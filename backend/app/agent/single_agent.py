"""单 Agent 模式：一个工具循环同时负责检索和写报告。

结构简单、调用次数少；保留它作为基线，用来和多 Agent 模式做对比评测。
"""

from dataclasses import asdict
from datetime import date
from typing import Any

from app.agent.events import AgentEvent, EmitFn
from app.agent.loop import ChatModel, run_tool_loop
from app.agent.prompts import FORCE_FINISH_PROMPT, SYSTEM_PROMPT
from app.agent.sources import SourceRegistry
from app.tools import ToolRegistry


class SingleAgent:
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
        result = await run_tool_loop(
            self.llm,
            self.tools,
            messages,
            max_steps=self.max_steps,
            emit=emit,
            finish_prompt=FORCE_FINISH_PROMPT,
            name="single",
        )
        report = result.content

        cited = self.sources.cited_in(report)
        await emit(
            AgentEvent(
                type="report",
                data={"markdown": report, "sources": [s.public() for s in cited]},
            )
        )
        await emit(
            AgentEvent(
                type="usage",
                data={**asdict(result.usage), "context": {"raw_chars": result.raw_chars}},
            )
        )
        return report
