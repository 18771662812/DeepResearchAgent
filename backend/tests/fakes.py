"""测试用的假 LLM 和假工具，让 Agent 可以脱离真实 API 运行。"""

import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from app.agent.sources import SourceRegistry
from app.llm import LLMResponse, ToolCall, Usage
from app.tools import Tool

Messages = list[dict[str, Any]]


class ScriptedLLM:
    """按顺序返回预设的回复，并记录每次收到的消息。适用于串行调用的单 Agent。"""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[Messages] = []

    async def chat(self, messages: Messages, tools: Any = None, **kwargs: Any) -> LLMResponse:
        self.calls.append(list(messages))
        return self._responses.pop(0)


class RoleLLM:
    """按调用方角色（name 参数）分派给不同的处理函数，适用于并发调用的多 Agent。

    处理函数根据收到的消息决定回复，因此与并发调度顺序无关。
    """

    def __init__(self, handlers: dict[str, Callable[[Messages], LLMResponse]]):
        self._handlers = handlers
        self.calls: dict[str, list[Messages]] = defaultdict(list)
        self.json_mode_roles: set[str] = set()

    async def chat(
        self, messages: Messages, tools: Any = None, *, json_mode: bool = False, name: str = "llm"
    ) -> LLMResponse:
        self.calls[name].append(list(messages))
        if json_mode:
            self.json_mode_roles.add(name)
        await asyncio.sleep(0)  # 让出控制权，模拟真实的并发交错
        return self._handlers[name](messages)


class FakeSearchTool(Tool):
    name = "web_search"
    description = "fake search"
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

    def __init__(self, sources: SourceRegistry):
        self._sources = sources

    async def run(self, query: str) -> str:
        src = self._sources.add(f"https://example.com/{query}", f"About {query}")
        return f"[{src.id}] {src.title}\n原始网页内容：{'x' * 500}"


def usage(prompt: int = 100, completion: int = 10) -> Usage:
    return Usage(prompt_tokens=prompt, completion_tokens=completion, calls=1)


def tool_call_response(*queries: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id=f"call_{i}", name="web_search", arguments=f'{{"query": "{q}"}}')
            for i, q in enumerate(queries)
        ],
        usage=usage(),
    )


def final_response(text: str) -> LLMResponse:
    return LLMResponse(content=text, usage=usage(200, 50))
