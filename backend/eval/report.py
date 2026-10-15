"""汇总评测结果，生成 summary.json / summary.md。"""

from collections import Counter
from statistics import mean
from typing import Any

from eval.records import PairwiseResult, RunRecord

_KEY_POINT_SCORE = {"covered": 1.0, "partial": 0.5, "missing": 0.0}
_CITATION_SCORE = {"supported": 1.0, "partial": 0.5, "unsupported": 0.0}


def run_metrics(r: RunRecord, n_key_points: int) -> dict[str, Any]:
    m: dict[str, Any] = {
        "ok": r.ok,
        "latency_s": r.latency_s,
        "llm_calls": r.llm_calls,
        "prompt_tokens": r.prompt_tokens,
        "completion_tokens": r.completion_tokens,
        "cost_usd": r.cost_usd,
        "report_chars": len(r.report),
        "sources_cited": r.cited_source_count(),
        "search_failure_rate": (
            r.tools.search_failures / r.tools.search_calls if r.tools.search_calls else None
        ),
    }
    if r.quality:
        s = r.quality.scores
        m |= {
            "overall": s.overall,
            "comprehensiveness": s.comprehensiveness,
            "depth": s.depth,
            "instruction_following": s.instruction_following,
            "readability": s.readability,
            # 裁判漏判的要点按未覆盖计
            "key_point_coverage": sum(_KEY_POINT_SCORE[k.verdict] for k in r.quality.key_points)
            / n_key_points,
        }
    if r.citations:
        m["citation_accuracy"] = mean(_CITATION_SCORE[c.verdict] for c in r.citations)
        m["citations_checked"] = len(r.citations)
    m["claims_total"] = r.claims_total
    m["invalid_citations"] = r.invalid_citations
    return m


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    return mean(values) if values else None


METRICS: list[tuple[str, str, str]] = [
    # (key, 显示名, 格式)
    ("overall", "质量总分（1-10）", "{:.2f}"),
    ("comprehensiveness", "　全面性", "{:.2f}"),
    ("depth", "　深度", "{:.2f}"),
    ("instruction_following", "　切题性", "{:.2f}"),
    ("readability", "　可读性", "{:.2f}"),
    ("key_point_coverage", "要点覆盖率", "{:.0%}"),
    ("citation_accuracy", "引用准确率", "{:.0%}"),
    ("invalid_citations", "编造引用（次/篇）", "{:.2f}"),
    ("sources_cited", "引用来源数", "{:.1f}"),
    ("report_chars", "报告字数", "{:.0f}"),
    ("latency_s", "耗时（秒）", "{:.0f}"),
    ("llm_calls", "LLM 调用次数", "{:.1f}"),
    ("prompt_tokens", "输入 tokens", "{:,.0f}"),
    ("completion_tokens", "输出 tokens", "{:,.0f}"),
    ("cost_usd", "成本（美元/篇）", "${:.4f}"),
    ("search_failure_rate", "搜索失败率", "{:.0%}"),
]


def summarize(
    records: list[RunRecord],
    key_points: dict[str, int],
    pairwise: list[PairwiseResult],
    config: dict[str, Any],
) -> dict[str, Any]:
    modes = sorted({r.mode for r in records}, key=lambda m: m != "single")
    per_run = {
        f"{r.question_id}/{r.mode}": run_metrics(r, key_points[r.question_id]) for r in records
    }
    by_mode: dict[str, dict[str, Any]] = {}
    for mode in modes:
        rows = [per_run[f"{r.question_id}/{r.mode}"] for r in records if r.mode == mode]
        by_mode[mode] = {
            "runs": len(rows),
            "failed": sum(not row["ok"] for row in rows),
            "judge_incomplete": sum(r.judge_error is not None for r in records if r.mode == mode),
            **{key: _avg(rows, key) for key, _, _ in METRICS},
        }
    outcomes = Counter(p.outcome for p in pairwise)
    return {
        "config": config,
        "by_mode": by_mode,
        "pairwise": {
            "multi_wins": outcomes["multi"],
            "ties": outcomes["tie"],
            "single_wins": outcomes["single"],
            "details": [p.model_dump() for p in pairwise],
        },
        "per_run": per_run,
    }


def _fmt(value: Any, fmt: str) -> str:
    return "—" if value is None else fmt.format(value)


MODE_NAMES = {"single": "单 Agent", "multi": "多 Agent"}


def to_markdown(summary: dict[str, Any], questions: dict[str, str]) -> str:
    cfg = summary["config"]
    modes = list(summary["by_mode"])
    lines = [
        "# 评测报告",
        "",
        f"- 时间：{cfg['started_at']}",
        f"- 题目数：{cfg['questions']}；模式：{', '.join(MODE_NAMES[m] for m in modes)}",
        f"- 研究模型：`{cfg['model']}`（reasoning_effort={cfg['reasoning_effort']}），"
        f"搜索：`{cfg['search_provider']}`",
        f"- 裁判模型：`{cfg['judge_model']}`；每篇抽查 {cfg['claims_per_report']} 条引用",
        f"- 裁判成本：${cfg.get('judge_cost_usd', 0):.4f}",
        "",
        "## 总览",
        "",
        "| 指标 | " + " | ".join(MODE_NAMES[m] for m in modes) + " |",
        "|---|" + "---|" * len(modes),
    ]
    for key, label, fmt in METRICS:
        cells = [_fmt(summary["by_mode"][m][key], fmt) for m in modes]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    failed = [str(summary["by_mode"][m]["failed"]) for m in modes]
    lines.append("| 研究失败次数 | " + " | ".join(failed) + " |")
    incomplete = [str(summary["by_mode"][m]["judge_incomplete"]) for m in modes]
    lines.append("| 评判不完整次数 | " + " | ".join(incomplete) + " |")

    pw = summary["pairwise"]
    if pw["details"]:
        n = len(pw["details"])
        lines += [
            "",
            "## 两两对比（多 Agent vs 单 Agent）",
            "",
            "同一问题的两份报告交给裁判比较，交换 A/B 顺序各判一次，两次结论不一致记为平局。",
            "",
            f"- 多 Agent 胜：{pw['multi_wins']} / {n}",
            f"- 平局：{pw['ties']} / {n}",
            f"- 单 Agent 胜：{pw['single_wins']} / {n}",
        ]

    lines += [
        "",
        "## 逐题结果",
        "",
        "格式：质量总分 / 要点覆盖率 / 引用准确率",
        "",
        "| 题目 | " + " | ".join(MODE_NAMES[m] for m in modes) + " | 对比胜者 |",
        "|---|" + "---|" * (len(modes) + 1),
    ]
    winners = {p["question_id"]: p["outcome"] for p in pw["details"]}
    for qid, text in questions.items():
        cells = []
        for m in modes:
            row = summary["per_run"].get(f"{qid}/{m}")
            if row is None:
                cells.append("—")
            elif not row["ok"]:
                cells.append("失败")
            else:
                cells.append(
                    f"{_fmt(row.get('overall'), '{:.2f}')} / "
                    f"{_fmt(row.get('key_point_coverage'), '{:.0%}')} / "
                    f"{_fmt(row.get('citation_accuracy'), '{:.0%}')}"
                )
        winner = {"multi": "多 Agent", "single": "单 Agent", "tie": "平局"}.get(
            winners.get(qid, ""), "—"
        )
        lines.append(f"| {text} | " + " | ".join(cells) + f" | {winner} |")
    return "\n".join(lines) + "\n"
