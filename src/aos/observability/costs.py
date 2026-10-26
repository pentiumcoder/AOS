from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml
from sqlalchemy import select

from aos.config import get_settings
from aos.db.models import Escalation, LLMCall, Run, ToolCall
from aos.db.session import session_scope

PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    simulated: bool = False


@lru_cache
def pricing() -> dict[str, Any]:
    path = get_settings().config_dir / "pricing.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def price_for(provider: str, model: str) -> Price | None:
    table = pricing()
    entry = (table.get("models") or {}).get(model) or (table.get("providers") or {}).get(provider)
    if not entry:
        return None
    return Price(entry["input"], entry["output"], bool(entry.get("simulated")))


def cost_of(provider: str, model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = price_for(provider, model)
    if price is None:
        return None
    return (input_tokens * price.input + output_tokens * price.output) / PER_MILLION


def run_metrics(run_id: str) -> dict[str, Any]:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise KeyError(run_id)
        calls = session.scalars(select(LLMCall).where(LLMCall.run_id == run_id)).all()
        tools = session.scalars(select(ToolCall).where(ToolCall.run_id == run_id)).all()
        escalations = session.scalars(select(Escalation).where(Escalation.run_id == run_id)).all()
        wall = (run.ended_at - run.started_at).total_seconds() if run.ended_at else None
        review = sum(e.review_seconds or 0.0 for e in escalations)
        return {
            "run_id": run_id,
            "status": run.status,
            "task_type": run.task_type,
            "llm": summarise_calls(calls),
            "tools": summarise_tools(tools),
            "escalations": len(escalations),
            "human_review_seconds": round(review, 1),
            "wall_clock_seconds": round(wall, 1) if wall is not None else None,
            "agent_seconds": round(wall - review, 1) if wall is not None else None,
        }


def record_run_metrics(run_id: str) -> dict[str, Any]:
    metrics = run_metrics(run_id)
    with session_scope() as session:
        session.get(Run, run_id).metrics = metrics
    return metrics


def summarise_calls(calls: list[LLMCall]) -> dict[str, Any]:
    by_agent: dict[str, dict[str, Any]] = defaultdict(_bucket)
    by_model: dict[str, dict[str, Any]] = defaultdict(_bucket)
    total = _bucket()
    for call in calls:
        for bucket in (by_agent[call.agent], by_model[f"{call.provider}:{call.model}"], total):
            bucket["calls"] += 1
            bucket["input_tokens"] += call.input_tokens
            bucket["output_tokens"] += call.output_tokens
            bucket["replayed"] += int(call.replayed)
            if call.cost_usd is None:
                bucket["unpriced_calls"] += 1
            else:
                bucket["cost_usd"] += call.cost_usd
    simulated = any(
        (price := price_for(c.provider, c.model)) is not None and price.simulated for c in calls
    )
    return {
        **_rounded(total),
        "simulated_prices": simulated,
        "by_agent": {k: _rounded(v) for k, v in sorted(by_agent.items())},
        "by_model": {k: _rounded(v) for k, v in sorted(by_model.items())},
    }


def summarise_tools(tools: list[ToolCall]) -> dict[str, Any]:
    by_tool: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "failures": 0})
    for call in tools:
        by_tool[call.tool]["calls"] += 1
        by_tool[call.tool]["failures"] += int(not call.success)
    return {
        "calls": len(tools),
        "failures": sum(int(not c.success) for c in tools),
        "by_tool": dict(sorted(by_tool.items())),
    }


def _bucket() -> dict[str, Any]:
    return {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "unpriced_calls": 0,
        "replayed": 0,
    }


def _rounded(bucket: dict[str, Any]) -> dict[str, Any]:
    return {**bucket, "cost_usd": round(bucket["cost_usd"], 6)}
