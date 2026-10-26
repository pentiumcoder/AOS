from dataclasses import dataclass, field
from typing import Any

from langgraph.types import interrupt

from aos.graph.helpers import update_run, update_task
from aos.graph.instrument import traced_node
from aos.graph.routing import RESUME_AT
from aos.hitl.levels import ApprovalLevel
from aos.hitl.notifications import notify
from aos.hitl.queue import get_escalation, open_escalation
from aos.memory import WorkingMemory
from aos.observability import tracing
from aos.replay.recorder import active_session
from aos.schemas import ExecutionPlan, SpecialistResult, validate_plan
from aos.schemas.escalation import HumanDecision
from aos.schemas.state import event


@dataclass
class Outcome:
    """Everything the decisions of one escalation batch change in the run state."""

    state: dict[str, Any]
    status: dict[str, str]
    actions: list[dict[str, Any]] | None
    resume_at: str
    updates: dict[str, Any] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    feedback: dict[str, str] = field(default_factory=dict)
    hints: dict[str, str] = field(default_factory=dict)
    records: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


@traced_node("escalate")
def escalate(state: dict[str, Any]) -> dict[str, Any]:
    pending = state.get("pending_escalations") or []
    origin = pending[0]["origin"] if pending else "review"
    outcome = Outcome(
        state=state,
        status=dict(state.get("subtask_status") or {}),
        actions=[dict(a) for a in state["actions"]] if state.get("actions") is not None else None,
        resume_at=RESUME_AT.get(origin, "deliver"),
    )
    for request in pending:
        with tracing.span(
            "hitl.escalation",
            escalation__level=request["level"],
            escalation__trigger=request["trigger"],
            subtask_id=request.get("subtask_id"),
            status="escalated",
        ):
            _handle(outcome, state, request)

    update_run(state["run_id"], status="running")
    update_task(state["task_id"], status="running")
    update: dict[str, Any] = {
        **outcome.updates,
        "pending_escalations": [],
        "escalations": outcome.records,
        "subtask_status": outcome.status,
        "results": outcome.results,
        "feedback": outcome.feedback,
        "approach_hints": outcome.hints,
        "resume_at": outcome.resume_at,
        "events": outcome.events,
    }
    if outcome.actions is not None:
        update["actions"] = outcome.actions
    return update


def _handle(outcome: Outcome, state: dict[str, Any], request: dict[str, Any]) -> None:
    replay = active_session(state["run_id"])
    if replay is not None:
        _replay_decision(outcome, request, replay.decision_for(request["trigger"]))
        return
    escalation, created = open_escalation(state, request)
    if created:
        notify(escalation)
    tracing.annotate(escalation__id=escalation["id"])
    if request["level"] == ApprovalLevel.NOTIFY:
        outcome.records.append({**request, "escalation_id": escalation["id"], "decision": None})
        outcome.events.append(
            event("escalate", "notify", f"{request['trigger']}: {request['reason']}")
        )
        return
    update_run(state["run_id"], status="awaiting_human")
    update_task(state["task_id"], status="awaiting_human")
    # LangGraph re-runs this node from the top on every resume and hands back answers in
    # call order, so interrupt() must be reached for each escalation every time.
    answer = interrupt(
        {
            "escalation_id": escalation["id"],
            "level": request["level"],
            "trigger": request["trigger"],
            "reason": request["reason"],
        }
    )
    decision = HumanDecision.model_validate(answer)
    decided = get_escalation(escalation["id"]) or {}
    tracing.annotate(
        escalation__decision=decision.action,
        escalation__reviewer=decision.reviewer,
        review_seconds=decided.get("review_seconds"),
    )
    apply_decision(outcome, request, decision)
    outcome.records.append(
        {
            **request,
            "escalation_id": escalation["id"],
            "decision": decision.action,
            "comment": decision.comment,
            "resolved_by": decision.reviewer,
        }
    )
    outcome.events.append(
        event(
            "escalate",
            "decision",
            f"{request['trigger']} ({request['level']}): {decision.reviewer} chose "
            f"{decision.action}" + (f" - {decision.comment}" if decision.comment else ""),
            trigger=request["trigger"],
            level=request["level"],
        )
    )


def _replay_decision(outcome: Outcome, request: dict[str, Any], decision: HumanDecision) -> None:
    if request["level"] == ApprovalLevel.NOTIFY:
        outcome.records.append({**request, "decision": None, "replayed": True})
        return
    tracing.annotate(escalation__decision=decision.action, escalation__reviewer=decision.reviewer)
    apply_decision(outcome, request, decision)
    outcome.records.append(
        {**request, "decision": decision.action, "resolved_by": decision.reviewer, "replayed": True}
    )
    outcome.events.append(
        event(
            "escalate",
            "decision",
            f"{request['trigger']} ({request['level']}): reused {decision.reviewer}'s "
            f"{decision.action} from the original run",
        )
    )


def apply_decision(outcome: Outcome, request: dict[str, Any], decision: HumanDecision) -> None:
    handler = {
        "plan": _plan_decision,
        "review": _subtask_decision,
        "synthesize": _deliverable_decision,
        "execute_actions": _action_decision,
    }[request["origin"]]
    handler(outcome, request, decision)


def _plan_decision(outcome: Outcome, request: dict[str, Any], decision: HumanDecision) -> None:
    if decision.action == "reject":
        outcome.updates["plan_feedback"] = decision.comment or "The reviewer rejected the plan."
        outcome.resume_at = "plan"
        return
    if decision.action == "modify" and decision.payload:
        edited = ExecutionPlan.model_validate(decision.payload)
        if errors := validate_plan(edited):
            outcome.updates["plan_feedback"] = "The edited plan is invalid: " + "; ".join(errors)
            outcome.resume_at = "plan"
            return
        state = outcome.state
        plan = edited.model_dump(mode="json")
        update_run(state["run_id"], plan=plan, task_type=edited.task_type)
        WorkingMemory(state["run_id"]).set_plan(plan)
        outcome.updates["plan"] = plan
        outcome.status.update({s.id: "pending" for s in edited.subtasks})


def _subtask_decision(outcome: Outcome, request: dict[str, Any], decision: HumanDecision) -> None:
    sid = request["subtask_id"]
    if decision.action in ("take_over", "modify") and decision.payload is not None:
        _human_output(outcome, sid, str(decision.payload))
    elif decision.action == "approve" and request["trigger"] == "repeated_specialist_failure":
        outcome.status[sid] = "retry"
        outcome.hints[sid] = decision.comment or "Try a different approach."
    elif decision.action == "approve":
        outcome.status[sid] = "done"
    elif decision.action == "reject":
        outcome.status[sid] = "needs_revision"
        outcome.feedback[sid] = decision.comment or "The reviewer rejected this output."
    else:
        outcome.status[sid] = "failed"


def _deliverable_decision(
    outcome: Outcome, request: dict[str, Any], decision: HumanDecision
) -> None:
    if decision.action in ("take_over", "modify") and decision.payload is not None:
        outcome.updates["final_output"] = str(decision.payload)
    elif decision.action == "reject":
        plan = ExecutionPlan.model_validate(outcome.state["plan"])
        writers = [s for s in plan.subtasks if s.specialist == "writing"] or plan.subtasks
        target = writers[-1].id
        outcome.status[target] = "needs_revision"
        outcome.feedback[target] = decision.comment or "The reviewer rejected the deliverable."
        outcome.resume_at = "schedule"


def _action_decision(outcome: Outcome, request: dict[str, Any], decision: HumanDecision) -> None:
    for action in outcome.actions or []:
        if action["id"] != request["action_id"]:
            continue
        if decision.action == "approve":
            action["status"] = "approved"
        elif decision.action == "modify":
            if isinstance(decision.payload, dict):
                action["args"] = {**action["args"], **decision.payload}
            action["status"] = "approved"
        else:
            action["status"] = "rejected"
            verb = "rejected" if decision.action == "reject" else "taken over"
            action["result"] = f"{verb} by {decision.reviewer}" + (
                f": {decision.comment}" if decision.comment else ""
            )


def _human_output(outcome: Outcome, sid: str, text: str) -> None:
    result = SpecialistResult(
        subtask_id=sid, specialist="human", status="success", output=text, confidence=1.0
    )
    outcome.results[sid] = result.model_dump(mode="json")
    outcome.status[sid] = "done"
    WorkingMemory(outcome.state["run_id"]).put_output(sid, text)
