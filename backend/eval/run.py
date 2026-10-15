"""评测入口。

uv run python -m eval.run                                   # 全部题目 × 单 / 多 Agent
uv run python -m eval.run --questions tech-mcp,sci-glp1 --modes multi
uv run python -m eval.run --rejudge eval/results/<目录>      # 复用已有研究结果，只重新评判
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.llm.client import LLMClient
from eval.dataset import load_questions
from eval.judges import Judge
from eval.pricing import estimate_cost
from eval.records import PairwiseResult, RunRecord
from eval.report import summarize, to_markdown
from eval.runner import compare_modes, judge_record, run_research

RESULTS_DIR = Path(__file__).parent / "results"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DeepResearchAgent 离线评测")
    p.add_argument("--modes", default="single,multi", help="逗号分隔：single,multi")
    p.add_argument("--questions", default="", help="只评测这些题目 id，逗号分隔")
    p.add_argument("--limit", type=int, default=0, help="最多评测多少道题（0 表示全部）")
    p.add_argument("--concurrency", type=int, default=2, help="同时运行的研究任务数")
    p.add_argument("--timeout", type=float, default=900, help="单个研究任务的超时（秒）")
    p.add_argument("--judge-model", default="deepseek-v4-pro")
    p.add_argument("--judge-effort", default="low", choices=["none", "low", "high", "max"])
    # DeepSeek 会按账户余额动态限制并发，余额较低时上限可能只有个位数
    p.add_argument("--judge-concurrency", type=int, default=4)
    p.add_argument("--claims", type=int, default=10, help="每篇报告抽查的引用条数")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--rejudge", default="", help="已有结果目录：跳过研究，只重新评判")
    return p.parse_args()


def _save(record: RunRecord, runs_dir: Path) -> None:
    path = runs_dir / f"{record.question_id}__{record.mode}.json"
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    questions = load_questions()
    if args.questions:
        wanted = set(args.questions.split(","))
        questions = [q for q in questions if q.id in wanted]
    if args.limit:
        questions = questions[: args.limit]
    by_id = {q.id: q for q in questions}
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    out_dir = (
        Path(args.rejudge)
        if args.rejudge
        else RESULTS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    runs_dir = out_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().isoformat(timespec="seconds")

    # ---- 1. 运行研究（或加载已有结果）----
    if args.rejudge:
        records = [
            RunRecord.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(runs_dir.glob("*.json"))
        ]
        records = [r for r in records if r.question_id in by_id and r.mode in modes]
        print(f"加载已有研究结果 {len(records)} 条：{runs_dir}")
    else:
        jobs = [(q, m) for q in questions for m in modes]
        semaphore = asyncio.Semaphore(args.concurrency)
        done = 0

        async def run_one(q, mode) -> RunRecord:
            nonlocal done
            async with semaphore:
                record = await run_research(q, mode, settings, timeout=args.timeout)
            _save(record, runs_dir)
            done += 1
            status = "OK" if record.ok else f"失败 {record.error}"
            print(
                f"[{done}/{len(jobs)}] {q.id} {mode}: {status} · {record.latency_s:.0f}s · "
                f"{record.llm_calls} calls · ${record.cost_usd:.4f}"
            )
            return record

        print(f"开始研究：{len(questions)} 题 × {len(modes)} 种模式，并发 {args.concurrency}")
        records = list(await asyncio.gather(*(run_one(q, m) for q, m in jobs)))

    # ---- 2. 评判 ----
    judge_llm = LLMClient(settings, model=args.judge_model, reasoning_effort=args.judge_effort)
    judge = Judge(judge_llm, max_concurrency=args.judge_concurrency)
    print(f"开始评判（裁判模型 {args.judge_model}）……")
    await asyncio.gather(
        *(
            judge_record(
                judge, by_id[r.question_id], r, claims_per_report=args.claims, seed=args.seed
            )
            for r in records
        )
    )
    for r in records:
        _save(r, runs_dir)

    pairwise: list[PairwiseResult] = []
    if {"single", "multi"} <= set(modes):
        index = {(r.question_id, r.mode): r for r in records}
        pairs = [
            (index[(q.id, "single")], index[(q.id, "multi")])
            for q in questions
            if (q.id, "single") in index and (q.id, "multi") in index
        ]
        pairs = [(s, m) for s, m in pairs if s.ok and m.ok]
        results = await asyncio.gather(*(compare_modes(judge, s, m) for s, m in pairs))
        pairwise = [p for p in results if p is not None]
        if len(pairwise) < len(pairs):
            print(f"注意：{len(pairs) - len(pairwise)} 道题的两两对比失败，已跳过")

    judge_failures = sum(r.judge_error is not None for r in records)
    if judge_failures:
        print(f"注意：{judge_failures} 条记录的评判不完整，详见 runs/*.json 中的 judge_error")

    # ---- 3. 汇总 ----
    config = {
        "started_at": started_at,
        "questions": len(questions),
        "model": settings.llm_model,
        "reasoning_effort": settings.llm_reasoning_effort,
        "search_provider": settings.search_provider,
        "judge_model": args.judge_model,
        "judge_effort": args.judge_effort,
        "claims_per_report": args.claims,
        "seed": args.seed,
        "judge_cost_usd": estimate_cost(
            args.judge_model,
            judge.usage.prompt_tokens,
            judge.usage.cache_hit_tokens,
            judge.usage.completion_tokens,
        ),
    }
    summary = summarize(records, {q.id: len(q.key_points) for q in questions}, pairwise, config)
    markdown = to_markdown(summary, {q.id: q.question for q in questions})

    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "summary.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"结果已保存到 {out_dir}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")
    asyncio.run(main(parse_args()))
