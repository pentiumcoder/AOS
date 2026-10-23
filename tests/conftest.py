import pytest

from aos.config import get_settings


def reset_state() -> None:
    from aos.agents.prompting import load_prompt
    from aos.db import cache, session
    from aos.graph.builder import reset_graph
    from aos.graph.checkpointer import reset_checkpointer
    from aos.llm.mock_provider import MockProvider
    from aos.llm.router import reset_router
    from aos.tools.builtin import demo_data
    from aos.tools.builtin.web_search import _fixtures as web_fixtures
    from aos.tools.registry import reset_registry

    get_settings.cache_clear()
    session.dispose()
    cache.reset_redis()
    reset_registry()
    reset_router()
    reset_graph()
    reset_checkpointer()
    MockProvider.reset()
    load_prompt.cache_clear()
    web_fixtures.cache_clear()
    demo_data._seeded.clear()


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.setenv("STORAGE_MODE", "memory")
    monkeypatch.setenv("TASK_EXECUTION", "inline")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'aos.sqlite').as_posix()}")
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    reset_state()

    from aos.db import get_redis, init_db

    init_db()
    get_redis().flushall()
    yield
    reset_state()


@pytest.fixture
def db():
    from aos.db import session_scope

    with session_scope() as session:
        yield session
