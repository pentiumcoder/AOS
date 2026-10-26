from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aos import __version__
from aos.api.routes import escalations, memory, metrics, replay, tasks, traces
from aos.config import get_settings
from aos.db import get_redis, init_db
from aos.db.session import ping
from aos.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging(get_settings().log_level)
    init_db()
    yield


app = FastAPI(title="Agent Orchestration System", version=__version__, lifespan=lifespan)
app.include_router(tasks.router)
app.include_router(memory.router)
app.include_router(escalations.router)
app.include_router(traces.router)
app.include_router(metrics.router)
app.include_router(replay.router)


@app.get("/health", tags=["system"])
def health() -> dict[str, object]:
    settings = get_settings()
    checks: dict[str, bool] = {}
    try:
        checks["database"] = ping()
    except Exception:
        checks["database"] = False
    try:
        checks["redis"] = bool(get_redis().ping())
    except Exception:
        checks["redis"] = False
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        **checks,
        "llm_mode": settings.llm_mode,
        "storage_mode": settings.storage_mode,
        "task_execution": settings.task_execution,
    }
