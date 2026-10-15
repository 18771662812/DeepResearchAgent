"""结构化输出：要求模型输出 JSON，用 Pydantic 校验，不合法时把错误反馈给模型重试。"""

import logging
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.client import LLMResponse, Usage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class JSONChatModel(Protocol):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        json_mode: bool = False,
        name: str = "llm",
    ) -> LLMResponse: ...


class StructuredOutputError(ValueError):
    pass


async def chat_json(
    llm: JSONChatModel,
    messages: list[dict[str, Any]],
    schema: type[T],
    *,
    name: str,
    usage: Usage | None = None,
    attempts: int = 2,
) -> T:
    """返回校验后的对象；所有尝试都失败时抛出 StructuredOutputError。

    usage 不为 None 时，每次调用的用量都会累加进去（包括失败的那次）。
    """
    for _ in range(attempts):
        resp = await llm.chat(messages, json_mode=True, name=name)
        if usage is not None:
            usage.add(resp.usage)
        try:
            return schema.model_validate_json(resp.content)
        except ValidationError as e:
            logger.warning("%s returned invalid JSON: %s", name, e)
            # 只回传 content：非工具调用轮次不需要 reasoning_content
            messages = [
                *messages,
                {"role": "assistant", "content": resp.content},
                {"role": "user", "content": f"输出不符合要求：{e}\n请只输出符合格式的 JSON。"},
            ]
    raise StructuredOutputError(f"{name} 未能输出合法的 JSON")
