import json
import time
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from aos import context
from aos.config import get_settings
from aos.llm import hooks
from aos.llm.base import (
    RESPOND_TOOL,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResult,
    LLMUnavailable,
    Message,
    StructuredOutputError,
    ToolDef,
    TransientLLMError,
    json_from_text,
)
from aos.llm.mock_provider import MockProvider
from aos.logging import get_logger
from aos.observability import costs, tracing

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

SPECIALIST_ROLES = {"research", "data_analysis", "writing", "code"}


class LLMClient:
    def __init__(
        self,
        role: str,
        providers: Sequence[LLMProvider],
        retries: int = 2,
        backoff_s: float = 0.5,
    ) -> None:
        if not providers:
            raise LLMUnavailable(f"no provider configured for role {role}")
        self.role = role
        self.providers = list(providers)
        self.retries = retries
        self.backoff_s = backoff_s

    def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        tools: Sequence[ToolDef] | None = None,
        schema: type[BaseModel] | None = None,
        max_tokens: int = 2048,
        meta: dict[str, Any] | None = None,
    ) -> LLMResult:
        request = LLMRequest(
            role=self.role,
            messages=list(messages),
            system=system,
            tools=list(tools or []),
            schema_name=schema.__name__ if schema else None,
            response_schema=schema.model_json_schema() if schema else None,
            max_tokens=max_tokens,
            meta=meta or {},
        )
        failures = []
        for provider in self.providers:
            try:
                return self._complete_with(provider, request, schema)
            except LLMError as exc:
                failures.append(f"{provider!r}: {exc}")
                log.warning(
                    "llm provider failed",
                    extra={"fields": {"provider": repr(provider), "error": str(exc)}},
                )
        raise LLMUnavailable(f"all providers failed for {self.role}: " + "; ".join(failures))

    def _complete_with(
        self, provider: LLMProvider, request: LLMRequest, schema: type[BaseModel] | None
    ) -> LLMResult:
        result = self._call(provider, request)
        if schema is None or (result.parsed is None and result.tool_calls):
            return result
        try:
            result.parsed = _validate(schema, result)
            return result
        except (ValidationError, ValueError) as exc:
            first_error = exc
        previous = result.text or json.dumps(result.parsed, default=str)
        repair = request.model_copy(
            update={
                "messages": [
                    *request.messages,
                    Message.assistant(previous),
                    Message.user(
                        f"That reply did not match the {request.schema_name} structure: "
                        f"{_short(first_error)}. Answer again with the {RESPOND_TOOL} tool "
                        "and valid arguments."
                    ),
                ]
            }
        )
        retry = self._call(provider, repair)
        if retry.parsed is None and retry.tool_calls:
            return retry
        try:
            retry.parsed = _validate(schema, retry)
        except (ValidationError, ValueError) as exc:
            raise StructuredOutputError(f"invalid {request.schema_name}: {_short(exc)}") from exc
        return retry

    def _call(self, provider: LLMProvider, request: LLMRequest) -> LLMResult:
        attributes = {
            "agent": request.role,
            "purpose": request.meta.get("purpose"),
            "provider": provider.name,
            "model": provider.model,
            "subtask_id": request.meta.get("subtask_id") or context.get("subtask_id"),
            "attempt": request.meta.get("attempt") or context.get("attempt"),
        }
        with tracing.span("llm.call", **attributes) as span:
            delay = self.backoff_s
            for attempt in range(self.retries + 1):
                try:
                    result = provider.complete(request)
                except TransientLLMError:
                    if attempt == self.retries:
                        raise
                    time.sleep(delay)
                    delay *= 2
                    continue
                cost = (
                    0.0
                    if result.replayed
                    else costs.cost_of(
                        result.provider,
                        result.model,
                        result.usage.input_tokens,
                        result.usage.output_tokens,
                    )
                )
                tracing.annotate(
                    tokens__input=result.usage.input_tokens,
                    tokens__output=result.usage.output_tokens,
                    cost_usd=cost,
                    latency_ms=round(result.latency_ms, 1),
                    retries=attempt,
                    replayed=result.replayed,
                )
                record = hooks.LLMCallRecord(
                    request=request,
                    result=result,
                    span_id=tracing.current_span_id(),
                    cost_usd=cost,
                )
                span.set_attribute("aos.call_key", record.call_key)
                hooks.emit(record)
                return result
        raise AssertionError("unreachable")


def _validate(schema: type[T], result: LLMResult) -> T:
    payload = result.parsed if result.parsed is not None else json_from_text(result.text)
    return schema.model_validate(payload)


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'root'}: {e['msg']}" for e in exc.errors()[:5]
        )
    return str(exc)[:300]


@lru_cache
def _routing() -> dict[str, Any]:
    path = get_settings().config_dir / "models.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _chain_specs(role: str, complexity: str) -> list[str]:
    roles = _routing()["roles"]
    key = "specialist" if role in SPECIALIST_ROLES and role not in roles else role
    entry = roles.get(key, roles["default"])
    if isinstance(entry, dict):
        entry = entry.get(complexity) or entry["medium"]
    return list(entry)


@lru_cache
def _build_provider(provider: str, model: str) -> LLMProvider | None:
    settings = get_settings()
    if not model:
        return None
    if provider == "ollama":
        from aos.llm.ollama_provider import OllamaProvider

        return OllamaProvider(
            model,
            settings.ollama_base_url,
            num_ctx=settings.ollama_num_ctx,
            temperature=settings.ollama_temperature,
        )
    if provider == "anthropic" and settings.anthropic_api_key:
        from aos.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model, settings.anthropic_api_key)
    if provider == "openai" and settings.openai_api_key:
        from aos.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(model, settings.openai_api_key)
    return None


def providers_for(role: str, complexity: str = "medium") -> list[LLMProvider]:
    settings = get_settings()
    if settings.llm_mode == "mock":
        return [MockProvider()]
    variables = {
        "ollama_model": settings.ollama_model,
        "openai_reviewer_model": settings.openai_reviewer_model,
    }
    chain = []
    for spec in _chain_specs(role, complexity):
        provider, _, model = spec.partition(":")
        built = _build_provider(provider, model.format(**variables))
        if built is not None:
            chain.append(built)
    return chain


def get_llm(role: str, complexity: str = "medium") -> LLMClient:
    from aos.replay.recorder import ReplayProvider, active_session

    session = active_session(context.get("run_id"))
    if session is not None:
        replay = ReplayProvider(session, providers_for(role, complexity))
        return LLMClient(role, [replay], retries=0)
    return LLMClient(role, providers_for(role, complexity))


def reset_router() -> None:
    _routing.cache_clear()
    _build_provider.cache_clear()
