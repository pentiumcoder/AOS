"""Escalation predicates and the conditional edges of the orchestration graph.

The predicates decide when a human should be asked. Until the approval queue exists the
escalate node resolves every request automatically.
"""

from typing import Any

from langgraph.types import Send

from aos.config import get_settings
from aos.graph.helpers import dep_outputs, load_plan, load_results
from aos.schemas import ExecutionPlan, ProposedAction, Review

NOTIFY = "NOTIFY"
APPROVE_ACTION = "APPROVE_ACTION"
APPROVE_PLAN = "APPROVE_PLAN"
TAKE_OVER = "TAKE_OVER"

RESUME_AT = {
    "plan": "schedule",
    "review": "schedule",
    "synthesize": "execute_actions",
    "execute_actions": "execute_actions",
}


def escalation_request(
    trigger: str, level: str, *, origin: str, reason: str, **extra: Any
) -> dict[str, Any]:
    scope = extra.get("subtask_id") or extra.get("action_id") or "run"
    return {
        "step_key": f"{origin}:{trigger}:{scope}",
        "trigger": trigger,
        "level": level,
        "origin": origin,
        "reason": reason,
        **extra,
    }


def plan_escalation(plan: ExecutionPlan) -> dict[str, Any] | None:
    threshold = get_settings().plan_confidence_threshold
    if plan.confidence < threshold:
        return escalation_request(
            "low_plan_confidence",
            APPROVE_PLAN,
            origin="plan",
            reason=f"plan confidence {plan.confidence:.2f} is below {threshold:.2f}",
        )
    return None


def failure_escalation(subtask_id: str, failures: int, error: str | None) -> dict[str, Any] | None:
    if failures >= get_settings().max_attempts:
        return escalation_request(
            "repeated_specialist_failure",
            TAKE_OVER,
            origin="review",
            subtask_id=subtask_id,
            reason=f"{subtask_id} failed {failures} times: {error}",
        )
    return None


def review_escalation(review: Review) -> dict[str, Any] | None:
    threshold = get_settings().review_escalate_score
    if review.score < threshold:
        return escalation_request(
            "low_review_score",
            APPROVE_ACTION,
            origin="review",
            subtask_id=review.subtask_id,
            reason=(
                f"{review.subtask_id} still scores {review.score:.2f} after the maximum "
                "number of revisions"
            ),
        )
    return None


def final_escalation(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("require_human_review"):
        return escalation_request(
            "user_requested_review",
            APPROVE_ACTION,
            origin="synthesize",
            reason="the task was submitted with human review of the deliverable",
        )
    return None


def action_escalation(action: ProposedAction) -> dict[str, Any]:
    return escalation_request(
        "sensitive_operation",
        APPROVE_ACTION,
        origin="execute_actions",
        action_id=action.id,
        subtask_id=action.subtask_id,
        reason=f"{action.agent} wants to run {action.tool}, which has side effects",
    )


def after_plan(state: dict[str, Any]) -> str:
    if state.get("plan") is None:
        return "deliver"
    return "escalate" if state.get("pending_escalations") else "schedule"


def dispatch(state: dict[str, Any]) -> list[Send] | str:
    status = state.get("subtask_status") or {}
    running = [sid for sid, value in status.items() if value == "running"]
    if running:
        plan, results = load_plan(state), load_results(state)
        return [
            Send("run_specialist", specialist_task(state, plan, results, sid)) for sid in running
        ]
    if any(value == "done" for value in status.values()):
        return "synthesize"
    return "deliver"


def specialist_task(
    state: dict[str, Any], plan: ExecutionPlan, results: dict[str, Any], subtask_id: str
) -> dict[str, Any]:
    subtask = plan.subtask(subtask_id)
    return {
        "task_id": state["task_id"],
        "run_id": state["run_id"],
        "request": state["request"],
        "subtask": subtask.model_dump(),
        "dep_outputs": dep_outputs(subtask, results),
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
