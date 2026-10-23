from typing import Any

from aos.agents import supervisor
from aos.graph.helpers import load_plan, load_results
from aos.graph.instrument import traced_node
from aos.graph.routing import final_escalation
from aos.schemas.state import event


@traced_node("synthesize")
def synthesize(state: dict[str, Any]) -> dict[str, Any]:
    plan = load_plan(state)
    status = state.get("subtask_status") or {}
    results = {
        sid: result for sid, result in load_results(state).items() if status.get(sid) == "done"
    }
    final_output = supervisor.synthesize(state["request"], plan, results)
    escalation = final_escalation(state)
    missing = [s.id for s in plan.subtasks if s.id not in results]
    message = f"deliverable ready ({len(final_output)} chars)"
    if missing:
        message += f"; missing {', '.join(missing)}"
    return {
        "final_output": final_output,
        "pending_escalations": [escalation] if escalation else [],
        "events": [event("synthesize", "deliverable", message)],
    }
