import json
from typing import Any

from aos import context
from aos.graph.helpers import load_plan, load_results
from aos.graph.instrument import traced_node
from aos.graph.routing import action_escalation
from aos.schemas import ProposedAction
from aos.schemas.state import event
from aos.tools import policy
from aos.tools.registry import get_registry

FINAL_OUTPUT_TOKEN = "{{final_output}}"


@traced_node("execute_actions")
def execute_actions(state: dict[str, Any]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    if state.get("actions") is None:
        proposal = _propose(state)
        if proposal["pending_escalations"]:
            return proposal
        raw_actions, events = proposal["actions"], proposal["events"]
    else:
        raw_actions = state["actions"]

    registry = get_registry()
    final_output = state.get("final_output") or ""
    actions = []
    for raw in raw_actions:
        action = ProposedAction.model_validate(raw)
        if action.status == "approved":
            # Checked again because a reviewer may have edited the arguments.
            if problem := policy.check_action(action.tool, action.args, state["request"]):
                action.status, action.result = "rejected", problem
            else:
                with context.bind(subtask_id=action.subtask_id, agent=action.agent):
                    outcome = registry.invoke(
                        action.agent, action.tool, _fill(action.args, final_output)
                    )
                action.status = "executed" if outcome.success else "failed"
                action.result = outcome.output if outcome.success else outcome.error
            detail = f": {action.result}" if action.status == "rejected" else ""
            events.append(
                event(
                    "execute_actions",
                    action.status,
                    f"{action.tool} {action.status}{detail}",
                    action_id=action.id,
                )
            )
        actions.append(action.model_dump(mode="json"))
    return {"actions": actions, "pending_escalations": [], "events": events}


def _propose(state: dict[str, Any]) -> dict[str, Any]:
    actions, events = [], []
    for action in _collect(state):
        if problem := policy.check_action(action.tool, action.args, state["request"]):
            action.status, action.result = "rejected", problem
            events.append(event("execute_actions", "rejected", f"{action.tool} blocked: {problem}"))
        actions.append(action)
    escalations = []
    for action in (a for a in actions if a.status == "proposed"):
        if request := action_escalation(action):
            escalations.append(request)
        else:
            action.status = "approved"
    if escalations:
        events.append(
            event(
                "execute_actions",
                "proposed",
                f"{len(escalations)} action(s) need approval: "
                + ", ".join(
                    f"{a.tool} from {a.subtask_id}" for a in actions if a.status == "proposed"
                ),
            )
        )
    return {
        "actions": [a.model_dump(mode="json") for a in actions],
        "pending_escalations": escalations,
        "events": events,
    }


def _collect(state: dict[str, Any]) -> list[ProposedAction]:
    plan, results = load_plan(state), load_results(state)
    status = state.get("subtask_status") or {}
    unique: dict[str, ProposedAction] = {}
    for subtask in plan.subtasks:
        if status.get(subtask.id) != "done" or subtask.id not in results:
            continue
        for action in results[subtask.id].proposed_actions:
            key = f"{action.tool}:{json.dumps(action.args, sort_keys=True, default=str)}"
            unique.setdefault(key, action)
    return list(unique.values())


def _fill(value: Any, final_output: str) -> Any:
    if isinstance(value, str):
        return value.replace(FINAL_OUTPUT_TOKEN, final_output)
    if isinstance(value, dict):
        return {k: _fill(v, final_output) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, final_output) for v in value]
    return value
