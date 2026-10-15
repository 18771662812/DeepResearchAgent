"""多 Agent 模式：Planner -> 并行 Researchers -> Reflector（可多轮）-> Writer。

和单 Agent 相比的关键区别是上下文隔离：
每个 Researcher 在自己的对话里检索、阅读原文，最后只把压缩后的研究笔记交回；
Reflector 和 Writer 只看笔记，看不到原始网页内容，主流程的上下文因此不会随检索量膨胀。

每个研究任务都要新建一个实例（状态是任务级的）。
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.agent.events import AgentEvent, EmitFn
from app.agent.loop import ChatModel, run_tool_loop
from app.agent.prompts import (
    PLANNER_PROMPT,
    REFLECTOR_PROMPT,
    RESEARCHER_FINISH_PROMPT,
    RESEARCHER_PROMPT,
    WRITER_PROMPT,
)
from app.agent.sources import SourceRegistry
from app.llm import Usage
from app.llm.structured import StructuredOutputError, chat_json
from app.tools import ToolRegistry

logger = logging.getLogger(__name__)


# ---- LLM 结构化输出 ----


class SubQuestionSpec(BaseModel):
    question: str = Field(min_length=1)
    goal: str = ""


class PlanOutput(BaseModel):
    brief: str = ""
    sub_questions: list[SubQuestionSpec] = Field(min_length=1)


class ReflectionOutput(BaseModel):
    sufficient: bool
    gaps: list[str] = Field(default_factory=list)
    follow_up_questions: list[SubQuestionSpec] = Field(default_factory=list)


# ---- 运行时状态 ----


@dataclass
class SubQuestion:
    id: int
    question: str
    goal: str
    round: int


@dataclass
class Note:
    sub_question: SubQuestion
    content: str
    ok: bool


@dataclass
class MultiAgentConfig:
    max_sub_questions: int = 4
    researcher_max_steps: int = 5
    max_concurrency: int = 3
    max_rounds: int = 2  # 研究轮数上限（含首轮），每轮之间进行一次反思
    max_follow_ups: int = 2  # 每次反思最多补充的子问题数


class MultiAgent:
    def __init__(
        self,
        llm: ChatModel,
        tools: ToolRegistry,
        sources: SourceRegistry,
        config: MultiAgentConfig | None = None,
    ):
        self.llm = llm
        self.tools = tools
        self.sources = sources
        self.config = config or MultiAgentConfig()

        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self._notes: list[Note] = []
        self._next_id = 1
        self._usage: dict[str, Usage] = defaultdict(Usage)
        self._raw_chars = 0
        self._today = date.today().isoformat()

    async def run(self, query: str, emit: EmitFn) -> str:
        await emit(AgentEvent(type="phase", data={"phase": "planning"}))
        plan = await self._plan(query, emit)
        pending = [self._new_sub_question(s, 1) for s in plan.sub_questions]
        await emit(
            AgentEvent(
                type="plan",
                data={"brief": plan.brief, "sub_questions": [asdict(q) for q in pending]},
            )
        )

        for round_no in range(1, self.config.max_rounds + 1):
            await emit(AgentEvent(type="phase", data={"phase": "researching", "round": round_no}))
            await asyncio.gather(*(self._research(query, q, emit) for q in pending))

            if round_no == self.config.max_rounds:
                break
            await emit(AgentEvent(type="phase", data={"phase": "reflecting", "round": round_no}))
            reflection = await self._reflect(query)
            follow_ups = [
                self._new_sub_question(s, round_no + 1)
                for s in reflection.follow_up_questions[: self.config.max_follow_ups]
            ]
            await emit(
                AgentEvent(
                    type="reflection",
                    data={
                        "round": round_no,
                        "sufficient": reflection.sufficient,
                        "gaps": reflection.gaps,
                        "follow_up_questions": [asdict(q) for q in follow_ups],
                    },
                )
            )
            if reflection.sufficient or not follow_ups:
                break
            pending = follow_ups

        if not any(n.ok for n in self._notes):
            raise RuntimeError("所有子问题的研究都失败了，无法生成报告")

        await emit(AgentEvent(type="phase", data={"phase": "writing"}))
        report = await self._write(query, plan.brief)

        cited = self.sources.cited_in(report)
        await emit(
            AgentEvent(
                type="report",
                data={"markdown": report, "sources": [s.public() for s in cited]},
            )
        )
        await emit(AgentEvent(type="usage", data=self._usage_summary()))
        return report

    # ---- 各角色 ----

    async def _plan(self, query: str, emit: EmitFn) -> PlanOutput:
        messages = [
            {
                "role": "system",
                "content": PLANNER_PROMPT.format(
                    today=self._today, max_sub_questions=self.config.max_sub_questions
                ),
            },
            {"role": "user", "content": query},
        ]
        try:
            plan = await chat_json(
                self.llm, messages, PlanOutput, name="planner", usage=self._usage["planner"]
            )
        except StructuredOutputError:
            # 规划失败时退化为把原问题当作唯一的子问题，保证流程能继续
            await emit(AgentEvent(type="status", data={"message": "规划失败，直接研究原问题"}))
            return PlanOutput(sub_questions=[SubQuestionSpec(question=query)])
        plan.sub_questions = plan.sub_questions[: self.config.max_sub_questions]
        return plan

    async def _research(self, query: str, q: SubQuestion, emit: EmitFn) -> None:
        label = f"R{q.id}"

        async def scoped_emit(event: AgentEvent) -> None:
            await emit(event.model_copy(update={"agent": label}))

        async with self._semaphore:
            await scoped_emit(
                AgentEvent(type="researcher_start", data={"id": q.id, "question": q.question})
            )
            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": RESEARCHER_PROMPT.format(today=self._today, query=query),
                },
                {"role": "user", "content": f"子问题：{q.question}\n需要查明：{q.goal or '无'}"},
            ]
            try:
                result = await run_tool_loop(
                    self.llm,
                    self.tools,
                    messages,
                    max_steps=self.config.researcher_max_steps,
                    emit=scoped_emit,
                    finish_prompt=RESEARCHER_FINISH_PROMPT,
                    name="researcher",
                )
            except Exception as e:
                # 单个子问题失败不影响整体，Writer 会基于其余笔记成文
                logger.warning("researcher %s failed: %r", label, e)
                self._notes.append(Note(q, f"（该子问题研究失败：{e}）", ok=False))
                await scoped_emit(
                    AgentEvent(
                        type="researcher_done", data={"id": q.id, "ok": False, "error": str(e)}
                    )
                )
                return

        self._usage["researcher"].add(result.usage)
        self._raw_chars += result.raw_chars
        self._notes.append(Note(q, result.content, ok=True))
        await scoped_emit(
            AgentEvent(
                type="researcher_done",
                data={
                    "id": q.id,
                    "ok": True,
                    "note": result.content,
                    "steps": result.steps,
                    "raw_chars": result.raw_chars,
                    "note_chars": len(result.content),
                },
            )
        )

    async def _reflect(self, query: str) -> ReflectionOutput:
        messages = [
            {
                "role": "system",
                "content": REFLECTOR_PROMPT.format(
                    today=self._today, max_follow_ups=self.config.max_follow_ups
                ),
            },
            {
                "role": "user",
                "content": f"研究问题：{query}\n\n研究笔记：\n\n{self._format_notes()}",
            },
        ]
        try:
            return await chat_json(
                self.llm,
                messages,
                ReflectionOutput,
                name="reflector",
                usage=self._usage["reflector"],
            )
        except StructuredOutputError:
            return ReflectionOutput(sufficient=True)

    async def _write(self, query: str, brief: str) -> str:
        user = f"研究问题：{query}\n"
        if brief:
            user += f"研究目标：{brief}\n"
        user += f"\n研究笔记：\n\n{self._format_notes()}"
        messages = [
            {"role": "system", "content": WRITER_PROMPT.format(today=self._today)},
            {"role": "user", "content": user},
        ]
        resp = await self.llm.chat(messages, name="writer")
        self._usage["writer"].add(resp.usage)
        return resp.content

    # ---- 工具方法 ----

    def _new_sub_question(self, spec: SubQuestionSpec, round_no: int) -> SubQuestion:
        q = SubQuestion(id=self._next_id, question=spec.question, goal=spec.goal, round=round_no)
        self._next_id += 1
        return q

    def _format_notes(self) -> str:
        notes = sorted(self._notes, key=lambda n: n.sub_question.id)
        return "\n\n".join(
            f"### 子问题 {n.sub_question.id}：{n.sub_question.question}\n{n.content}" for n in notes
        )

    def _usage_summary(self) -> dict[str, Any]:
        total = Usage()
        for u in self._usage.values():
            total.add(u)
        notes_chars = sum(len(n.content) for n in self._notes if n.ok)
        return {
            **asdict(total),
            "by_role": {role: asdict(u) for role, u in self._usage.items()},
            "context": {"raw_chars": self._raw_chars, "notes_chars": notes_chars},
        }
