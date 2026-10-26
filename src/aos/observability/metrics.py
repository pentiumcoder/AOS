from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import quantiles
from typing import Any

from sqlalchemy import select

from aos.db.models import Escalation, LLMCall, Run, ToolCall
from aos.db.session import session_scope
from aos.observability.costs import summarise_calls

PAUSING_LEVELS = {"APPROVE_ACTION", "APPROVE_PLAN", "TAKE_OVER"}


def summary(days: int = 7) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    with session_scope() as session:
        runs = session.scalars(select(Run).where(Run.started_at >= since)).all()
        run_ids = [run.id for run in runs]
        calls = session.scalars(select(LLMCall).where(LLMCall.run_id.in_(run_ids))).all()
        tools = session.scalars(select(ToolCall).where(ToolCall.run_id.in_(run_ids))).all()
        escalations = session.scalars(
            select(Escalation).where(Escalation.run_id.in_(run_ids))
        ).all()
        return {
            "days": days,
            "runs": _runs(runs, calls, escalations),
            "cost_by_task_type": _by_task_type(runs, calls),
            "llm": summarise_calls(calls),
            "tools": _tools(tools),
            "escalations": _escalations(escalations),
            "daily": _daily(runs, calls, escalations),
        }


def _cost(calls: list[LLMCall]) -> float:
    return sum(call.cost_usd or 0.0 for call in calls)


def _runs(runs: list[Run], calls: list[LLMCall], escalations: list[Escalation]) -> dict[str, Any]:
    by_status: dict[str, int] = defaultdict(int)
    for run in runs:
        by_status[run.status] += 1
    paused = {e.run_id for e in escalations if e.level in PAUSING_LEVELS}
    finished = [r for r in runs if r.ended_at]
    wall = [(r.ended_at - r.started_at).total_seconds() for r in finished]
    reviews = [e.review_seconds for e in escalations if e.review_seconds is not None]
    total = _cost(calls)
    return {
        "total": len(runs),
        "by_status": dict(by_status),
        "total_cost_usd": round(total, 6),
        "avg_cost_usd": round(total / len(runs), 6) if runs else 0.0,
        "avg_wall_clock_seconds": round(sum(wall) / len(wall), 1) if wall else None,
        "escalation_rate": round(len(paused) / len(runs), 3) if runs else 0.0,
        "avg_review_seconds": round(sum(reviews) / len(reviews), 1) if reviews else None,
    }


def _by_task_type(runs: list[Run], calls: list[LLMCall]) -> list[dict[str, Any]]:
    cost_by_run: dict[str, float] = defaultdict(float)
    for call in calls:
        cost_by_run[call.run_id] += call.cost_usd or 0.0
    grouped: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        grouped[run.task_type or "unplanned"].append(cost_by_run[run.id])
    return sorted(
        (
            {
                "task_type": task_type,
                "runs": len(costs),
                "total_cost_usd": round(sum(costs), 6),
                "avg_cost_usd": round(sum(costs) / len(costs), 6),
            }
            for task_type, costs in grouped.items()
        ),
        key=lambda row: row["total_cost_usd"],
        reverse=True,
    )


def _tools(tools: list[ToolCall]) -> list[dict[str, Any]]:
    grouped: dict[str, list[ToolCall]] = defaultdict(list)
    for call in tools:
        grouped[call.tool].append(call)
    rows = []
    for tool, calls in sorted(grouped.items()):
        latencies = sorted(call.latency_ms for call in calls)
        rows.append(
            {
                "tool": tool,
                "calls": len(calls),
                "failure_rate": round(sum(int(not c.success) for c in calls) / len(calls), 3),
                "p50_ms": round(_percentile(latencies, 50), 1),
                "p95_ms": round(_percentile(latencies, 95), 1),
            }
        )
    return rows


def _escalations(escalations: list[Escalation]) -> dict[str, Any]:
    by_trigger: dict[str, int] = defaultdict(int)
    by_decision: dict[str, int] = defaultdict(int)
    for escalation in escalations:
        by_trigger[escalation.trigger] += 1
        by_decision[escalation.status] += 1
    return {
        "total": len(escalations),
        "by_trigger": dict(by_trigger),
        "by_status": dict(by_decision),
    }


def _daily(
    runs: list[Run], calls: list[LLMCall], escalations: list[Escalation]
) -> list[dict[str, Any]]:
    day_of = {run.id: run.started_at.date().isoformat() for run in runs}
    paused = {e.run_id for e in escalations if e.level in PAUSING_LEVELS}
    days: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"runs": 0, "escalated": 0, "cost_usd": 0.0}
    )
    for run in runs:
        bucket = days[day_of[run.id]]
        bucket["runs"] += 1
        bucket["escalated"] += int(run.id in paused)
    for call in calls:
        days[day_of[call.run_id]]["cost_usd"] += call.cost_usd or 0.0
    return [
        {"date": day, **values, "cost_usd": round(values["cost_usd"], 6)}
        for day, values in sorted(days.items())
    ]


def _percentile(values: list[float], percent: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return quantiles(values, n=100, method="inclusive")[percent - 1]
