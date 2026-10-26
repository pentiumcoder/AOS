from typing import Any

from aos import context
from aos.agents.prompting import render
from aos.llm import LLMError, Message, get_llm
from aos.logging import get_logger
from aos.memory.longterm import LongTermMemory
from aos.schemas import ExecutionPlan, Review, SpecialistResult
from aos.schemas.memory import MemoryExtraction, MemoryItem, StoredMemory

log = get_logger(__name__)
OUTPUT_PREVIEW = 1500


def episode(state: dict[str, Any]) -> MemoryItem:
    """The task, its plan shape and outcome, built from the run itself so it is always stored."""
    plan = ExecutionPlan.model_validate(state["plan"])
    steps = ", ".join(
        f"{s.specialist}" + (f" after {'+'.join(s.depends_on)}" if s.depends_on else "")
        for s in plan.subtasks
    )
    revisions = sum((state.get("revisions") or {}).values())
    failures = sum((state.get("failures") or {}).values())
    succeeded = bool(state.get("final_output"))
    return MemoryItem(
        kind="task_episode",
        text=(
            f"Task: {state['request']}\nPlan ({plan.task_type}): {steps}\n"
            f"Outcome: {'delivered' if succeeded else 'failed'} with {revisions} revision(s) "
            f"and {failures} failed attempt(s)"
        ),
        outcome="success" if succeeded else "failure",
        importance=0.5,
        tags=[plan.task_type],
    )


def run_record(state: dict[str, Any]) -> str:
    plan = ExecutionPlan.model_validate(state["plan"])
    results = {
        sid: SpecialistResult.model_validate(data)
        for sid, data in (state.get("results") or {}).items()
    }
    lines = [f"Request: {state['request']}", f"Plan type: {plan.task_type}", "", "Subtasks:"]
    for subtask in plan.subtasks:
        result = results.get(subtask.id)
        tools = ", ".join(result.tools_used) if result else "none"
        status = (state.get("subtask_status") or {}).get(subtask.id, "pending")
        lines.append(f"- {subtask.specialist}: {subtask.description} [{status}; tools: {tools}]")
        for raw in (state.get("reviews") or {}).get(subtask.id, []):
            review = Review.model_validate(raw)
            if not review.approved:
                lines.append(f"  rejected ({review.score:.2f}): {'; '.join(review.issues)}")
        if result and result.error:
            lines.append(f"  failed: {result.error}")
    for escalation in state.get("escalations") or []:
        lines.append(
            f"Escalation {escalation['trigger']}: {escalation.get('decision')} "
            f"({escalation.get('comment') or escalation['reason']})"
        )
    final_output = (state.get("final_output") or "")[:OUTPUT_PREVIEW]
    lines += ["", "Final deliverable:", final_output or "(none)"]
    return "\n".join(lines)


def extract(state: dict[str, Any]) -> list[MemoryItem]:
    with context.bind(agent="memory"):
        try:
            result = get_llm("memory", "low").complete(
                [Message.user(run_record(state))],
                system=render("memory_extraction"),
                schema=MemoryExtraction,
                max_tokens=2048,
                meta={"purpose": "memory_extraction", "request": state["request"]},
            )
        except LLMError as exc:
            log.warning("memory extraction failed", extra={"fields": {"error": str(exc)}})
            return []
    return [item for item in result.parsed.memories if item.kind != "task_episode"]


def remember_run(
    state: dict[str, Any], memory: LongTermMemory | None = None
) -> list[tuple[StoredMemory, bool]]:
    store = memory or LongTermMemory()
    user_id = state.get("user_id") or "default"
    items = [episode(state), *extract(state)]
    return [store.add(user_id, item, source_run_id=state["run_id"]) for item in items]
