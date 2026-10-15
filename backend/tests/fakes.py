"""测试用的假 LLM 和假工具，让 Agent 循环可以脱离真实 API 运行。"""

from typing import Any

from app.agent.sources import SourceRegistry
from app.llm import LLMResponse, ToolCall, Usage
from app.tools import Tool


class ScriptedLLM:
    """按顺序返回预设的回复，并记录每次收到的消息。"""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        self.calls.append(list(messages))
        return self._responses.pop(0)


class FakeSearchTool(Tool):
    name = "web_search"
    description = "fake search"
    parameters = {"type": "object", "properties": {"query": {"type": "string"}}}

    def __init__(self, sources: SourceRegistry):
        self._sources = sources

    async def run(self, query: str) -> str:
        src = self._sources.add(f"https://example.com/{query}", f"About {query}")
        return f"[{src.id}] {src.title}"


def tool_call_response(*queries: str) -> LLMResponse:
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id=f"call_{i}", name="web_search", arguments=f'{{"query": "{q}"}}')
            for i, q in enumerate(queries)
        ],
        usage=Usage(prompt_tokens=100, completion_tokens=10, calls=1),
    )


def final_response(text: str) -> LLMResponse:
    return LLMResponse(content=text, usage=Usage(prompt_tokens=200, completion_tokens=50, calls=1))
