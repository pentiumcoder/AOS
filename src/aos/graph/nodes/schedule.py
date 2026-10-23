from typing import Any

from aos.graph.helpers import load_plan
from aos.graph.instrument import traced_node
from aos.schemas import ready_subtasks
from aos.schemas.plan import TERMINAL_STATUSES
from aos.schemas.state import event


@traced_node("schedule")
def schedule(state: dict[str, Any]) -> dict[str, Any]:
    plan = load_plan(state)
    status = dict(state.get("subtask_status") or {})
    visits = dict(state.get("visits") or {})
    events = []

    ready = ready_subtasks(plan, status)
    for subtask in ready:
        status[subtask.id] = "running"
        visits[subtask.id] = visits.get(subtask.id, 0) + 1

    if ready:
        names = ", ".join(s.id for s in ready)
        mode = "in parallel" if len(ready) > 1 else "alone"
        events.append(event("schedule", "dispatch", f"dispatching {names} {mode}"))
    else:
        blocked = [sid for sid, value in status.items() if value not in TERMINAL_STATUSES]
        for sid in blocked:
            status[sid] = "failed"
        if blocked:
            events.append(
                event("schedule", "blocked", f"{', '.join(blocked)} blocked by failed dependencies")
            )

    return {"subtask_status": status, "visits": visits, "events": events}
