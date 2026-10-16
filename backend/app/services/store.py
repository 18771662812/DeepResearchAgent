"""任务持久化：任务和事件写入 SQLite，进程重启后历史记录仍在。

通过 SQLAlchemy 访问数据库，换成 Postgres 只需修改 DATABASE_URL。
事件逐条写入（每次一个小事务），开启 WAL 后写入不会阻塞读取。
"""

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, String, Text, event, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.agent.events import AgentEvent

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "服务重启，任务被中断"


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    query: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[float] = mapped_column(Float, index=True)
    report: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)


class EventRow(Base):
    __tablename__ = "events"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    agent: Mapped[str | None] = mapped_column(String(16))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    ts: Mapped[float] = mapped_column(Float)

    @classmethod
    def from_event(cls, task_id: str, seq: int, ev: AgentEvent) -> "EventRow":
        return cls(task_id=task_id, seq=seq, type=ev.type, agent=ev.agent, data=ev.data, ts=ev.ts)

    def to_event(self) -> AgentEvent:
        return AgentEvent.model_validate(
            {"type": self.type, "agent": self.agent, "data": self.data, "ts": self.ts}
        )


class TaskStore:
    def __init__(self, url: str):
        db_url = make_url(url)
        self._is_sqlite = db_url.get_backend_name() == "sqlite"
        if self._is_sqlite and db_url.database not in (None, "", ":memory:"):
            Path(db_url.database).parent.mkdir(parents=True, exist_ok=True)

        # timeout：写锁被占用时最多等待的秒数，避免并发写入直接报 database is locked
        connect_args = {"timeout": 30} if self._is_sqlite else {}
        self._engine = create_async_engine(url, connect_args=connect_args)
        self._session = async_sessionmaker(self._engine, expire_on_commit=False)

        if self._is_sqlite:
            event.listen(self._engine.sync_engine, "connect", _sqlite_pragmas)

    async def init(self) -> None:
        """建表，并把上次进程退出时没跑完的任务标记为失败。"""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        recovered = await self._recover_interrupted()
        if recovered:
            logger.warning("marked %d interrupted task(s) as failed", recovered)

    async def close(self) -> None:
        await self._engine.dispose()

    async def save_task(
        self,
        *,
        id: str,
        query: str,
        mode: str,
        status: str,
        created_at: float,
        report: str | None,
        sources: list[dict[str, Any]],
        error: str | None,
    ) -> None:
        async with self._session.begin() as s:
            await s.merge(
                TaskRow(
                    id=id,
                    query=query,
                    mode=mode,
                    status=status,
                    created_at=created_at,
                    report=report,
                    sources=sources,
                    error=error,
                )
            )

    async def add_event(self, task_id: str, seq: int, ev: AgentEvent) -> None:
        async with self._session.begin() as s:
            s.add(EventRow.from_event(task_id, seq, ev))

    async def list_tasks(self, limit: int = 100) -> list[TaskRow]:
        async with self._session() as s:
            stmt = select(TaskRow).order_by(TaskRow.created_at.desc()).limit(limit)
            return list(await s.scalars(stmt))

    async def get_task(self, task_id: str) -> TaskRow | None:
        async with self._session() as s:
            return await s.get(TaskRow, task_id)

    async def load_events(self, task_id: str) -> list[AgentEvent]:
        async with self._session() as s:
            stmt = select(EventRow).where(EventRow.task_id == task_id).order_by(EventRow.seq)
            return [row.to_event() for row in await s.scalars(stmt)]

    async def _recover_interrupted(self) -> int:
        """补写 error 和 done 事件：前端收到 done 才会关闭 EventSource，否则会不停重连。"""
        async with self._session.begin() as s:
            rows = list(
                await s.scalars(select(TaskRow).where(TaskRow.status.in_(("pending", "running"))))
            )
            for row in rows:
                row.status = "failed"
                row.error = INTERRUPTED_MESSAGE
                await _append_events(
                    s,
                    row.id,
                    AgentEvent(type="error", data={"message": INTERRUPTED_MESSAGE}),
                    AgentEvent(type="done", data={"status": "failed"}),
                )
            return len(rows)


async def _append_events(s: AsyncSession, task_id: str, *events: AgentEvent) -> None:
    last = await s.scalar(select(func.max(EventRow.seq)).where(EventRow.task_id == task_id))
    start = -1 if last is None else last
    s.add_all(EventRow.from_event(task_id, start + 1 + i, ev) for i, ev in enumerate(events))


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    # WAL：读写可以并发；NORMAL 在 WAL 下足够安全且写入更快
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
