import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
from ddgs import DDGS
from ddgs.exceptions import DDGSException

from app.agent.sources import SourceRegistry
from app.config import Settings
from app.tools.base import Tool

SNIPPET_MAX_CHARS = 500


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int) -> list[SearchResult]: ...


class TavilySearch(SearchProvider):
    """https://docs.tavily.com/documentation/api-reference/endpoint/search"""

    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                self.URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"query": query, "max_results": max_results, "search_depth": "basic"},
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            SearchResult(title=r.get("title", ""), url=r["url"], snippet=r.get("content", ""))
            for r in data.get("results", [])
            if r.get("url")
        ]


class BochaSearch(SearchProvider):
    """博查 Web Search API：https://open.bochaai.com"""

    URL = "https://api.bochaai.com/v1/web-search"

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                self.URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "query": query,
                    "count": max_results,
                    "summary": True,
                    "freshness": "noLimit",
                },
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        pages = ((data.get("data") or {}).get("webPages") or {}).get("value") or []
        return [
            SearchResult(
                title=p.get("name", ""),
                url=p["url"],
                snippet=p.get("summary") or p.get("snippet", ""),
            )
            for p in pages
            if p.get("url")
        ]


class DDGSSearch(SearchProvider):
    """免 key 的元搜索（https://github.com/deedy5/ddgs），通过抓取搜索引擎结果页实现。

    无需注册即可使用，适合本地开发；但速度慢、稳定性一般，正式使用推荐 Tavily / 博查。
    """

    def __init__(self, backend: str, proxy: str | None, timeout: int = 10):
        self._backend = backend
        self._proxy = proxy
        self._timeout = timeout

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        def _search() -> list[dict[str, Any]]:
            try:
                ddgs = DDGS(proxy=self._proxy, timeout=self._timeout)
                return ddgs.text(query, max_results=max_results, backend=self._backend)
            except DDGSException as e:
                if "No results" in str(e):
                    return []
                raise

        # ddgs 是同步库，放到线程池中执行，避免阻塞事件循环
        rows = await asyncio.to_thread(_search)
        return [
            SearchResult(title=r.get("title", ""), url=r["href"], snippet=r.get("body", ""))
            for r in rows
            if r.get("href")
        ]


def create_search_provider(settings: Settings) -> SearchProvider:
    if settings.search_provider == "ddgs":
        proxy = (
            settings.ddgs_proxy or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        )
        return DDGSSearch(settings.ddgs_backend, proxy or None)
    if settings.search_provider == "tavily":
        if not settings.tavily_api_key:
            raise RuntimeError("未配置 TAVILY_API_KEY，请在 backend/.env 中填写")
        return TavilySearch(settings.tavily_api_key)
    if settings.search_provider == "bocha":
        if not settings.bocha_api_key:
            raise RuntimeError("未配置 BOCHA_API_KEY，请在 backend/.env 中填写")
        return BochaSearch(settings.bocha_api_key)
    raise ValueError(f"unknown search provider: {settings.search_provider}")


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "使用搜索引擎检索网页。每条结果带有来源编号 [n]，撰写报告时用这个编号引用来源。"
        "关键词要具体，复杂问题应拆成多次不同角度的搜索。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        },
        "required": ["query"],
    }

    def __init__(self, provider: SearchProvider, sources: SourceRegistry, max_results: int = 5):
        self._provider = provider
        self._sources = sources
        self._max_results = max_results

    async def run(self, query: str) -> str:
        results = await self._provider.search(query, self._max_results)
        if not results:
            return "没有找到相关结果，请换个关键词。"

        blocks = []
        for r in results:
            snippet = r.snippet[:SNIPPET_MAX_CHARS]
            src = self._sources.add(r.url, r.title, snippet)
            blocks.append(f"[{src.id}] {r.title}\nURL: {r.url}\n摘要: {snippet}")
        return "\n\n".join(blocks)
