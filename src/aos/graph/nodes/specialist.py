from typing import Any

from aos.agents import get_specialist
from aos.graph.instrument import traced_node
from aos.schemas import Subtask
from aos.schemas.state import event


@traced_node("run_specialist")
def run_specialist(task: dict[str, Any]) -> dict[str, Any]:
    subtask = Subtask.model_validate(task["subtask"])
    result = get_specialist(subtask.specialist).run(
        subtask,
        request=task["request"],
        dep_outputs=task["dep_outputs"],
        feedback=task.get("feedback"),
        approach_hint=task.get("approach_hint"),
        attempt=task["attempt"],
    )
    if result.status == "success":
        tools = ", ".join(result.tools_used) or "no tools"
        message = f"{subtask.id} ({subtask.specialist}) finished using {tools}"
        if result.proposed_actions:
            queued = ", ".join(a.tool for a in result.proposed_actions)
            message += f"; queued {queued} for approval"
        status = "awaiting_review"
    else:
        message = f"{subtask.id} ({subtask.specialist}) failed: {result.error}"
        status = "errored"
    return {
        "results": {subtask.id: result.model_dump(mode="json")},
        "subtask_status": {subtask.id: status},
        "events": [
            event(
                "run_specialist", "result", message, subtask_id=subtask.id, attempt=task["attempt"]
            )
        ],
    }
