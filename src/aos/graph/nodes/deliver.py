from typing import Any

from aos.db.models import utcnow
from aos.graph.helpers import update_run, update_task
from aos.graph.instrument import traced_node
from aos.memory import WorkingMemory
from aos.schemas.state import event


@traced_node("deliver")
def deliver(state: dict[str, Any]) -> dict[str, Any]:
    final_output = state.get("final_output")
    status = "completed" if final_output else "failed"
    error = None if final_output else (state.get("error") or "no deliverable was produced")
    memory = WorkingMemory(state["run_id"])
    snapshot = memory.snapshot()
    now = utcnow()
    update_run(state["run_id"], status=status, error=error, ended_at=now, wm_snapshot=snapshot)
    update_task(state["task_id"], status=status, final_output=final_output, completed_at=now)
    memory.clear()
    return {"error": error, "events": [event("deliver", status, f"run {status}")]}
