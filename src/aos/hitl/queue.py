from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from aos.db.models import Escalation, utcnow
from aos.db.session import session_scope
from aos.hitl.levels import ApprovalLevel, allowed
from aos.logging import get_logger
from aos.memory import WorkingMemory
from aos.schemas.escalation import HumanDecision
from aos.schemas.memory import MemoryItem

log = get_logger(__name__)

STATUS_FOR = {
    "approve": "approved",
    "modify": "modified",
    "reject": "rejected",
    "take_over": "taken_over",
}
PREVIEW = 4000


class DecisionError(ValueError):
    pass


def queue_key(state: dict[str, Any], request: dict[str, Any]) -> str:
    """step_key plus how often that step has already escalated in this run.

    A re-planned run can hit the same trigger again; each occurrence needs its own row,
    while re-executing the paused node must find the row it created before.
    """
    earlier = sum(1 for e in state.get("escalations") or [] if e["step_key"] == request["step_key"])
    return f"{request['step_key']}#{earlier}"


def open_escalation(state: dict[str, Any], request: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Get or create the queue entry for a request. Returns (escalation, created)."""
    key = queue_key(state, request)
    with session_scope() as session:
        existing = session.scalars(
            select(Escalation).where(
                Escalation.run_id == state["run_id"], Escalation.step_key == key
            )
        ).first()
        if existing is not None:
            return _row(existing), False
    notify_only = request["level"] == ApprovalLevel.NOTIFY
    row = Escalation(
        run_id=state["run_id"],
        task_id=state["task_id"],
        step_key=key,
        level=request["level"],
        trigger=request["trigger"],
        origin=request["origin"],
        reason=request["reason"],
        subtask_id=request.get("subtask_id"),
        action_id=request.get("action_id"),
        status="auto_proceeded" if notify_only else "pending",
        context=package_context(state, request),
        proposed_action=_action(state, request.get("action_id")),
    )
    try:
        with session_scope() as session:
            session.add(row)
            session.flush()
            return _row(row), True
    except IntegrityError:
        return open_escalation(state, request)


def package_context(state: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    plan = state.get("plan") or {}
    status = state.get("subtask_status") or {}
    results = state.get("results") or {}
    outputs = WorkingMemory(state["run_id"]).outputs()
    completed = [
        {
            "id": s["id"],
            "specialist": s["specialist"],
            "description": s["description"],
            "output": _preview(
                (outputs.get(s["id"]) or {}).get("output")
                or (results.get(s["id"]) or {}).get("output")
            ),
        }
        for s in plan.get("subtasks", [])
        if status.get(s["id"]) == "done"
    ]
    current = None
    if subtask_id := request.get("subtask_id"):
        subtask = next((s for s in plan.get("subtasks", []) if s["id"] == subtask_id), None)
        result = results.get(subtask_id) or {}
        current = {
            "subtask": subtask,
            "output": _preview(result.get("output")),
            "error": result.get("error"),
            "evidence": result.get("evidence", []),
            "reviews": (state.get("reviews") or {}).get(subtask_id, []),
        }
    memories = state.get("memory_context") or {}
    recalled = [
        {"id": m["id"], "kind": m["kind"], "text": m["text"]}
        for field in ("similar_tasks", "worked", "failed", "preferences", "facts", "decisions")
        for m in memories.get(field, [])
    ]
    return {
        "task": {
            "request": state["request"],
            "user_id": state.get("user_id"),
            "require_human_review": state.get("require_human_review", False),
        },
        "plan": plan,
        "completed": completed,
        "current": current,
        "final_output": _preview(state.get("final_output")),
        "memories": recalled,
        "past_decisions": _past_decisions(state, request),
    }


def record_decision(escalation_id: str, decision: HumanDecision) -> dict[str, Any]:
    with session_scope() as session:
        row = session.get(Escalation, escalation_id)
        if row is None:
            raise KeyError(escalation_id)
        if row.status != "pending":
            raise DecisionError(f"escalation is already {row.status}")
        if not allowed(row.level, decision.action):
            raise DecisionError(f"{decision.action} is not allowed for {row.level}")
        now = utcnow()
        row.status = STATUS_FOR[decision.action]
        row.decision = decision.model_dump(mode="json")
        row.decided_by = decision.reviewer
        row.decided_at = now
        row.review_seconds = (now - _aware(row.created_at)).total_seconds()
        result = _row(row)
    _remember(result, decision)
    return result


def get_escalation(escalation_id: str) -> dict[str, Any] | None:
    with session_scope() as session:
        row = session.get(Escalation, escalation_id)
        return _row(row) if row else None


def list_escalations(
    status: str | None = None, run_id: str | None = None, task_id: str | None = None
) -> list[dict[str, Any]]:
    with session_scope() as session:
        query = select(Escalation).order_by(Escalation.created_at.desc())
        if status:
            query = query.where(Escalation.status == status)
        if run_id:
            query = query.where(Escalation.run_id == run_id)
        if task_id:
            query = query.where(Escalation.task_id == task_id)
        return [_row(row) for row in session.scalars(query)]


def append_chat(escalation_id: str, *messages: dict[str, str]) -> list[dict[str, str]]:
    with session_scope() as session:
        row = session.get(Escalation, escalation_id)
        if row is None:
            raise KeyError(escalation_id)
        row.chat = [*(row.chat or []), *messages]
        return list(row.chat)


def _remember(escalation: dict[str, Any], decision: HumanDecision) -> None:
    from aos.memory.longterm import LongTermMemory

    user_id = escalation["context"]["task"].get("user_id") or "default"
    comment = f" Comment: {decision.comment}" if decision.comment else ""
    text = (
        f"When {escalation['trigger'].replace('_', ' ')} came up ({escalation['reason']}), "
        f"the reviewer chose to {decision.action.replace('_', ' ')}.{comment}"
    )
    try:
        LongTermMemory().add(
            user_id,
            MemoryItem(
                kind="human_decision", text=text, importance=0.6, tags=[escalation["trigger"]]
            ),
            source_run_id=escalation["run_id"],
        )
    except Exception:
        log.exception("could not store the decision as a memory")


def _past_decisions(state: dict[str, Any], request: dict[str, Any]) -> list[dict[str, Any]]:
    from aos.memory.longterm import LongTermMemory

    try:
        found = LongTermMemory().search(
            state.get("user_id") or "default",
            f"{request['trigger'].replace('_', ' ')} {request['reason']}",
            kinds=["human_decision"],
            k=3,
        )
    except Exception:
        log.exception("could not load past decisions")
        return []
    return [{"id": m.id, "text": m.text, "similarity": m.similarity} for m in found]


def _action(state: dict[str, Any], action_id: str | None) -> dict[str, Any] | None:
    if action_id is None:
        return None
    return next((a for a in state.get("actions") or [] if a["id"] == action_id), None)


def _preview(text: str | None) -> str | None:
    return text[:PREVIEW] if text else text


def _aware(moment: Any) -> Any:
    from datetime import UTC

    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _row(row: Escalation) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "task_id": row.task_id,
        "step_key": row.step_key,
        "level": row.level,
        "trigger": row.trigger,
        "origin": row.origin,
        "reason": row.reason,
        "status": row.status,
        "subtask_id": row.subtask_id,
        "action_id": row.action_id,
        "context": row.context,
        "proposed_action": row.proposed_action,
        "decision": row.decision,
        "chat": row.chat or [],
        "decided_by": row.decided_by,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
        "review_seconds": row.review_seconds,
    }
