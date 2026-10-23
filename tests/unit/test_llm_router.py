import pytest
from pydantic import BaseModel

from aos import context
from aos.config import get_settings
from aos.db.models import LLMCall
from aos.llm import LLMUnavailable, Message, StructuredOutputError, get_llm
from aos.llm.base import LLMError, LLMProvider, LLMRequest, LLMResult, TransientLLMError
from aos.llm.mock_provider import MockProvider
from aos.llm.router import LLMClient, providers_for, reset_router
from aos.schemas import ExecutionPlan


class Answer(BaseModel):
    value: int


class Scripted(LLMProvider):
    name = "scripted"

    def __init__(self, *responses: object) -> None:
        super().__init__("scripted-1")
        self.responses = list(responses)
        self.calls = 0

    def complete(self, request: LLMRequest) -> LLMResult:
        self.calls += 1
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return LLMResult(parsed=response, provider=self.name, model=self.model)


def test_mock_returns_validated_plan():
    result = get_llm("supervisor").complete(
        [Message.user("x")],
        schema=ExecutionPlan,
        meta={"purpose": "plan", "request": "Explain LangGraph checkpoints"},
    )
    assert isinstance(result.parsed, ExecutionPlan)
    assert result.parsed.subtasks[0].description.endswith("Explain LangGraph checkpoints")
    assert result.usage.input_tokens > 0


def test_invalid_structured_output_gets_one_repair_round():
    provider = Scripted({"value": "not a number"}, {"value": 7})
    result = LLMClient("supervisor", [provider]).complete([Message.user("x")], schema=Answer)
    assert result.parsed == Answer(value=7)
    assert provider.calls == 2


def test_repair_failure_falls_back_to_next_provider():
    broken = Scripted({"wrong": True})
    result = LLMClient("supervisor", [broken, Scripted({"value": 3})]).complete(
        [Message.user("x")], schema=Answer
    )
    assert result.parsed.value == 3
    assert broken.calls == 2


def test_transient_errors_are_retried_before_fallback():
    flaky = Scripted(TransientLLMError("503"), TransientLLMError("503"), {"value": 1})
    client = LLMClient("supervisor", [flaky], retries=2, backoff_s=0)
    assert client.complete([Message.user("x")], schema=Answer).parsed.value == 1
    assert flaky.calls == 3


def test_permanent_error_skips_retries_and_falls_back():
    denied = Scripted(LLMError("401 invalid key"))
    client = LLMClient("supervisor", [denied, MockProvider()], backoff_s=0)
    result = client.complete([Message.user("x")], meta={"purpose": "default"})
    assert result.provider == "mock"
    assert denied.calls == 1


def test_all_providers_failing_raises_unavailable():
    client = LLMClient("reviewer", [Scripted(LLMError("down"))], backoff_s=0)
    with pytest.raises(LLMUnavailable, match="all providers failed for reviewer"):
        client.complete([Message.user("x")])


def test_structured_output_error_is_an_llm_error():
    assert issubclass(StructuredOutputError, LLMError)


def test_calls_are_persisted_with_run_context(db):
    with context.bind(run_id="run-1", subtask_id="s2"):
        get_llm("research").complete([Message.user("x")], meta={"purpose": "default"})
    row = db.query(LLMCall).one()
    assert (row.run_id, row.subtask_id, row.agent, row.provider) == (
        "run-1",
        "s2",
        "research",
        "mock",
    )
    assert len(row.prompt_hash) == 64


def test_live_mode_without_keys_uses_local_ollama(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    get_settings.cache_clear()
    reset_router()
    assert [repr(p) for p in providers_for("supervisor")] == ["ollama:llama3.1:8b"]
    assert [repr(p) for p in providers_for("reviewer")] == ["ollama:llama3.1:8b"]


def test_live_mode_prefers_hosted_models_when_keys_exist(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    reset_router()
    chain = [repr(p) for p in providers_for("research", "low")]
    assert chain[0] == "anthropic:claude-haiku-5-5"
    assert chain[-1].startswith("ollama:")
