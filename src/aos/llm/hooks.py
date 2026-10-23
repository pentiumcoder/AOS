import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from aos import context
from aos.llm.base import LLMRequest, LLMResult
from aos.logging import get_logger

log = get_logger(__name__)


@dataclass
class LLMCallRecord:
    request: LLMRequest
    result: LLMResult
    run_id: str | None = field(default_factory=lambda: context.get("run_id"))
    subtask_id: str | None = field(default_factory=lambda: context.get("subtask_id"))
    call_key: str | None = None

    @property
    def prompt_hash(self) -> str:
        return prompt_hash(self.request)


LLMHook = Callable[[LLMCallRecord], None]
_hooks: list[LLMHook] = []


def register_llm_hook(hook: LLMHook) -> None:
    if hook not in _hooks:
        _hooks.append(hook)


def unregister_llm_hook(hook: LLMHook) -> None:
    if hook in _hooks:
        _hooks.remove(hook)


def emit(record: LLMCallRecord) -> None:
    for hook in (persist_llm_call, *_hooks):
        try:
            hook(record)
        except Exception:
            log.exception("llm hook failed", extra={"fields": {"hook": hook.__name__}})


def prompt_hash(request: LLMRequest) -> str:
    payload = {
        "system": request.system,
        "messages": [m.model_dump() for m in request.messages],
        "tools": [t.name for t in request.tools],
        "schema": request.schema_name,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if isinstance(value, BaseModel) else value


def persist_llm_call(record: LLMCallRecord) -> None:
    from aos.db.models import LLMCall
    from aos.db.session import session_scope

    request, result = record.request, record.result
    scalar_meta = {
        k: v
        for k, v in request.meta.items()
        if isinstance(v, str | int | float | bool) and k != "request"
    }
    with session_scope() as session:
        session.add(
            LLMCall(
                run_id=record.run_id,
                subtask_id=record.subtask_id,
                agent=request.role,
                purpose=request.meta.get("purpose"),
                provider=result.provider,
                model=result.model,
                call_key=record.call_key,
                prompt_hash=record.prompt_hash,
                messages={
                    "system": request.system,
                    "messages": [m.model_dump() for m in request.messages],
                    "tools": [t.name for t in request.tools],
                    "schema": request.schema_name,
                    "meta": scalar_meta,
                },
                response={
                    "text": result.text,
                    "parsed": _dump(result.parsed),
                    "tool_calls": [c.model_dump() for c in result.tool_calls],
                },
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                latency_ms=result.latency_ms,
            )
        )
