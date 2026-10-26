import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field

SPECIALISTS = ("research", "data_analysis", "writing", "code")
MAX_SUBTASKS = 12

SubtaskStatus = Literal[
    "pending",
    "running",
    "awaiting_review",
    "errored",
    "needs_revision",
    "retry",
    "escalate",
    "done",
    "failed",
]
READY_STATUSES = {"pending", "needs_revision", "retry"}
TERMINAL_STATUSES = {"done", "failed"}


class Subtask(BaseModel):
    id: str = Field(description="Short unique id such as s1")
    description: str
    specialist: str = Field(description=f"One of: {', '.join(SPECIALISTS)}")
    depends_on: list[str] = Field(default_factory=list)
    inputs: dict[str, str] = Field(
        default_factory=dict,
        description="Named inputs: literal values or subtask:<id> references",
    )
    expected_output: str = Field(description="Format and content the result must have")
    complexity: Literal["low", "medium", "high"] = "medium"
    actions: list[str] = Field(
        default_factory=list,
        description="Side-effect tools such as send_email, only if the user asked for them",
    )
    approach_hint: str | None = None


class MemoryInfluence(BaseModel):
    memory_id: str
    how_used: str


class ExecutionPlan(BaseModel):
    task_type: str = Field(description="Short snake_case label, e.g. research_report")
    rationale: str
    confidence: float = Field(ge=0, le=1, description="How likely this plan fully solves the task")
    subtasks: list[Subtask]
    memory_influence: list[MemoryInfluence] = Field(default_factory=list)

    def subtask(self, subtask_id: str) -> Subtask:
        for item in self.subtasks:
            if item.id == subtask_id:
                return item
        raise KeyError(subtask_id)


def infer_dependencies(plan: ExecutionPlan) -> ExecutionPlan:
    """Add dependencies the planner implied but left out of depends_on.

    A subtask depends on any subtask its description or inputs name. A writing subtask
    with no dependencies at all writes up the other subtasks' findings, so it depends on
    every non-writing subtask that does not itself wait for it.
    """
    ids = {s.id for s in plan.subtasks if any(ch.isdigit() for ch in s.id)}
    fixed = plan.model_copy(deep=True)
    for subtask in fixed.subtasks:
        text = " ".join([subtask.description, *subtask.inputs.values()])
        named = {token for token in re.findall(r"[\w-]+", text) if token in ids}
        missing = sorted(named - set(subtask.depends_on) - {subtask.id})
        subtask.depends_on = [*subtask.depends_on, *missing]
    for subtask in fixed.subtasks:
        if subtask.specialist == "writing" and not subtask.depends_on:
            subtask.depends_on = [
                other.id
                for other in fixed.subtasks
                if other.specialist != "writing" and subtask.id not in other.depends_on
            ]
    return fixed


def validate_plan(plan: ExecutionPlan) -> list[str]:
    errors: list[str] = []
    if not plan.subtasks:
        return ["plan has no subtasks"]
    if len(plan.subtasks) > MAX_SUBTASKS:
        errors.append(f"plan has {len(plan.subtasks)} subtasks; the limit is {MAX_SUBTASKS}")

    ids = [s.id for s in plan.subtasks]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        errors.append(f"duplicate subtask ids: {', '.join(duplicates)}")

    known = set(ids)
    for subtask in plan.subtasks:
        if subtask.specialist not in SPECIALISTS:
            errors.append(f"{subtask.id} uses unknown specialist {subtask.specialist}")
        for dep in subtask.depends_on:
            if dep == subtask.id:
                errors.append(f"{subtask.id} depends on itself")
            elif dep not in known:
                errors.append(f"{subtask.id} depends on unknown subtask {dep}")

    cycle = _find_cycle({s.id: [d for d in s.depends_on if d in known] for s in plan.subtasks})
    if cycle:
        errors.append(f"plan has cycle: {' -> '.join(cycle)}")
    return errors


def _find_cycle(graph: Mapping[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for dep in graph.get(node, []):
            if dep == node:
                continue
            if state.get(dep) == 1:
                return [*stack[stack.index(dep) :], dep]
            if state.get(dep) is None and (found := visit(dep)):
                return found
        stack.pop()
        state[node] = 2
        return None

    for node in graph:
        if state.get(node) is None and (found := visit(node)):
            return found
    return None


def ready_subtasks(plan: ExecutionPlan, status: Mapping[str, str]) -> list[Subtask]:
    return [
        s
        for s in plan.subtasks
        if status.get(s.id, "pending") in READY_STATUSES
        and all(status.get(dep) == "done" for dep in s.depends_on)
    ]
