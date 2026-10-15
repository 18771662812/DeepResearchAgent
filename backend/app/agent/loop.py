"""手写的 tool-use 循环，单 Agent 和多 Agent 中的 Researcher 共用。

调用 LLM -> 有工具调用就并行执行、把结果追加回对话 -> 再次调用 LLM
-> 直到模型不再调用工具，或达到步数上限后强制收尾。
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.agent.events import AgentEvent, EmitFn
from app.llm import LLMResponse, ToolCall, Usage
from app.tools import ToolRegistry

RESULT_PREVIEW_CHARS = 300


class ChatModel(Protocol):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        json_mode: bool = False,
        name: str = "llm",
    ) -> LLMResponse: ...


@dataclass
class LoopResult:
    content: str
    usage: Usage
    steps: int
    # 工具返回的原始内容总字数，用来衡量上下文压缩的效果
    raw_chars: int


def _parse_args(arguments: str) -> Any:
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments


async def run_tool_loop(
    llm: ChatModel,
    tools: ToolRegistry,
    messages: list[dict[str, Any]],
    *,
    max_steps: int,
    emit: EmitFn,
    finish_prompt: str,
    name: str = "agent",
) -> LoopResult:
    """运行工具循环，会原地追加 messages。"""
    usage = Usage()
    raw_chars = 0

    for step in range(1, max_steps + 1):
        await emit(AgentEvent(type="step", data={"step": step}))

        resp = await llm.chat(messages, tools=tools.specs(), name=name)
        usage.add(resp.usage)
        messages.append(resp.to_message())

        if not resp.tool_calls:
            return LoopResult(resp.content, usage, step, raw_chars)

        if resp.content.strip():
            await emit(AgentEvent(type="thought", data={"content": resp.content}))
        raw_chars += await _run_tool_calls(tools, resp.tool_calls, messages, emit)

    await emit(AgentEvent(type="status", data={"message": "达到步数上限，基于已有信息收尾"}))
    messages.append({"role": "user", "content": finish_prompt})
    resp = await llm.chat(messages, name=name)
    usage.add(resp.usage)
    return LoopResult(resp.content, usage, max_steps, raw_chars)


async def _run_tool_calls(
    tools: ToolRegistry, calls: list[ToolCall], messages: list[dict[str, Any]], emit: EmitFn
) -> int:
    for call in calls:
        await emit(
            AgentEvent(
                type="tool_call",
                data={"id": call.id, "name": call.name, "args": _parse_args(call.arguments)},
            )
        )

    # 同一轮的多个工具调用互不依赖，并行执行
    results = await asyncio.gather(*(tools.call(c.name, c.arguments) for c in calls))

    for call, result in zip(calls, results, strict=True):
        await emit(
            AgentEvent(
                type="tool_result",
                data={
                    "id": call.id,
                    "name": call.name,
                    "preview": result[:RESULT_PREVIEW_CHARS],
                    "length": len(result),
                },
            )
        )
        messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    return sum(len(r) for r in results)
