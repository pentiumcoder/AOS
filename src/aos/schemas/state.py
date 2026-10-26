from operator import add
from typing import Annotated, Any, TypedDict


def merge(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class TaskState(TypedDict, total=False):
    """Graph state. Values are plain JSON so checkpoints stay portable across processes."""

    task_id: str
    run_id: str
    user_id: str
    request: str
    require_human_review: bool

    memory_context: dict[str, Any] | None
    working_memory_ref: str | None

    plan: dict[str, Any] | None
    plan_errors: list[str]
    plan_feedback: str | None

    subtask_status: Annotated[dict[str, str], merge]
    results: Annotated[dict[str, dict[str, Any]], merge]
    reviews: Annotated[dict[str, list[dict[str, Any]]], merge]
    visits: Annotated[dict[str, int], merge]
    failures: Annotated[dict[str, int], merge]
    revisions: Annotated[dict[str, int], merge]
    feedback: Annotated[dict[str, str], merge]
    approach_hints: Annotated[dict[str, str], merge]

    actions: list[dict[str, Any]] | None
    pending_escalations: list[dict[str, Any]]
    escalations: Annotated[list[dict[str, Any]], add]
    resume_at: str | None

    final_output: str | None
    error: str | None
    events: Annotated[list[dict[str, Any]], add]


class SpecialistTask(TypedDict):
    """Payload sent to one parallel run_specialist branch."""

    task_id: str
    run_id: str
    request: str
    subtask: dict[str, Any]
    attempt: int
    feedback: str | None
    approach_hint: str | None


def event(node: str, kind: str, message: str, **fields: Any) -> dict[str, Any]:
    return {"node": node, "kind": kind, "message": message, **fields}
