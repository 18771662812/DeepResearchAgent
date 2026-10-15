from app.agent.research_agent import ResearchAgent
from app.agent.sources import SourceRegistry
from app.config import Settings
from app.llm.client import get_llm_client
from app.tools import FetchUrlTool, ToolRegistry, WebSearchTool, create_search_provider


def build_research_agent(settings: Settings) -> ResearchAgent:
    """每个研究任务创建一个新的 Agent：来源编号等状态是任务级的，不能共享。"""
    sources = SourceRegistry()
    tools = ToolRegistry(
        [
            WebSearchTool(create_search_provider(settings), sources, settings.search_max_results),
            FetchUrlTool(sources, settings.fetch_max_chars),
        ],
        timeout=settings.tool_timeout,
    )
    return ResearchAgent(get_llm_client(), tools, sources, max_steps=settings.agent_max_steps)
