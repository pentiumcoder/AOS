from typing import Any

from aos.agents import PlanningError, supervisor
from aos.graph.helpers import update_run
from aos.graph.instrument import traced_node
from aos.graph.routing import plan_escalation
from aos.llm import LLMError
from aos.memory import WorkingMemory
from aos.memory.retrieval import PlanningContext, mark_used
from aos.schemas.state import event


@traced_node("plan")
def plan_node(state: dict[str, Any]) -> dict[str, Any]:
    recalled = state.get("memory_context")
    try:
        plan = supervisor.plan(
            state["request"],
            memory=PlanningContext.model_validate(recalled) if recalled else None,
            feedback=state.get("plan_feedback"),
        )
    except (PlanningError, LLMError) as exc:
        errors = exc.errors if isinstance(exc, PlanningError) else [str(exc)]
        return {
            "plan": None,
            "plan_errors": errors,
            "error": f"planning failed: {'; '.join(errors)}",
            "events": [event("plan", "error", f"planning failed: {'; '.join(errors)}")],
        }

    update_run(state["run_id"], plan=plan.model_dump(mode="json"), task_type=plan.task_type)
    mark_used(state["run_id"], [influence.memory_id for influence in plan.memory_influence])
    memory = WorkingMemory(state["run_id"])
    memory.set_plan(plan.model_dump(mode="json"))
    escalation = plan_escalation(plan)
    summary = ", ".join(
        f"{s.id}<-{'+'.join(s.depends_on)}" if s.depends_on else s.id for s in plan.subtasks
    )
    message = f"{len(plan.subtasks)} subtasks ({summary}), confidence {plan.confidence:.2f}"
    if plan.memory_influence:
        message += f", shaped by {len(plan.memory_influence)} memories"
    return {
        "plan": plan.model_dump(mode="json"),
        "plan_errors": [],
        "working_memory_ref": memory.prefix,
        "subtask_status": {s.id: "pending" for s in plan.subtasks},
        "pending_escalations": [escalation] if escalation else [],
        "events": [event("plan", "plan", message, task_type=plan.task_type)],
    }
