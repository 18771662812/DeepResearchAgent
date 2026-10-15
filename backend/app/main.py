import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.factory import build_research_agent
from app.api import research
from app.config import get_settings
from app.services.task_manager import TaskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.task_manager = TaskManager(lambda: build_research_agent(settings))
    yield
    await app.state.task_manager.shutdown()


app = FastAPI(title="DeepResearchAgent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(research.router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.llm_model, "search": settings.search_provider}
