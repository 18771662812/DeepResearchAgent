import asyncio
from typing import Any

from app.tools import Tool, ToolRegistry


class EchoTool(Tool):
    name = "echo"
    description = "echo"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}

    async def run(self, text: str) -> str:
        return text


class BrokenTool(Tool):
    name = "broken"
    description = "always fails"
    parameters = {"type": "object", "properties": {}}

    async def run(self, **kwargs: Any) -> str:
        raise ConnectionError("boom")


class SlowTool(Tool):
    name = "slow"
    description = "never finishes in time"
    parameters = {"type": "object", "properties": {}}

    async def run(self, **kwargs: Any) -> str:
        await asyncio.sleep(10)
        return "done"


def call(registry: ToolRegistry, name: str, args: str) -> str:
    return asyncio.run(registry.call(name, args))


def test_success():
    assert call(ToolRegistry([EchoTool()]), "echo", '{"text": "hi"}') == "hi"


def test_errors_are_returned_as_text_not_raised():
    reg = ToolRegistry([EchoTool(), BrokenTool(), SlowTool()], timeout=0.05)
    assert "不存在" in call(reg, "nope", "{}")
    assert "JSON" in call(reg, "echo", "{bad json")
    assert "ConnectionError" in call(reg, "broken", "{}")
    assert "超时" in call(reg, "slow", "{}")
    # 参数名错误（TypeError）同样不会中断
    assert "失败" in call(reg, "echo", '{"wrong": 1}')


def test_specs_format():
    spec = ToolRegistry([EchoTool()]).specs()[0]
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "echo"
