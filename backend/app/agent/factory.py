from app.agent.multi_agent import MultiAgent, MultiAgentConfig
from app.agent.single_agent import SingleAgent
from app.agent.sources import SourceRegistry
from app.config import AgentMode, Settings
from app.llm.client import get_llm_client
from app.tools import FetchUrlTool, ToolRegistry, WebSearchTool, create_search_provider


def build_agent(settings: Settings, mode: AgentMode) -> SingleAgent | MultiAgent:
    """每个研究任务创建一个新的 Agent：来源编号等状态是任务级的，不能共享。"""
    sources = SourceRegistry()
    tools = ToolRegistry(
        [
            WebSearchTool(create_search_provider(settings), sources, settings.search_max_results),
            FetchUrlTool(sources, settings.fetch_max_chars),
        ],
        timeout=settings.tool_timeout,
    )
    llm = get_llm_client()

    if mode == "single":
        return SingleAgent(llm, tools, sources, max_steps=settings.agent_max_steps)
    return MultiAgent(
        llm,
        tools,
        sources,
        MultiAgentConfig(
            max_sub_questions=settings.planner_max_sub_questions,
            researcher_max_steps=settings.researcher_max_steps,
            max_concurrency=settings.researcher_concurrency,
            max_rounds=settings.research_max_rounds,
            max_follow_ups=settings.reflector_max_follow_ups,
        ),
    )
