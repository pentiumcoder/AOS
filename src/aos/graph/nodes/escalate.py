from typing import Any

from aos.graph.instrument import traced_node
from aos.graph.routing import RESUME_AT
from aos.logging import get_logger
from aos.schemas.state import event

log = get_logger(__name__)

# What each trigger resolves to when no reviewer is available.
AUTO_DECISIONS = {
    "low_plan_confidence": "approve",
    "repeated_specialist_failure": "give_up",
    "low_review_score": "accept",
    "user_requested_review": "approve",
    "sensitive_operation": "approve",
}


@traced_node("escalate")
def escalate(state: dict[str, Any]) -> dict[str, Any]:
    pending = state.get("pending_escalations") or []
    status = dict(state.get("subtask_status") or {})
    actions = [dict(a) for a in state.get("actions") or []]
    records, events = [], []

    for request in pending:
        decision = AUTO_DECISIONS.get(request["trigger"], "approve")
        subtask_id = request.get("subtask_id")
        if request["trigger"] == "repeated_specialist_failure" and subtask_id:
            status[subtask_id] = "failed"
        elif request["trigger"] == "low_review_score" and subtask_id:
            status[subtask_id] = "done"
        elif request["trigger"] == "sensitive_operation":
            for action in actions:
                if action["id"] == request.get("action_id"):
                    action["status"] = "approved"
        log.warning(
            "escalation resolved without a reviewer",
            extra={"fields": {"trigger": request["trigger"], "decision": decision}},
        )
        records.append({**request, "decision": decision, "resolved_by": "auto"})
        events.append(
            event(
                "escalate",
                "escalation",
                f"{request['trigger']} ({request['level']}): {request['reason']}; "
                f"auto-resolved as {decision}",
                trigger=request["trigger"],
                level=request["level"],
            )
        )

    origin = pending[0]["origin"] if pending else "review"
    update: dict[str, Any] = {
        "pending_escalations": [],
        "escalations": records,
        "subtask_status": status,
        "resume_at": RESUME_AT.get(origin, "deliver"),
        "events": events,
    }
    if state.get("actions") is not None:
        update["actions"] = actions
    return update
