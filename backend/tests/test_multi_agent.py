import asyncio
import json
import re

from app.agent.events import AgentEvent
from app.agent.multi_agent import MultiAgent, MultiAgentConfig
from app.agent.sources import SourceRegistry
from app.llm import LLMResponse
from app.tools import ToolRegistry
from tests.fakes import FakeSearchTool, Messages, RoleLLM, final_response, tool_call_response, usage


def json_response(obj: dict) -> LLMResponse:
    return LLMResponse(content=json.dumps(obj, ensure_ascii=False), usage=usage())


def plan_handler(questions: list[str]):
    def handle(messages: Messages) -> LLMResponse:
        return json_response(
            {"brief": "目标", "sub_questions": [{"question": q, "goal": "g"} for q in questions]}
        )

    return handle


def researcher(messages: Messages) -> LLMResponse:
    """第一次调用发起搜索；拿到工具结果后，引用结果里的来源编号写笔记。"""
    sub_question = re.search(r"子问题：(.+)", messages[1]["content"]).group(1)
    if messages[-1]["role"] != "tool":
        return tool_call_response(sub_question)
    source_id = re.match(r"\[(\d+)\]", messages[-1]["content"]).group(1)
    return final_response(f"- 关于{sub_question}的发现 [{source_id}]")


def writer(messages: Messages) -> LLMResponse:
    ids = sorted(set(re.findall(r"\[(\d+)\]", messages[-1]["content"])))
    return final_response("# 报告\n" + "".join(f"结论 [{i}]。" for i in ids))


def run(llm: RoleLLM, config: MultiAgentConfig | None = None):
    sources = SourceRegistry()
    agent = MultiAgent(llm, ToolRegistry([FakeSearchTool(sources)]), sources, config)
    events: list[AgentEvent] = []

    async def emit(e: AgentEvent) -> None:
        events.append(e)

    report = asyncio.run(agent.run("总问题", emit))
    return report, events


def test_full_pipeline_with_follow_up_round():
    reflections = iter(
        [
            {
                "sufficient": False,
                "gaps": ["缺少 C"],
                "follow_up_questions": [{"question": "C", "goal": "g"}],
            },
        ]
    )
    llm = RoleLLM(
        {
            "planner": plan_handler(["A", "B"]),
            "researcher": researcher,
            "reflector": lambda m: json_response(next(reflections)),
            "writer": writer,
        }
    )
    report, events = run(llm, MultiAgentConfig(max_rounds=2))

    # 阶段顺序
    phases = [e.data["phase"] for e in events if e.type == "phase"]
    assert phases == ["planning", "researching", "reflecting", "researching", "writing"]

    # 计划 + 反思补充的子问题都被研究了，编号全局递增
    plan = next(e for e in events if e.type == "plan")
    assert [q["id"] for q in plan.data["sub_questions"]] == [1, 2]
    reflection = next(e for e in events if e.type == "reflection")
    assert reflection.data["follow_up_questions"][0] == {
        "id": 3,
        "question": "C",
        "goal": "g",
        "round": 2,
    }
    done = [e for e in events if e.type == "researcher_done"]
    assert sorted(e.data["id"] for e in done) == [1, 2, 3]
    assert all(e.data["ok"] for e in done)

    # Researcher 的事件都带有各自的标签
    assert {e.agent for e in events if e.type == "tool_call"} == {"R1", "R2", "R3"}
    assert all(e.agent is None for e in events if e.type in ("plan", "phase", "report"))

    # 上下文隔离：Writer 只看到笔记，看不到原始网页内容
    writer_input = llm.calls["writer"][0][-1]["content"]
    assert "关于A的发现" in writer_input and "关于C的发现" in writer_input
    assert "原始网页内容" not in writer_input

    # 并行 Researcher 共享来源编号，报告引用了 3 个不同来源
    report_event = next(e for e in events if e.type == "report")
    assert len(report_event.data["sources"]) == 3
    assert report.startswith("# 报告")

    # Planner / Reflector 使用 JSON 输出
    assert llm.json_mode_roles == {"planner", "reflector"}

    # 用量按角色统计，并记录压缩前后的字数
    u = next(e for e in events if e.type == "usage").data
    assert set(u["by_role"]) == {"planner", "researcher", "reflector", "writer"}
    assert u["calls"] == 1 + 3 * 2 + 1 + 1
    assert u["context"]["raw_chars"] > u["context"]["notes_chars"] > 0


def test_sufficient_reflection_skips_follow_up_round():
    llm = RoleLLM(
        {
            "planner": plan_handler(["A"]),
            "researcher": researcher,
            "reflector": lambda m: json_response({"sufficient": True}),
            "writer": writer,
        }
    )
    _, events = run(llm, MultiAgentConfig(max_rounds=3))
    phases = [e.data["phase"] for e in events if e.type == "phase"]
    assert phases == ["planning", "researching", "reflecting", "writing"]


def test_invalid_plan_json_retries_then_falls_back_to_original_question():
    llm = RoleLLM(
        {
            "planner": lambda m: LLMResponse(content="不是 JSON", usage=usage()),
            "researcher": researcher,
            "writer": writer,
        }
    )
    _, events = run(llm, MultiAgentConfig(max_rounds=1))
    assert len(llm.calls["planner"]) == 2  # 第一次失败后带着错误信息重试一次
    plan = next(e for e in events if e.type == "plan")
    assert [q["question"] for q in plan.data["sub_questions"]] == ["总问题"]


def test_one_failed_researcher_does_not_break_the_task():
    def flaky_researcher(messages: Messages) -> LLMResponse:
        if "子问题：坏" in messages[1]["content"]:
            raise ConnectionError("network down")
        return researcher(messages)

    llm = RoleLLM(
        {
            "planner": plan_handler(["好", "坏"]),
            "researcher": flaky_researcher,
            "writer": writer,
        }
    )
    report, events = run(llm, MultiAgentConfig(max_rounds=1))
    done = {e.data["id"]: e.data for e in events if e.type == "researcher_done"}
    assert done[1]["ok"] and not done[2]["ok"]
    assert "network down" in done[2]["error"]
    assert report.startswith("# 报告")


def test_concurrency_is_limited():
    running = 0
    peak = 0

    async def slow_chat(messages, tools=None, *, json_mode=False, name="llm"):
        nonlocal running, peak
        if name == "planner":
            return plan_handler(["A", "B", "C", "D"])(messages)
        if name == "writer":
            return writer(messages)
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return final_response("- 笔记")

    llm = RoleLLM({})
    llm.chat = slow_chat  # type: ignore[method-assign]
    run(llm, MultiAgentConfig(max_rounds=1, max_concurrency=2))
    assert peak == 2
