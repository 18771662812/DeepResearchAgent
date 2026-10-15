import asyncio
import html
import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
import trafilatura

from app.agent.sources import SourceRegistry
from app.tools.base import Tool

# 如实标明爬虫身份：维基百科等站点会拦截伪装成浏览器的请求，反而放行可识别的 bot UA
USER_AGENT = "DeepResearchAgent/0.1 (+https://github.com/18771662812/DeepResearchAgent)"
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# Clash / Mihomo 等代理的 fake-ip 模式会把所有域名解析到 198.18.0.0/15（RFC 2544 测试网段），
# 真实连接由代理完成。这个网段不会部署真实的内网服务，因此放行
_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")


async def _ensure_public_url(url: str) -> None:
    """基础的 SSRF 防护：URL 由模型生成，不能让它访问内网或本机服务。

    TODO: 重定向后的地址目前没有再次校验。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("只支持 http/https 链接")

    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip in _FAKE_IP_NET:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("禁止访问内网地址")


def _extract(page_html: str) -> tuple[str, str]:
    """返回 (标题, 正文)。trafilatura 是同步的 CPU 密集操作，调用方需放到线程池里执行。"""
    m = _TITLE_RE.search(page_html)
    title = html.unescape(m.group(1)).strip() if m else ""
    text = trafilatura.extract(page_html, include_comments=False, include_tables=True) or ""
    return title, text


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = "抓取网页并提取正文。当搜索摘要不足以支撑结论时，用它阅读原文。"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要阅读的网页链接"},
        },
        "required": ["url"],
    }

    def __init__(self, sources: SourceRegistry, max_chars: int = 8000):
        self._sources = sources
        self._max_chars = max_chars

    async def run(self, url: str) -> str:
        await _ensure_public_url(url)

        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "pdf" in content_type:
            # TODO: 接入 PDF 解析
            return "暂不支持解析 PDF，请换一个来源。"
        if "html" in content_type or not content_type:
            title, text = await asyncio.to_thread(_extract, resp.text)
        else:
            title, text = "", resp.text

        if not text.strip():
            return "未能从该页面提取到正文，可能需要 JS 渲染或有反爬，请换一个来源。"

        src = self._sources.add(url, title or url)
        truncated = len(text) > self._max_chars
        body = text[: self._max_chars]
        suffix = f"\n\n（正文过长，已截断，原文共 {len(text)} 字）" if truncated else ""
        return f"[{src.id}] {src.title}\nURL: {url}\n\n{body}{suffix}"
