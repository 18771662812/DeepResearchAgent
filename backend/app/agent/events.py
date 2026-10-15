import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "status",  # 任务级状态说明
    "phase",  # 多 Agent 模式的阶段切换：planning / researching / reflecting / writing
    "plan",  # Planner 产出的子问题列表
    "researcher_start",
    "researcher_done",  # Researcher 提交研究笔记（或失败）
    "reflection",  # Reflector 的评估结果与补充子问题
    "step",  # 工具循环进入第 n 轮
    "thought",  # 模型在调用工具前输出的说明文字
    "tool_call",
    "tool_result",
    "report",  # 最终报告 + 引用来源
    "usage",  # token 用量统计
    "error",
    "done",  # 流结束标记，前端收到后关闭连接
]


class AgentEvent(BaseModel):
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
    # 产生事件的子 Agent，如 "R1"；None 表示主流程
    agent: str | None = None
    ts: float = Field(default_factory=time.time)


EmitFn = Callable[[AgentEvent], Awaitable[None]]
