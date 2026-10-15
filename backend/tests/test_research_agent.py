import asyncio

from app.agent.events import AgentEvent
from app.agent.research_agent import ResearchAgent
from app.agent.sources import SourceRegistry
from app.tools import ToolRegistry
from tests.fakes import FakeSearchTool, ScriptedLLM, final_response, tool_call_response


def run_agent(llm: ScriptedLLM, max_steps: int = 5) -> tuple[str, list[AgentEvent]]:
    sources = SourceRegistry()
    agent = ResearchAgent(llm, ToolRegistry([FakeSearchTool(sources)]), sources, max_steps)
    events: list[AgentEvent] = []

    async def emit(e: AgentEvent) -> None:
        events.append(e)

    report = asyncio.run(agent.run("测试问题", emit))
    return report, events


def test_loop_runs_tools_then_returns_report_with_cited_sources():
    llm = ScriptedLLM(
        [
            tool_call_response("a", "b"),  # 一轮并行两个工具调用
            final_response("# 报告\n结论 [2]。"),
        ]
    )
    report, events = run_agent(llm)

    assert report.startswith("# 报告")
    types = [e.type for e in events]
    assert types == [
        "step",
        "tool_call",
        "tool_call",
        "tool_result",
        "tool_result",
        "step",
        "report",
        "usage",
    ]

    # 只有被引用的来源出现在报告里
    report_event = next(e for e in events if e.type == "report")
    assert [s["id"] for s in report_event.data["sources"]] == [2]

    # 第二次调用 LLM 时，历史里应包含 assistant 的 tool_calls 和两条 tool 结果
    second_call = llm.calls[1]
    assert second_call[2]["role"] == "assistant" and len(second_call[2]["tool_calls"]) == 2
    assert [m["tool_call_id"] for m in second_call[3:]] == ["call_0", "call_1"]

    usage = next(e for e in events if e.type == "usage").data
    assert usage["calls"] == 2 and usage["prompt_tokens"] == 300


def test_force_finish_when_step_budget_exhausted():
    llm = ScriptedLLM(
        [
            tool_call_response("a"),
            tool_call_response("b"),
            final_response("收尾报告 [1]"),
        ]
    )
    report, events = run_agent(llm, max_steps=2)

    assert report == "收尾报告 [1]"
    assert any(e.type == "status" for e in events)
    # 强制收尾那次调用不带工具，最后一条消息是收尾指令
    assert llm.calls[-1][-1]["role"] == "user"
