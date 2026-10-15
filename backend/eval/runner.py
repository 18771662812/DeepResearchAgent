import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from app.agent.events import AgentEvent
from app.agent.factory import build_agent
from app.agent.sources import parse_citation_ids
from app.config import AgentMode, Settings
from eval.citations import extract_claims, sample_claims
from eval.dataset import EvalQuestion
from eval.judges import Judge
from eval.pricing import estimate_cost
from eval.records import PairwiseResult, RunRecord, SourceRecord, ToolStats

logger = logging.getLogger(__name__)

_SEARCH_FAILURE_PREFIXES = ("没有找到", "错误")
_FETCH_FAILURE_PREFIXES = ("错误", "未能", "暂不支持")

AgentBuilder = Callable[[Settings, AgentMode], Any]


def _tool_stats(events: list[AgentEvent]) -> ToolStats:
    stats = ToolStats()
    for e in events:
        if e.type != "tool_result":
            continue
        preview: str = e.data["preview"]
        if e.data["name"] == "web_search":
            stats.search_calls += 1
            stats.search_failures += preview.startswith(_SEARCH_FAILURE_PREFIXES)
        elif e.data["name"] == "fetch_url":
            stats.fetch_calls += 1
            stats.fetch_failures += preview.startswith(_FETCH_FAILURE_PREFIXES)
    return stats


async def run_research(
    question: EvalQuestion,
    mode: AgentMode,
    settings: Settings,
    *,
    timeout: float,
    builder: AgentBuilder = build_agent,
) -> RunRecord:
    """在进程内直接运行 Agent（不经过 HTTP），以便拿到来源的完整内容。"""
    agent = builder(settings, mode)
    events: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        events.append(event)

    record = RunRecord(question_id=question.id, question=question.question, mode=mode)
    started = time.perf_counter()
    try:
        record.report = await asyncio.wait_for(agent.run(question.question, emit), timeout)
    except Exception as e:
        record.error = f"{type(e).__name__}: {e}"
    record.latency_s = round(time.perf_counter() - started, 1)

    usage = next((e.data for e in reversed(events) if e.type == "usage"), {})
    record.llm_calls = usage.get("calls", 0)
    record.prompt_tokens = usage.get("prompt_tokens", 0)
    record.completion_tokens = usage.get("completion_tokens", 0)
    record.cache_hit_tokens = usage.get("cache_hit_tokens", 0)
    record.cost_usd = estimate_cost(
        settings.llm_model, record.prompt_tokens, record.cache_hit_tokens, record.completion_tokens
    )
    record.tools = _tool_stats(events)
    record.sources = [
        SourceRecord(id=s.id, url=s.url, title=s.title, content=s.content)
        for s in agent.sources.all()
    ]
    return record


async def judge_record(
    judge: Judge, question: EvalQuestion, record: RunRecord, *, claims_per_report: int, seed: int
) -> None:
    """质量打分与引用核查，结果直接写回 record。

    各项评判相互独立：某一项失败（如限流）时保留其余结果，错误记入 judge_error。
    """
    if not record.ok:
        return

    known = {s.id: s for s in record.sources}
    claims = extract_claims(record.report)
    record.claims_total = len(claims)
    record.invalid_citations = sum(i not in known for i in parse_citation_ids(record.report))

    sampled = sample_claims(claims, claims_per_report, seed)
    quality, *checks = await asyncio.gather(
        judge.quality(question, record.report),
        *(judge.citation(c, known) for c in sampled),
        return_exceptions=True,
    )
    errors = [r for r in (quality, *checks) if isinstance(r, BaseException)]
    record.quality = None if isinstance(quality, BaseException) else quality
    record.citations = [c for c in checks if not isinstance(c, BaseException)]
    record.judge_error = (
        f"{len(errors)} 项评判失败，首个错误：{type(errors[0]).__name__}: {errors[0]}"
        if errors
        else None
    )


async def compare_modes(judge: Judge, single: RunRecord, multi: RunRecord) -> PairwiseResult | None:
    """两两对比；失败时返回 None，不影响其他题目。"""
    try:
        winner, verdicts = await judge.compare(single.question, multi.report, single.report)
    except Exception as e:
        logger.warning("pairwise judge failed for %s: %r", multi.question_id, e)
        return None
    outcome = {"x": "multi", "y": "single", "tie": "tie"}[winner]
    return PairwiseResult(question_id=multi.question_id, outcome=outcome, verdicts=verdicts)
