from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "questions.jsonl"


class EvalQuestion(BaseModel):
    id: str
    category: str
    question: str
    # 报告应当覆盖的方面（而非具体数字），避免答案随时间过期
    key_points: list[str] = Field(min_length=1)


def load_questions(path: Path = DEFAULT_DATASET) -> list[EvalQuestion]:
    with path.open(encoding="utf-8") as f:
        return [EvalQuestion.model_validate_json(line) for line in f if line.strip()]
