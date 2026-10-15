"""研究任务管理：任务在后台运行，与 HTTP 连接解耦。

- 客户端断开不会中断研究；重连时可以从任意事件序号继续订阅（配合 SSE 的 Last-Event-ID）。
- 所有事件按序保存在内存里，新订阅者会先回放历史事件，再实时接收新事件。

TODO: 目前存储在内存中，进程重启即丢失；后续可换成 Postgres（任务/报告）+ Redis Stream（事件）。
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
    _cond: asyncio.Condition = field(default_factory=asyncio.Condition, repr=False)

    @property
    def finished(self) -> bool:
        return self.status in ("completed", "failed")

    async def emit(self, event: AgentEvent) -> None:
        async with self._cond:
            self.events.append(event)
            self._cond.notify_all()

    async def finish(self, status: TaskStatus) -> None:
        # 状态变更和 done 事件必须在同一把锁内完成，否则订阅者可能看到"已结束"却漏掉 done
        async with self._cond:
            self.status = status
            self.events.append(AgentEvent(type="done", data={"status": status}))
            self._cond.notify_all()

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
    def __init__(self, agent_factory: Callable[[AgentMode], Agent]):
        self._agent_factory = agent_factory
        self._tasks: dict[str, ResearchTask] = {}
        # 持有后台任务的强引用，防止被 GC 回收
        self._running: set[asyncio.Task[None]] = set()

    def create(self, query: str, mode: AgentMode = "multi") -> ResearchTask:
        task = ResearchTask(id=uuid.uuid4().hex[:12], query=query, mode=mode)
        self._tasks[task.id] = task
        bg = asyncio.create_task(self._run(task))
        self._running.add(bg)
        bg.add_done_callback(self._running.discard)
        return task

    def get(self, task_id: str) -> ResearchTask | None:
        return self._tasks.get(task_id)

    def list(self) -> list[ResearchTask]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    async def _run(self, task: ResearchTask) -> None:
        task.status = "running"
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

    async def shutdown(self) -> None:
        for bg in list(self._running):
            bg.cancel()
        await asyncio.gather(*self._running, return_exceptions=True)
