import time
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "status",  # 任务级状态说明
    "step",  # 进入第 n 轮循环
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
    ts: float = Field(default_factory=time.time)
