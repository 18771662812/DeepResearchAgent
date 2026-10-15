"""LLM 裁判：报告质量打分、引用核查、两两对比。"""

import asyncio
from typing import Literal

from app.llm import Usage
from app.llm.structured import JSONChatModel, chat_json
from eval.citations import Claim, select_passages
from eval.dataset import EvalQuestion
from eval.prompts import CITATION_JUDGE_PROMPT, PAIRWISE_JUDGE_PROMPT, QUALITY_JUDGE_PROMPT
from eval.records import (
    CitationCheck,
    CitationVerdict,
    PairwiseVerdict,
    QualityJudgement,
    SourceRecord,
)

SOURCE_CONTENT_CHARS = 3000  # 每个来源交给裁判的最大字数（超出时挑选相关片段）
MAX_SOURCES_PER_CLAIM = 3


class Judge:
    def __init__(self, llm: JSONChatModel, max_concurrency: int = 8):
        self.llm = llm
        self.usage = Usage()
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _ask(self, system: str, user: str, schema, name: str):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        async with self._semaphore:
            return await chat_json(self.llm, messages, schema, name=name, usage=self.usage)

    async def quality(self, question: EvalQuestion, report: str) -> QualityJudgement:
        points = "\n".join(f"- {p}" for p in question.key_points)
        user = f"## 研究问题\n{question.question}\n\n## 参考要点\n{points}\n\n## 待评报告\n{report}"
        return await self._ask(QUALITY_JUDGE_PROMPT, user, QualityJudgement, "judge-quality")

    async def citation(self, claim: Claim, sources: dict[int, SourceRecord]) -> CitationCheck:
        cited = [sources[i] for i in claim.source_ids if i in sources][:MAX_SOURCES_PER_CLAIM]
        if not cited:
            return CitationCheck(
                claim=claim.text,
                source_ids=claim.source_ids,
                verdict="unsupported",
                reason="引用的来源编号不存在",
            )
        blocks = "\n\n".join(
            f"### 来源 [{s.id}] {s.title}\n{s.url}\n"
            + select_passages(s.content, claim.text, SOURCE_CONTENT_CHARS)
            for s in cited
        )
        user = f"## 陈述\n{claim.text}\n\n## 来源内容\n{blocks}"
        verdict = await self._ask(CITATION_JUDGE_PROMPT, user, CitationVerdict, "judge-citation")
        return CitationCheck(
            claim=claim.text,
            source_ids=claim.source_ids,
            verdict=verdict.verdict,
            reason=verdict.reason,
        )

    async def compare(
        self, question: str, report_x: str, report_y: str
    ) -> tuple[Literal["x", "y", "tie"], list[PairwiseVerdict]]:
        """两两对比，交换 A/B 顺序各判一次以消除位置偏差；两次结论不一致时记为平局。"""

        async def judge(a: str, b: str) -> PairwiseVerdict:
            user = f"## 研究问题\n{question}\n\n## 报告 A\n{a}\n\n## 报告 B\n{b}"
            return await self._ask(PAIRWISE_JUDGE_PROMPT, user, PairwiseVerdict, "judge-pairwise")

        first, second = await asyncio.gather(judge(report_x, report_y), judge(report_y, report_x))
        # 把第二次的结论映射回 x / y 视角
        r1 = {"A": "x", "B": "y", "tie": "tie"}[first.winner]
        r2 = {"A": "y", "B": "x", "tie": "tie"}[second.winner]
        return (r1 if r1 == r2 else "tie"), [first, second]  # type: ignore[return-value]
