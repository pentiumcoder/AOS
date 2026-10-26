import uuid

import pytest

from aos.config import get_settings


def pytest_addoption(parser):
    parser.addoption(
        "--services",
        action="store_true",
        help="run e2e tests against the API at API_URL instead of in-process",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: drives the system through its HTTP API")


def reset_state() -> None:
    from aos.agents.prompting import load_prompt
    from aos.db import cache, session
    from aos.graph.builder import reset_graph
    from aos.graph.checkpointer import reset_checkpointer
    from aos.hitl.policy import get_policy
    from aos.llm.mock_provider import MockProvider
    from aos.llm.router import reset_router
    from aos.memory.embeddings import get_embedder
    from aos.observability.costs import pricing
    from aos.observability.tracing import reset_tracing
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
    get_embedder.cache_clear()
    get_policy.cache_clear()
    reset_tracing()
    pricing.cache_clear()


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    monkeypatch.setenv("STORAGE_MODE", "memory")
    monkeypatch.setenv("TASK_EXECUTION", "inline")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'aos.sqlite').as_posix()}")
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    # The in-memory Chroma client is shared by the whole process, so each test gets its
    # own collection instead of a new client.
    collection = f"test_{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("CHROMA_COLLECTION", collection)
    reset_state()

    from aos.db import get_redis, init_db

    init_db()
    get_redis().flushall()
    yield
    _drop_collection(collection)
    reset_state()


def _drop_collection(name: str) -> None:
    from aos.memory.longterm import chroma_client

    client = chroma_client()
    if name in {c.name for c in client.list_collections()}:
        client.delete_collection(name)


@pytest.fixture
def db():
    from aos.db import session_scope

    with session_scope() as session:
        yield session


def approve(escalation):
    from aos.schemas.escalation import HumanDecision

    return HumanDecision(action="approve", reviewer="tester")


@pytest.fixture
def finish():
    """Run a task to the end, answering each escalation with decide (approve by default)."""
    from aos.graph.runner import create_task, run_to_completion

    def run(request, decide=approve, **task_fields):
        task_id, run_id = create_task(request, **task_fields)
        return run_to_completion(run_id, decide), task_id, run_id

    return run
