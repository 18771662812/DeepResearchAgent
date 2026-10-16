import asyncio
import time
from pathlib import Path

from app.agent.events import AgentEvent, EmitFn
from app.services.store import INTERRUPTED_MESSAGE, TaskStore
from app.services.task_manager import TaskManager


class StepAgent:
    async def run(self, query: str, emit: EmitFn) -> str:
        for i in range(3):
            await emit(AgentEvent(type="step", data={"step": i + 1}))
            await asyncio.sleep(0.01)
        await emit(AgentEvent(type="report", data={"markdown": "ok", "sources": []}))
        return "ok"


class FailingAgent:
    async def run(self, query: str, emit: EmitFn) -> str:
        raise RuntimeError("未配置 KEY")


class HangingAgent:
    async def run(self, query: str, emit: EmitFn) -> str:
        await emit(AgentEvent(type="step", data={"step": 1}))
        await asyncio.sleep(3600)
        return ""


async def open_store(tmp_path: Path) -> TaskStore:
    store = TaskStore(f"sqlite+aiosqlite:///{(tmp_path / 'tasks.db').as_posix()}")
    await store.init()
    return store


async def collect(manager: TaskManager, task_id: str, start: int = 0) -> list[AgentEvent]:
    task = await manager.get(task_id)
    assert task is not None
    return [item[1] async for item in task.stream(start) if item is not None]


async def wait_finished(manager: TaskManager, task_id: str) -> None:
    await collect(manager, task_id)
    # 订阅结束时 done 已推送，但落库和移出内存在其后完成
    for _ in range(100):
        if task_id not in manager._live:
            return
        await asyncio.sleep(0.01)


def test_stream_receives_all_events_and_ends_with_done(tmp_path):
    async def main():
        store = await open_store(tmp_path)
        manager = TaskManager(lambda mode: StepAgent(), store)
        task = await manager.create("q")
        events = await collect(manager, task.id)
        # 结束后订阅，从中间序号开始回放（模拟断线重连）
        replay = await collect(manager, task.id, start=3)
        await store.close()
        return task, events, replay

    task, events, replay = asyncio.run(main())
    assert [e.type for e in events] == ["status", "step", "step", "step", "report", "done"]
    assert [e.type for e in replay] == ["step", "report", "done"]
    assert task.status == "completed" and task.report == "ok"


def test_failure_is_reported_as_error_event(tmp_path):
    async def main():
        store = await open_store(tmp_path)
        manager = TaskManager(lambda mode: FailingAgent(), store)
        task = await manager.create("q")
        events = await collect(manager, task.id)
        await store.close()
        return task, events

    task, events = asyncio.run(main())
    assert [e.type for e in events] == ["status", "error", "done"]
    assert task.status == "failed" and "KEY" in (task.error or "")


def test_finished_task_survives_restart(tmp_path):
    async def first_run() -> tuple[str, list[AgentEvent]]:
        store = await open_store(tmp_path)
        manager = TaskManager(lambda mode: StepAgent(), store)
        task = await manager.create("持久化", mode="single")
        await wait_finished(manager, task.id)
        events = list(task.events)
        await store.close()
        return task.id, events

    async def after_restart(task_id: str):
        store = await open_store(tmp_path)
        manager = TaskManager(lambda mode: StepAgent(), store)
        listed = await manager.list()
        task = await manager.get(task_id)
        assert task is not None
        replay = await collect(manager, task_id)
        await store.close()
        return listed, task, replay

    task_id, original = asyncio.run(first_run())
    listed, task, replay = asyncio.run(after_restart(task_id))

    assert [t.id for t in listed] == [task_id]
    assert task.status == "completed" and task.report == "ok" and task.mode == "single"
    assert [e.model_dump() for e in replay] == [e.model_dump() for e in original]


def test_interrupted_task_is_marked_failed_on_restart(tmp_path):
    async def first_run() -> str:
        store = await open_store(tmp_path)
        manager = TaskManager(lambda mode: HangingAgent(), store)
        task = await manager.create("q")
        while len(task.events) < 2:
            await asyncio.sleep(0.01)
        await manager.shutdown()
        await store.close()
        return task.id

    async def after_restart(task_id: str):
        store = await open_store(tmp_path)
        manager = TaskManager(lambda mode: StepAgent(), store)
        task = await manager.get(task_id)
        assert task is not None
        events = await collect(manager, task_id)
        await store.close()
        return task, events

    task_id = asyncio.run(first_run())
    task, events = asyncio.run(after_restart(task_id))

    assert task.status == "failed" and task.error == INTERRUPTED_MESSAGE
    # 补写的事件接在原有事件之后，并以 done 结尾，前端才能正常关闭连接
    assert [e.type for e in events] == ["status", "step", "error", "done"]


def test_list_is_newest_first(tmp_path):
    async def main():
        store = await open_store(tmp_path)
        manager = TaskManager(lambda mode: StepAgent(), store)
        ids = []
        for q in ("a", "b"):
            task = await manager.create(q)
            ids.append(task.id)
            await wait_finished(manager, task.id)
            time.sleep(0.01)
        listed = [t.id for t in await manager.list()]
        await store.close()
        return ids, listed

    ids, listed = asyncio.run(main())
    assert listed == ids[::-1]
