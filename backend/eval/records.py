"""评测过程中产生的数据结构。全部是 Pydantic 模型，便于存盘和重新加载（--rejudge）。"""

from statistics import mean
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.sources import parse_citation_ids
from app.config import AgentMode


class SourceRecord(BaseModel):
    id: int
    url: str
    title: str
    content: str


class ToolStats(BaseModel):
    search_calls: int = 0
    search_failures: int = 0  # 无结果或报错
    fetch_calls: int = 0
    fetch_failures: int = 0


class QualityScores(BaseModel):
    comprehensiveness: int = Field(ge=1, le=10)
    depth: int = Field(ge=1, le=10)
    instruction_following: int = Field(ge=1, le=10)
    readability: int = Field(ge=1, le=10)

    @property
    def overall(self) -> float:
        return mean(
            [self.comprehensiveness, self.depth, self.instruction_following, self.readability]
        )


class KeyPointVerdict(BaseModel):
    point: str
    verdict: Literal["covered", "partial", "missing"]


class QualityJudgement(BaseModel):
    scores: QualityScores
    key_points: list[KeyPointVerdict] = Field(default_factory=list)
    comment: str = ""


class CitationVerdict(BaseModel):
    verdict: Literal["supported", "partial", "unsupported"]
    reason: str = ""


class CitationCheck(BaseModel):
    claim: str
    source_ids: list[int]
    verdict: Literal["supported", "partial", "unsupported"]
    reason: str = ""


class PairwiseVerdict(BaseModel):
    winner: Literal["A", "B", "tie"]
    reason: str = ""


class RunRecord(BaseModel):
    question_id: str
    question: str
    mode: AgentMode
    report: str = ""
    error: str | None = None
    latency_s: float = 0.0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cost_usd: float = 0.0
    tools: ToolStats = Field(default_factory=ToolStats)
    sources: list[SourceRecord] = Field(default_factory=list)

    # ---- 评测结果，由 judge 阶段填充 ----
    quality: QualityJudgement | None = None
    claims_total: int = 0  # 报告中带引用的陈述数
    invalid_citations: int = 0  # 引用了不存在的来源编号的次数
    citations: list[CitationCheck] = Field(default_factory=list)
    judge_error: str | None = None  # 评判阶段的错误（部分结果仍会保留）

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.report.strip())

    def cited_source_count(self) -> int:
        known = {s.id for s in self.sources}
        return len(set(parse_citation_ids(self.report)) & known)


class PairwiseResult(BaseModel):
    question_id: str
    # 以 multi 为视角：multi 胜 / 平 / 负；两次换位判断不一致时记为平局
    outcome: Literal["multi", "single", "tie"]
    verdicts: list[PairwiseVerdict]
