import asyncio

from app.agent.events import AgentEvent, EmitFn
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


async def collect(manager: TaskManager, task_id: str, start: int = 0) -> list[AgentEvent]:
    task = manager.get(task_id)
    assert task is not None
    return [item[1] async for item in task.stream(start) if item is not None]


def test_stream_receives_all_events_and_ends_with_done():
    async def main():
        manager = TaskManager(lambda mode: StepAgent())
        task = manager.create("q")
        events = await collect(manager, task.id)
        # 结束后订阅，从中间序号开始回放（模拟断线重连）
        replay = await collect(manager, task.id, start=3)
        return task, events, replay

    task, events, replay = asyncio.run(main())
    assert [e.type for e in events] == ["status", "step", "step", "step", "report", "done"]
    assert [e.type for e in replay] == ["step", "report", "done"]
    assert task.status == "completed" and task.report == "ok"


def test_failure_is_reported_as_error_event():
    async def main():
        manager = TaskManager(lambda mode: FailingAgent())
        task = manager.create("q")
        return task, await collect(manager, task.id)

    task, events = asyncio.run(main())
    assert [e.type for e in events] == ["status", "error", "done"]
    assert task.status == "failed" and "KEY" in (task.error or "")
