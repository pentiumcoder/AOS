"""Escalation predicates and the conditional edges of the orchestration graph."""

from typing import Any

from langgraph.types import Send

from aos.graph.helpers import load_plan
from aos.hitl.policy import get_policy
from aos.schemas import ExecutionPlan, ProposedAction, Review
from aos.schemas.escalation import EscalationRequest

RESUME_AT = {
    "plan": "schedule",
    "review": "schedule",
    "synthesize": "execute_actions",
    "execute_actions": "execute_actions",
}


def _dump(request: EscalationRequest | None) -> dict[str, Any] | None:
    return request.model_dump() if request else None


def plan_escalation(plan: ExecutionPlan) -> dict[str, Any] | None:
    return _dump(get_policy().check_plan(plan))


def failure_escalation(subtask_id: str, failures: int, error: str | None) -> dict[str, Any] | None:
    return _dump(get_policy().check_subtask(subtask_id, failures, error))


def review_escalation(review: Review) -> dict[str, Any] | None:
    return _dump(get_policy().check_review(review))


def final_escalation(state: dict[str, Any]) -> dict[str, Any] | None:
    return _dump(get_policy().check_final(bool(state.get("require_human_review"))))


def action_escalation(action: ProposedAction) -> dict[str, Any] | None:
    return _dump(get_policy().check_action(action))


def after_plan(state: dict[str, Any]) -> str:
    if state.get("plan") is None:
        return "deliver"
    return "escalate" if state.get("pending_escalations") else "schedule"


def dispatch(state: dict[str, Any]) -> list[Send] | str:
    status = state.get("subtask_status") or {}
    running = [sid for sid, value in status.items() if value == "running"]
    if running:
        plan = load_plan(state)
        return [Send("run_specialist", specialist_task(state, plan, sid)) for sid in running]
    if any(value == "done" for value in status.values()):
        return "synthesize"
    return "deliver"


def specialist_task(state: dict[str, Any], plan: ExecutionPlan, subtask_id: str) -> dict[str, Any]:
    subtask = plan.subtask(subtask_id)
    return {
        "task_id": state["task_id"],
        "run_id": state["run_id"],
        "request": state["request"],
        "subtask": subtask.model_dump(),
        "attempt": (state.get("visits") or {}).get(subtask_id, 1),
        "feedback": (state.get("feedback") or {}).get(subtask_id),
        "approach_hint": (state.get("approach_hints") or {}).get(subtask_id),
    }


def after_review(state: dict[str, Any]) -> str:
    return "escalate" if state.get("pending_escalations") else "schedule"


def after_synthesize(state: dict[str, Any]) -> str:
    return "escalate" if state.get("pending_escalations") else "execute_actions"


def after_actions(state: dict[str, Any]) -> str:
    return "escalate" if state.get("pending_escalations") else "deliver"


def after_escalation(state: dict[str, Any]) -> str:
    return state.get("resume_at") or "deliver"
