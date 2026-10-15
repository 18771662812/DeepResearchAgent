"""DeepSeek 客户端（OpenAI 兼容接口）。

只封装 Agent 需要的最小能力：带工具的一次对话调用，并统一 token 用量的统计口径。
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings, get_settings


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # DeepSeek 自动上下文缓存命中的 token 数，命中部分价格约为未命中的 1/50
    cache_hit_tokens: int = 0
    calls: int = 0

    def add(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cache_hit_tokens += other.cache_hit_tokens
        self.calls += other.calls


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # 模型生成的原始 JSON 字符串，可能不合法


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str | None = None
    usage: Usage = field(default_factory=Usage)

    def to_message(self) -> dict[str, Any]:
        """转成可以追加回对话历史的 assistant 消息。"""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        # 思考模式下发生工具调用时，DeepSeek 要求把 reasoning_content 原样回传
        if self.reasoning_content:
            msg["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in self.tool_calls
            ]
        return msg


class LLMClient:
    def __init__(self, settings: Settings):
        self._api_key = settings.deepseek_api_key
        self._client = AsyncOpenAI(
            api_key=settings.deepseek_api_key or "not-configured",
            base_url=settings.deepseek_base_url,
            timeout=settings.llm_timeout,
        )
        self.model = settings.llm_model
        self.reasoning_effort = settings.llm_reasoning_effort

    def _thinking_params(self) -> dict[str, Any]:
        if self.reasoning_effort == "none":
            return {"thinking": {"type": "disabled"}}
        return {"thinking": {"type": "enabled"}, "reasoning_effort": self.reasoning_effort}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY，请在 backend/.env 中填写")

        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = tools

        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            extra_body=self._thinking_params(),
            **kwargs,
        )
        msg = resp.choices[0].message

        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
            for tc in (msg.tool_calls or [])
            if tc.type == "function"
        ]

        usage = Usage(calls=1)
        if resp.usage:
            usage.prompt_tokens = resp.usage.prompt_tokens
            usage.completion_tokens = resp.usage.completion_tokens
            usage.cache_hit_tokens = getattr(resp.usage, "prompt_cache_hit_tokens", 0) or 0

        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            reasoning_content=getattr(msg, "reasoning_content", None),
            usage=usage,
        )


@lru_cache
def get_llm_client() -> LLMClient:
    # 全局复用一个客户端，共享底层 HTTP 连接池
    return LLMClient(get_settings())
