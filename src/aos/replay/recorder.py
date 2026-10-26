import json
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select

from aos.db.models import Escalation, LLMCall, ToolCall
from aos.db.session import session_scope
from aos.llm.base import LLMError, LLMProvider, LLMRequest, LLMResult, Usage
from aos.llm.base import ToolCall as Call
from aos.llm.hooks import call_key, prompt_hash
from aos.schemas.escalation import HumanDecision

Mode = Literal["recorded", "live"]


@dataclass
class Recorded:
    id: str
    prompt_hash: str
    provider: str
    model: str
    response: dict[str, Any]
    input_tokens: int
    output_tokens: int


@dataclass
class ReplaySession:
    """What a replay run may reuse from its parent run, and what it has used so far."""

    run_id: str
    parent_run_id: str
    mode: Mode
    overrides: dict[str, dict[str, Any]]
    calls: dict[str, list[Recorded]]
    tools: dict[str, list[dict[str, Any]]]
    decisions: list[tuple[str, dict[str, Any]]]
    memory_context: dict[str, Any] | None
    used_calls: Counter = field(default_factory=Counter)
    used_tools: Counter = field(default_factory=Counter)
    used_decisions: set[int] = field(default_factory=set)
    replayed: int = 0
    fresh: int = 0
    overridden: list[str] = field(default_factory=list)
    divergence: dict[str, Any] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def answer(self, request: LLMRequest) -> LLMResult | None:
        """The recorded or overridden result for this call, or None to call a real model."""
        key = call_key(request)
        with self.lock:
            position = self.used_calls[key]
            self.used_calls[key] += 1
            candidates = self.calls.get(key, [])
            recorded = candidates[position] if position < len(candidates) else None
            if recorded is not None and recorded.id in self.overrides:
                self.overridden.append(recorded.id)
                return _result(recorded, self.overrides[recorded.id], replayed=False)
            if self.mode == "live":
                self.fresh += 1
                return None
            if recorded is not None and recorded.prompt_hash == prompt_hash(request):
                self.replayed += 1
                return _result(recorded, recorded.response, replayed=True)
            self.fresh += 1
            if self.divergence is None:
                self.divergence = {
                    "call_key": key,
                    "agent": request.role,
                    "purpose": request.meta.get("purpose"),
                    "subtask_id": request.meta.get("subtask_id"),
                    "reason": "inputs changed" if recorded else "no recorded call at this step",
                }
            return None

    def tool_output(self, subtask_id: str | None, agent: str, tool: str, args: Any) -> Any:
        key = _tool_key(subtask_id, agent, tool, args)
        with self.lock:
            position = self.used_tools[key]
            self.used_tools[key] += 1
            recorded = self.tools.get(key, [])
            return recorded[position] if position < len(recorded) else None

    def decision_for(self, trigger: str) -> HumanDecision:
        with self.lock:
            for index, (recorded_trigger, decision) in enumerate(self.decisions):
                if index not in self.used_decisions and recorded_trigger == trigger:
                    self.used_decisions.add(index)
                    return HumanDecision.model_validate(decision)
        return HumanDecision(action="approve", reviewer="replay", comment="no recorded decision")

    def summary(self) -> dict[str, Any]:
        return {
            "parent_run_id": self.parent_run_id,
            "mode": self.mode,
            "replayed_calls": self.replayed,
            "fresh_calls": self.fresh,
            "overridden_calls": self.overridden,
            "divergence": self.divergence,
        }


class ReplayProvider(LLMProvider):
    name = "replay"

    def __init__(self, session: ReplaySession, fallback: list[LLMProvider]) -> None:
        super().__init__("recorded")
        self.session = session
        self.fallback = fallback

    def complete(self, request: LLMRequest) -> LLMResult:
        result = self.session.answer(request)
        if result is not None:
            return result
        failures = []
        for provider in self.fallback:
            try:
                return provider.complete(request)
            except LLMError as exc:
                failures.append(f"{provider!r}: {exc}")
        raise LLMError("no model available after divergence: " + "; ".join(failures))


_sessions: dict[str, ReplaySession] = {}


def active_session(run_id: str | None) -> ReplaySession | None:
    return _sessions.get(run_id) if run_id else None


def activate(session: ReplaySession) -> None:
    _sessions[session.run_id] = session


def deactivate(run_id: str) -> None:
    _sessions.pop(run_id, None)


def load_session(
    run_id: str,
    parent_run_id: str,
    mode: Mode,
    overrides: dict[str, dict[str, Any]],
    memory_context: dict[str, Any] | None,
) -> ReplaySession:
    with session_scope() as session:
        llm_calls = session.scalars(
            select(LLMCall).where(LLMCall.run_id == parent_run_id).order_by(LLMCall.created_at)
        ).all()
        tool_calls = session.scalars(
            select(ToolCall).where(ToolCall.run_id == parent_run_id).order_by(ToolCall.created_at)
        ).all()
        escalations = session.scalars(
            select(Escalation)
            .where(Escalation.run_id == parent_run_id)
            .order_by(Escalation.created_at)
        ).all()
        calls: dict[str, list[Recorded]] = defaultdict(list)
        for call in llm_calls:
            calls[call.call_key or ""].append(
                Recorded(
                    id=call.id,
                    prompt_hash=call.prompt_hash,
                    provider=call.provider,
                    model=call.model,
                    response=call.response,
                    input_tokens=call.input_tokens,
                    output_tokens=call.output_tokens,
                )
            )
        tools: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for call in tool_calls:
            # Failures replay too: their error text (temp paths, timings) would differ if rerun.
            if call.output is not None and "truncated" in call.output:
                continue
            key = _tool_key(call.subtask_id, call.agent, call.tool, call.input)
            tools[key].append({"success": call.success, "output": call.output, "error": call.error})
        decisions = [(e.trigger, e.decision) for e in escalations if e.decision]
    return ReplaySession(
        run_id=run_id,
        parent_run_id=parent_run_id,
        mode=mode,
        overrides=overrides,
        calls=dict(calls),
        tools=dict(tools),
        decisions=decisions,
        memory_context=memory_context,
    )


def _tool_key(subtask_id: str | None, agent: str, tool: str, args: Any) -> str:
    return f"{subtask_id}|{agent}|{tool}|{json.dumps(args, sort_keys=True, default=str)}"


def _result(recorded: Recorded, response: dict[str, Any], *, replayed: bool) -> LLMResult:
    return LLMResult(
        text=response.get("text") or "",
        parsed=response.get("parsed"),
        tool_calls=[Call.model_validate(c) for c in response.get("tool_calls") or []],
        usage=Usage(input_tokens=recorded.input_tokens, output_tokens=recorded.output_tokens),
        provider=recorded.provider,
        model=recorded.model,
        replayed=replayed,
    )
