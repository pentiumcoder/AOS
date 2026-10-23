from typing import Any

from aos.agents import PlanningError, supervisor
from aos.graph.helpers import update_run
from aos.graph.instrument import traced_node
from aos.graph.routing import plan_escalation
from aos.llm import LLMError
from aos.schemas.state import event


@traced_node("plan")
def plan_node(state: dict[str, Any]) -> dict[str, Any]:
    try:
        plan = supervisor.plan(
            state["request"],
            memory_context=_memory_text(state.get("memory_context")),
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
    escalation = plan_escalation(plan)
    summary = ", ".join(
        f"{s.id}<-{'+'.join(s.depends_on)}" if s.depends_on else s.id for s in plan.subtasks
    )
    return {
        "plan": plan.model_dump(mode="json"),
        "plan_errors": [],
        "subtask_status": {s.id: "pending" for s in plan.subtasks},
        "pending_escalations": [escalation] if escalation else [],
        "events": [
            event(
                "plan",
                "plan",
                f"{len(plan.subtasks)} subtasks ({summary}), confidence {plan.confidence:.2f}",
                task_type=plan.task_type,
            )
        ],
    }


def _memory_text(memory_context: Any) -> str | None:
    if not memory_context:
        return None
    return memory_context if isinstance(memory_context, str) else str(memory_context)
