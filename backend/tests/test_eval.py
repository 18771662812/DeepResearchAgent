import asyncio
import json

from app.agent.events import AgentEvent
from app.agent.sources import SourceRegistry
from app.llm import LLMResponse
from eval.citations import extract_claims, sample_claims, select_passages
from eval.dataset import EvalQuestion, load_questions
from eval.judges import Judge
from eval.pricing import estimate_cost
from eval.records import RunRecord, SourceRecord
from eval.report import summarize, to_markdown
from eval.runner import compare_modes, judge_record, run_research
from tests.fakes import Messages, RoleLLM, usage

QUESTION = EvalQuestion(id="q1", category="技术", question="问题", key_points=["要点一", "要点二"])


def json_response(obj: dict) -> LLMResponse:
    return LLMResponse(content=json.dumps(obj, ensure_ascii=False), usage=usage())


def test_dataset_is_valid():
    questions = load_questions()
    assert len(questions) >= 10
    assert len({q.id for q in questions}) == len(questions)


def test_extract_claims():
    report = (
        "# 标题\n"
        "2026 年出口 400 万辆 [1]。增速很快 [2, 3]！没有引用的句子。\n"
        "- **要点**：数据见此 [4]\n"
        "2026 年出口 400 万辆 [1]。\n"  # 重复陈述只算一次
        "短 [5]。"
    )
    claims = extract_claims(report)
    assert [(c.text, c.source_ids) for c in claims] == [
        ("2026 年出口 400 万辆。", [1]),
        ("增速很快！", [2, 3]),
        ("要点：数据见此", [4]),
    ]
    assert sample_claims(claims, 2, seed=1) == sample_claims(claims, 2, seed=1)
    assert len(sample_claims(claims, 10, seed=1)) == 3


def test_select_passages_finds_evidence_beyond_the_head():
    filler = "无关的背景介绍内容。" * 300  # 约 3000 字
    content = filler + "自适应分块在临床研究中达到 87% 准确率。" + filler
    picked = select_passages(content, "自适应分块达 87% 准确率", budget=1000, window=200)
    assert "87% 准确率" in picked
    assert len(picked) <= 1000 + 20  # 片段之间的分隔符
    assert select_passages("短文", "任意", budget=1000) == "短文"


def test_estimate_cost():
    # 1M 未命中输入 + 1M 命中输入 + 1M 输出
    assert estimate_cost("deepseek-flash", 2_000_000, 1_000_000, 1_000_000) == 0.3 + 0.006 + 1.2
    assert estimate_cost("unknown-model", 100, 0, 100) == 0.0


def test_run_research_collects_metrics():
    class FakeAgent:
        def __init__(self):
            self.sources = SourceRegistry()

        async def run(self, query, emit):
            self.sources.add("https://a.com", "A", "摘要", content="完整正文")
            for name, preview in [
                ("web_search", "[1] A"),
                ("web_search", "没有找到相关结果"),
                ("fetch_url", "错误：403"),
            ]:
                await emit(AgentEvent(type="tool_result", data={"name": name, "preview": preview}))
            await emit(
                AgentEvent(
                    type="usage",
                    data={
                        "calls": 3,
                        "prompt_tokens": 1000,
                        "completion_tokens": 100,
                        "cache_hit_tokens": 400,
                    },
                )
            )
            return "报告 [1]"

    from app.config import Settings

    settings = Settings(deepseek_api_key="x")
    record = asyncio.run(
        run_research(QUESTION, "single", settings, timeout=5, builder=lambda s, m: FakeAgent())
    )
    assert record.ok and record.report == "报告 [1]"
    assert record.llm_calls == 3 and record.cost_usd > 0
    assert (record.tools.search_calls, record.tools.search_failures) == (2, 1)
    assert (record.tools.fetch_calls, record.tools.fetch_failures) == (1, 1)
    assert record.sources[0].content == "完整正文"


def test_run_research_records_errors_and_timeouts():
    class SlowAgent:
        sources = SourceRegistry()

        async def run(self, query, emit):
            await asyncio.sleep(10)

    from app.config import Settings

    record = asyncio.run(
        run_research(QUESTION, "multi", Settings(), timeout=0.05, builder=lambda s, m: SlowAgent())
    )
    assert not record.ok and "TimeoutError" in record.error


def make_record(mode: str, report: str) -> RunRecord:
    return RunRecord(
        question_id="q1",
        question="问题",
        mode=mode,
        report=report,
        sources=[
            SourceRecord(id=1, url="https://a.com", title="A", content="出口 400 万辆"),
            SourceRecord(id=2, url="https://b.com", title="B", content="无关内容"),
        ],
    )


def citation_handler(messages: Messages) -> LLMResponse:
    supported = "出口 400 万辆" in messages[-1]["content"]
    return json_response({"verdict": "supported" if supported else "unsupported"})


def test_judge_record_scores_quality_and_citations():
    llm = RoleLLM(
        {
            "judge-quality": lambda m: json_response(
                {
                    "scores": {
                        "comprehensiveness": 8,
                        "depth": 6,
                        "instruction_following": 9,
                        "readability": 7,
                    },
                    "key_points": [{"point": "要点一", "verdict": "covered"}],  # 漏判一个
                    "comment": "ok",
                }
            ),
            "judge-citation": citation_handler,
        }
    )
    record = make_record("multi", "出口规模大 [1]。另一说法 [2]。编造的引用 [9]。")
    asyncio.run(judge_record(Judge(llm), QUESTION, record, claims_per_report=10, seed=0))

    assert record.quality.scores.overall == 7.5
    assert record.claims_total == 3 and record.invalid_citations == 1
    verdicts = {c.claim: c.verdict for c in record.citations}
    assert verdicts == {
        "出口规模大。": "supported",
        "另一说法。": "unsupported",
        "编造的引用。": "unsupported",
    }
    # 不存在的编号直接判为 unsupported，不调用裁判
    assert len(llm.calls["judge-citation"]) == 2

    summary = summarize([record], {"q1": 2}, [], {})
    row = summary["per_run"]["q1/multi"]
    assert row["key_point_coverage"] == 0.5  # 漏判的要点按未覆盖计
    assert abs(row["citation_accuracy"] - 1 / 3) < 1e-9


def test_judge_failures_keep_partial_results():
    def flaky_citation(messages: Messages) -> LLMResponse:
        if "另一说法" in messages[-1]["content"]:
            raise RuntimeError("429 rate limit")
        return citation_handler(messages)

    llm = RoleLLM(
        {
            "judge-quality": lambda m: json_response(
                {
                    "scores": {
                        "comprehensiveness": 8,
                        "depth": 8,
                        "instruction_following": 8,
                        "readability": 8,
                    }
                }
            ),
            "judge-citation": flaky_citation,
        }
    )
    record = make_record("multi", "出口规模大 [1]。另一说法 [2]。")
    asyncio.run(judge_record(Judge(llm), QUESTION, record, claims_per_report=10, seed=0))

    assert record.quality is not None
    assert [c.claim for c in record.citations] == ["出口规模大。"]
    assert "429" in record.judge_error

    def failing_pairwise(messages: Messages) -> LLMResponse:
        raise RuntimeError("429")

    judge = Judge(RoleLLM({"judge-pairwise": failing_pairwise}))
    assert asyncio.run(compare_modes(judge, make_record("single", "单"), record)) is None


def test_pairwise_swaps_positions_to_cancel_bias():
    single, multi = make_record("single", "单"), make_record("multi", "多")

    def run(handler) -> str:
        judge = Judge(RoleLLM({"judge-pairwise": handler}))
        return asyncio.run(compare_modes(judge, single, multi)).outcome

    # 总是偏向第一个位置的裁判：两次结论矛盾 -> 平局
    assert run(lambda m: json_response({"winner": "A"})) == "tie"

    # 稳定偏好多 Agent 报告的裁判：无论顺序都选它 -> 多 Agent 胜
    def prefers_multi(messages: Messages) -> LLMResponse:
        a = messages[-1]["content"].split("## 报告 A\n")[1].split("\n")[0]
        return json_response({"winner": "A" if a == "多" else "B"})

    assert run(prefers_multi) == "multi"


def test_markdown_summary_renders():
    records = [make_record("single", "单 [1]。"), make_record("multi", "多 [1]。")]
    records[0].error = "TimeoutError: "
    config = {
        "started_at": "now",
        "questions": 1,
        "model": "deepseek-flash",
        "reasoning_effort": "low",
        "search_provider": "ddgs",
        "judge_model": "deepseek-v4-pro",
        "claims_per_report": 10,
    }
    summary = summarize(records, {"q1": 2}, [], config)
    assert summary["by_mode"]["single"]["failed"] == 1
    md = to_markdown(summary, {"q1": "问题"})
    assert "| 问题 | 失败 |" in md
