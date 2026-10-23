from typing import Any

from aos.graph.helpers import update_run, update_task
from aos.graph.instrument import traced_node
from aos.schemas.state import event


@traced_node("intake")
def intake(state: dict[str, Any]) -> dict[str, Any]:
    request = " ".join(state["request"].split())
    update_run(state["run_id"], status="running")
    update_task(state["task_id"], status="running")
    return {
        "request": request,
        "events": [event("intake", "start", f"run started for user {state.get('user_id')}")],
    }
