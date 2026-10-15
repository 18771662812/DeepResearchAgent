"""来源登记表：给每个检索到的 URL 分配一个全局编号。

模型在报告中用 [n] 引用，最后由程序（而不是模型）根据编号生成参考文献，
这样参考文献列表里的链接一定是真实检索到的，从机制上杜绝了编造 URL。

同时记录 Agent 实际读到的内容（搜索摘要或抓取的正文），评测时用来核对引用是否有据可依。
"""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urldefrag

_CITATION_RE = re.compile(r"\[(\d+(?:\s*[,，]\s*\d+)*)\]")


def parse_citation_ids(text: str) -> list[int]:
    """按出现顺序返回 text 中所有 [n] / [n, m] 引用的编号（含重复）。"""
    ids: list[int] = []
    for group in _CITATION_RE.findall(text):
        ids.extend(int(x) for x in re.split(r"\s*[,，]\s*", group))
    return ids


@dataclass
class Source:
    id: int
    url: str
    title: str
    snippet: str = ""
    # Agent 读到的完整内容，只在服务端使用（评测核对引用），不推送给前端
    content: str = ""

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "url": self.url, "title": self.title, "snippet": self.snippet}


def _normalize(url: str) -> str:
    return urldefrag(url)[0].rstrip("/")


class SourceRegistry:
    def __init__(self) -> None:
        self._sources: list[Source] = []
        self._by_url: dict[str, Source] = {}

    def add(self, url: str, title: str, snippet: str = "", content: str = "") -> Source:
        key = _normalize(url)
        existing = self._by_url.get(key)
        if existing:
            if snippet and not existing.snippet:
                existing.snippet = snippet
            # 先搜索到、后抓取正文的情况：保留信息量更大的那份
            if len(content) > len(existing.content):
                existing.content = content
            return existing
        src = Source(
            id=len(self._sources) + 1,
            url=url,
            title=title,
            snippet=snippet,
            content=content or snippet,
        )
        self._sources.append(src)
        self._by_url[key] = src
        return src

    def get(self, source_id: int) -> Source | None:
        if 1 <= source_id <= len(self._sources):
            return self._sources[source_id - 1]
        return None

    def all(self) -> list[Source]:
        return list(self._sources)

    def cited_in(self, text: str) -> list[Source]:
        """按编号顺序返回 text 中实际引用过的来源，忽略不存在的编号。"""
        return [s for i in sorted(set(parse_citation_ids(text))) if (s := self.get(i))]
