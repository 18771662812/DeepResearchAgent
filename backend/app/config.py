from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    llm_reasoning_effort: Literal["none", "low", "high", "max"] = "low"
    llm_timeout: float = 120.0

    # 搜索
    search_provider: Literal["ddgs", "tavily", "bocha"] = "ddgs"
    tavily_api_key: str = ""
    bocha_api_key: str = ""
    search_max_results: int = 5
    # ddgs：免 key 的元搜索，逗号分隔多个引擎依次尝试；代理留空则读取 HTTPS_PROXY 环境变量
    ddgs_backend: str = "yahoo,bing"
    ddgs_proxy: str = ""

    # Agent
    agent_max_steps: int = 10
    fetch_max_chars: int = 8000
    tool_timeout: float = 60.0

    # Server
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
