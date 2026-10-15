from collections.abc import AsyncIterable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from app.config import AgentMode, get_settings
from app.services.task_manager import ResearchTask, TaskManager, TaskStatus

router = APIRouter(prefix="/api/research", tags=["research"])


class CreateResearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    # multi：多 Agent 深度研究；single：单 Agent 快速研究；不填使用服务端默认配置
    mode: AgentMode | None = None


class CreateResearchResponse(BaseModel):
    task_id: str


class TaskSummary(BaseModel):
    id: str
    query: str
    mode: AgentMode
    status: TaskStatus
    created_at: float
    error: str | None = None


class TaskDetail(TaskSummary):
    report: str | None = None
    sources: list[dict[str, Any]] = []


def get_manager(request: Request) -> TaskManager:
    return request.app.state.task_manager


Manager = Annotated[TaskManager, Depends(get_manager)]


def get_task(task_id: str, manager: Manager) -> ResearchTask:
    # 放在依赖里校验：SSE 响应开始后就无法再返回 404 了
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


Task = Annotated[ResearchTask, Depends(get_task)]


def _summary(task: ResearchTask) -> TaskSummary:
    return TaskSummary(
        id=task.id,
        query=task.query,
        mode=task.mode,
        status=task.status,
        created_at=task.created_at,
        error=task.error,
    )


@router.post("", status_code=201)
async def create_research(body: CreateResearchRequest, manager: Manager) -> CreateResearchResponse:
    task = manager.create(body.query.strip(), body.mode or get_settings().agent_mode)
    return CreateResearchResponse(task_id=task.id)


@router.get("")
async def list_research(manager: Manager) -> list[TaskSummary]:
    return [_summary(t) for t in manager.list()]


@router.get("/{task_id}")
async def get_research(task: Task) -> TaskDetail:
    return TaskDetail(**_summary(task).model_dump(), report=task.report, sources=task.sources)


@router.get("/{task_id}/events", response_class=EventSourceResponse)
async def stream_events(
    task: Task,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    """SSE 事件流。浏览器 EventSource 断线重连时会自动带上 Last-Event-ID，从断点继续推送。"""
    start = last_event_id + 1 if last_event_id is not None else 0
    async for item in task.stream(start):
        if item is None:
            yield ServerSentEvent(comment="ping")
            continue
        idx, event = item
        yield ServerSentEvent(data=event, id=str(idx))
