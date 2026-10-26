from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    llm_mode: Literal["mock", "live"] = "mock"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_num_ctx: int = 8192
    ollama_temperature: float = 0.2
    storage_mode: Literal["services", "memory"] = "services"
    task_execution: Literal["celery", "inline"] = "celery"

    database_url: str = "postgresql+psycopg://aos:aos@localhost:5433/aos"
    redis_url: str = "redis://localhost:6380/0"
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_reviewer_model: str = ""
    tavily_api_key: str = ""

    workspace_dir: Path = ROOT_DIR / "workspace"
    config_dir: Path = ROOT_DIR / "config"
    fixtures_dir: Path = ROOT_DIR / "tests" / "fixtures"
    mcp_enabled: bool = True
    log_level: str = "INFO"

    embedding_provider: Literal["hash", "ollama", "openai"] = "hash"
    embedding_model: str = ""
    chroma_collection: str = "aos_memories"
    memory_top_k: int = 4
    memory_min_similarity: float | None = None
    memory_dedupe_similarity: float = 0.92
    memory_consolidate_similarity: float | None = None
    memory_half_life_days: float = 30.0
    memory_expire_below: float = 0.05
    memory_maintenance_minutes: int = 60

    notify_webhook_url: str = ""
    plan_confidence_threshold: float = 0.6
    plan_notify_threshold: float = 0.75
    review_approve_score: float = 0.7
    review_escalate_score: float = 0.6
    max_revisions: int = 2
    max_attempts: int = 2
    specialist_max_steps: int = 6
    graph_recursion_limit: int = 100

    otel_service_name: str = "aos"
    otel_exporter_otlp_endpoint: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
