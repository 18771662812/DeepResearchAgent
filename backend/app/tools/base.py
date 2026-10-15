import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict[str, Any]]  # JSON Schema

    @abstractmethod
    async def run(self, **kwargs: Any) -> str: ...

    def spec(self) -> dict[str, Any]:
        """OpenAI / DeepSeek 格式的工具定义。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """统一负责工具的查找、参数解析、超时和异常处理。

    任何错误都转成文本返回给模型，而不是抛出去中断循环：
    模型看到错误信息后通常能自己修正（换关键词、换 URL、修正参数）。
    """

    def __init__(self, tools: Iterable[Tool], timeout: float = 30.0):
        self._tools = {t.name: t for t in tools}
        self._timeout = timeout

    def specs(self) -> list[dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]

    async def call(self, name: str, arguments: str) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"错误：不存在名为 {name} 的工具。可用工具：{', '.join(self._tools)}"

        try:
            kwargs = json.loads(arguments or "{}")
        except json.JSONDecodeError as e:
            return f"错误：工具参数不是合法的 JSON（{e}），请重新生成参数。"
        if not isinstance(kwargs, dict):
            return "错误：工具参数必须是 JSON 对象。"

        try:
            return await asyncio.wait_for(tool.run(**kwargs), timeout=self._timeout)
        except TimeoutError:
            return f"错误：工具 {name} 执行超时（{self._timeout:.0f}s），请换一个来源或关键词。"
        except Exception as e:
            logger.warning("tool %s failed: %r", name, e)
            return f"错误：工具 {name} 执行失败：{type(e).__name__}: {e}"
