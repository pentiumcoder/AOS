from aos import context
from aos.agents.prompting import render, section
from aos.agents.specialists import SPECIALIST_AGENTS
from aos.llm import Message, get_llm
from aos.schemas import ExecutionPlan, SpecialistResult, validate_plan
from aos.schemas.plan import MAX_SUBTASKS, infer_dependencies
from aos.tools.registry import get_registry


class PlanningError(Exception):
    def __init__(self, message: str, errors: list[str]) -> None:
        super().__init__(message)
        self.errors = errors


def specialist_catalog() -> str:
    registry = get_registry()
    lines = []
    for name, agent in SPECIALIST_AGENTS.items():
        tools = ", ".join(d.name for d in registry.list_for(name)) or "none"
        lines.append(f"- {name}: {agent.description} Tools: {tools}.")
    return "\n".join(lines)


def plan(
    request: str, *, memory_context: str | None = None, feedback: str | None = None
) -> ExecutionPlan:
    system = render("supervisor_plan", specialists=specialist_catalog(), max_subtasks=MAX_SUBTASKS)
    prompt = (
        f"Request:\n{request}"
        + section("What you remember", memory_context)
        + section("Feedback on the previous plan", feedback)
    )
    messages = [Message.user(prompt)]
    errors: list[str] = []
    with context.bind(agent="supervisor"):
        llm = get_llm("supervisor", "high")
        for _ in range(2):
            result = llm.complete(
                messages,
                system=system,
                schema=ExecutionPlan,
                max_tokens=4096,
                meta={"purpose": "plan", "request": request},
            )
            candidate = infer_dependencies(result.parsed)
            errors = validate_plan(candidate)
            if not errors:
                return candidate
            problems = "\n".join(f"- {error}" for error in errors)
            messages += [
                Message.assistant(candidate.model_dump_json()),
                Message.user(f"The plan is invalid:\n{problems}\nReturn a corrected plan."),
            ]
    raise PlanningError("plan still invalid after re-planning", errors)


def synthesize(request: str, plan: ExecutionPlan, results: dict[str, SpecialistResult]) -> str:
    parts, outputs = [], {}
    for subtask in plan.subtasks:
        result = results.get(subtask.id)
        if result is not None and result.status == "success":
            outputs[subtask.id] = result.output
            parts.append(f"### {subtask.id}: {subtask.description}\n{result.output}")
        else:
            reason = result.error if result else "not run"
            parts.append(f"### {subtask.id}: {subtask.description}\nNOT COMPLETED: {reason}")
    with context.bind(agent="supervisor"):
        result = get_llm("supervisor", "medium").complete(
            [Message.user(f"Request:\n{request}\n\nSubtask results:\n\n" + "\n\n".join(parts))],
            system=render("supervisor_synthesize"),
            max_tokens=4096,
            meta={"purpose": "synthesize", "request": request, "outputs": outputs},
        )
    return result.text.strip()
