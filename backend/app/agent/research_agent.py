"""阶段 1：单 Agent + 手写 tool-use 循环。

循环逻辑：
    调用 LLM -> 有工具调用就并行执行、把结果追加回对话 -> 再次调用 LLM
    -> 直到模型不再调用工具（即输出了最终报告），或达到步数上限后强制收尾。

后续阶段在此基础上演进：Planner 拆解子问题 -> 多个 Researcher 并行 -> Reflector 查漏补缺。
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import date
from typing import Any, Protocol

from app.agent.events import AgentEvent
from app.agent.prompts import FORCE_FINISH_PROMPT, SYSTEM_PROMPT
from app.agent.sources import SourceRegistry
from app.llm import LLMResponse, ToolCall, Usage
from app.tools import ToolRegistry

EmitFn = Callable[[AgentEvent], Awaitable[None]]

RESULT_PREVIEW_CHARS = 300


class ChatModel(Protocol):
    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse: ...


def _parse_args(arguments: str) -> Any:
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments


class ResearchAgent:
    def __init__(
        self,
        llm: ChatModel,
        tools: ToolRegistry,
        sources: SourceRegistry,
        max_steps: int = 10,
    ):
        self.llm = llm
        self.tools = tools
        self.sources = sources
        self.max_steps = max_steps

    async def run(self, query: str, emit: EmitFn) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(today=date.today().isoformat())},
            {"role": "user", "content": query},
        ]
        usage = Usage()
        report: str | None = None

        for step in range(1, self.max_steps + 1):
            await emit(AgentEvent(type="step", data={"step": step}))

            resp = await self.llm.chat(messages, tools=self.tools.specs())
            usage.add(resp.usage)
            messages.append(resp.to_message())

            if not resp.tool_calls:
                report = resp.content
                break

            if resp.content.strip():
                await emit(AgentEvent(type="thought", data={"content": resp.content}))
            await self._run_tool_calls(resp.tool_calls, messages, emit)

        if report is None:
            await emit(AgentEvent(type="status", data={"message": "达到步数上限，开始撰写报告"}))
            messages.append({"role": "user", "content": FORCE_FINISH_PROMPT})
            resp = await self.llm.chat(messages)
            usage.add(resp.usage)
            report = resp.content

        cited = self.sources.cited_in(report)
        await emit(
            AgentEvent(
                type="report",
                data={"markdown": report, "sources": [asdict(s) for s in cited]},
            )
        )
        await emit(AgentEvent(type="usage", data=asdict(usage)))
        return report

    async def _run_tool_calls(
        self, calls: list[ToolCall], messages: list[dict[str, Any]], emit: EmitFn
    ) -> None:
        for call in calls:
            await emit(
                AgentEvent(
                    type="tool_call",
                    data={"id": call.id, "name": call.name, "args": _parse_args(call.arguments)},
                )
            )

        # 同一轮的多个工具调用互不依赖，并行执行
        results = await asyncio.gather(*(self.tools.call(c.name, c.arguments) for c in calls))

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
