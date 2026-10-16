"""研究任务管理：任务在后台运行，与 HTTP 连接解耦。

- 客户端断开不会中断研究；重连时可以从任意事件序号继续订阅（配合 SSE 的 Last-Event-ID）。
- 运行中的任务在内存里保存全部事件，新订阅者先回放历史事件，再实时接收新事件。
- 任务和事件同时写入数据库：任务结束后从内存移除，之后的查询和回放都读数据库，进程重启也不丢失。
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.agent.events import AgentEvent, EmitFn
from app.config import AgentMode
from app.services.store import TaskRow, TaskStore

logger = logging.getLogger(__name__)

TaskStatus = Literal["pending", "running", "completed", "failed"]


class Agent(Protocol):
    async def run(self, query: str, emit: EmitFn) -> str: ...


@dataclass
class ResearchTask:
    id: str
    query: str
    mode: AgentMode = "multi"
    status: TaskStatus = "pending"
    created_at: float = field(default_factory=time.time)
    report: str | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    events: list[AgentEvent] = field(default_factory=list)
    # 为 None 时不持久化（从数据库加载的已结束任务）
    store: TaskStore | None = field(default=None, repr=False)
    _cond: asyncio.Condition = field(default_factory=asyncio.Condition, repr=False)

    @classmethod
    def from_row(cls, row: TaskRow, events: list[AgentEvent]) -> "ResearchTask":
        return cls(
            id=row.id,
            query=row.query,
            mode=row.mode,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            created_at=row.created_at,
            report=row.report,
            sources=row.sources or [],
            error=row.error,
            events=events,
        )

    @property
    def finished(self) -> bool:
        return self.status in ("completed", "failed")

    async def emit(self, event: AgentEvent) -> None:
        async with self._cond:
            seq = len(self.events)
            self.events.append(event)
            self._cond.notify_all()
        await self._persist_event(seq, event)

    async def finish(self, status: TaskStatus) -> None:
        # 状态变更和 done 事件必须在同一把锁内完成，否则订阅者可能看到"已结束"却漏掉 done
        done = AgentEvent(type="done", data={"status": status})
        async with self._cond:
            self.status = status
            seq = len(self.events)
            self.events.append(done)
            self._cond.notify_all()
        await self.save()
        await self._persist_event(seq, done)

    async def save(self) -> None:
        if self.store is None:
            return
        try:
            await self.store.save_task(
                id=self.id,
                query=self.query,
                mode=self.mode,
                status=self.status,
                created_at=self.created_at,
                report=self.report,
                sources=self.sources,
                error=self.error,
            )
        except Exception:
            # 持久化失败不应中断研究，内存里的实时事件流仍然可用
            logger.exception("failed to save task %s", self.id)

    async def _persist_event(self, seq: int, event: AgentEvent) -> None:
        if self.store is None:
            return
        try:
            await self.store.add_event(self.id, seq, event)
        except Exception:
            logger.exception("failed to save event %d of task %s", seq, self.id)

    async def stream(
        self, start: int = 0, heartbeat: float = 15.0
    ) -> AsyncIterator[tuple[int, AgentEvent] | None]:
        """从第 start 个事件开始订阅。长时间没有新事件时产出 None，供上层发送心跳。"""
        idx = start
        while True:
            async with self._cond:
                if idx >= len(self.events):
                    if self.finished:
                        return
                    try:
                        async with asyncio.timeout(heartbeat):
                            await self._cond.wait()
                    except TimeoutError:
                        pass
                batch = self.events[idx:]

            if not batch:
                yield None
                continue
            for event in batch:
                yield idx, event
                idx += 1


class TaskManager:
    def __init__(self, agent_factory: Callable[[AgentMode], Agent], store: TaskStore):
        self._agent_factory = agent_factory
        self._store = store
        # 只保存运行中的任务，结束后移除
        self._live: dict[str, ResearchTask] = {}
        # 持有后台任务的强引用，防止被 GC 回收
        self._running: set[asyncio.Task[None]] = set()

    async def create(self, query: str, mode: AgentMode = "multi") -> ResearchTask:
        task = ResearchTask(id=uuid.uuid4().hex[:12], query=query, mode=mode, store=self._store)
        # 先落库再启动，保证返回 task_id 后立刻查询列表就能看到
        await task.save()
        self._live[task.id] = task
        bg = asyncio.create_task(self._run(task))
        self._running.add(bg)
        bg.add_done_callback(self._running.discard)
        return task

    async def get(self, task_id: str) -> ResearchTask | None:
        task = self._live.get(task_id)
        if task is not None:
            return task
        row = await self._store.get_task(task_id)
        if row is None:
            return None
        return ResearchTask.from_row(row, await self._store.load_events(task_id))

    async def list(self) -> list[TaskRow]:
        return await self._store.list_tasks()

    async def _run(self, task: ResearchTask) -> None:
        task.status = "running"
        await task.save()
        await task.emit(AgentEvent(type="status", data={"message": "开始研究"}))

        async def emit(event: AgentEvent) -> None:
            if event.type == "report":
                task.report = event.data["markdown"]
                task.sources = event.data["sources"]
            await task.emit(event)

        try:
            agent = self._agent_factory(task.mode)
            await agent.run(task.query, emit)
        except Exception as e:
            logger.exception("research task %s failed", task.id)
            task.error = str(e)
            await task.emit(AgentEvent(type="error", data={"message": str(e)}))
            await task.finish("failed")
        else:
            await task.finish("completed")
        # 正在订阅的连接持有 task 引用，不受影响；之后的请求改从数据库读取
        self._live.pop(task.id, None)

    async def shutdown(self) -> None:
        # 被取消的任务在数据库里仍是 running，下次启动时由 TaskStore.init 标记为中断
        for bg in list(self._running):
            bg.cancel()
        await asyncio.gather(*self._running, return_exceptions=True)
