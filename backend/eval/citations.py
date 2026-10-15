"""从报告中提取带引用的陈述，供引用核查使用。"""

import random
import re
from dataclasses import dataclass

from app.agent.sources import parse_citation_ids

# 中英文句末标点或换行处断句
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])|\n+")
_CITATION_MARK_RE = re.compile(r"\[\d+(?:\s*[,，]\s*\d+)*\]")
# 行首的标题 / 引用 / 列表标记，以及行内的强调、代码、表格符号
_LEADING_MARK_RE = re.compile(r"^\s*(?:#+|>|[-*+]|\d+[.、)])\s+")
_INLINE_MARK_RE = re.compile(r"[*_`|]")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([。！？!?；;，,：:])")
_NON_WORD_RE = re.compile(r"[\W_]")
MIN_CLAIM_CHARS = 4  # 不计标点和空白


@dataclass
class Claim:
    text: str  # 去掉引用标记后的陈述
    source_ids: list[int]


def extract_claims(report: str) -> list[Claim]:
    """按句切分报告，返回所有带引用标记的句子（去重）。"""
    claims: list[Claim] = []
    seen: set[str] = set()
    for sentence in _SENTENCE_SPLIT_RE.split(report):
        ids = list(dict.fromkeys(parse_citation_ids(sentence)))
        if not ids:
            continue
        text = _CITATION_MARK_RE.sub("", sentence)
        text = _INLINE_MARK_RE.sub("", _LEADING_MARK_RE.sub("", text))
        text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text).strip()
        if len(_NON_WORD_RE.sub("", text)) < MIN_CLAIM_CHARS or text in seen:
            continue
        seen.add(text)
        claims.append(Claim(text=text, source_ids=ids))
    return claims


def sample_claims(claims: list[Claim], k: int, seed: int) -> list[Claim]:
    if len(claims) <= k:
        return list(claims)
    return random.Random(seed).sample(claims, k)


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text.lower())
    return {t[i : i + 2] for i in range(len(t) - 1)}


def select_passages(content: str, claim: str, budget: int, window: int = 500) -> str:
    """从长文中挑出与陈述最相关的片段，总长度不超过 budget。

    直接截取开头会漏掉位于后文的证据，导致引用被误判为无依据；全文交给裁判又太贵。
    做法：按半窗口步长切出重叠窗口，以字符二元组重合度排序，取前若干个，合并相邻区间后按原文顺序拼接。
    """
    if len(content) <= budget:
        return content
    grams = _bigrams(claim)
    starts = sorted(set(range(0, len(content) - window + 1, window // 2)) | {len(content) - window})
    ranked = sorted(
        starts, key=lambda s: len(_bigrams(content[s : s + window]) & grams), reverse=True
    )

    spans: list[list[int]] = []
    for s in sorted(ranked[: max(budget // window, 1)]):
        if spans and s <= spans[-1][1]:
            spans[-1][1] = s + window
        else:
            spans.append([s, s + window])
    return "\n……\n".join(content[s:e] for s, e in spans)
