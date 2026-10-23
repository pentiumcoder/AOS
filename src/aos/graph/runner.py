from typing import Any

from aos.config import get_settings
from aos.db.models import Run, Task, new_id, utcnow
from aos.db.session import session_scope
from aos.graph.builder import get_graph
from aos.graph.helpers import update_run, update_task
from aos.logging import get_logger
from aos.schemas.state import TaskState

log = get_logger(__name__)


def create_task(
    request: str, user_id: str = "default", require_human_review: bool = False
) -> tuple[str, str]:
    with session_scope() as session:
        task = Task(user_id=user_id, request=request, require_human_review=require_human_review)
        session.add(task)
        session.flush()
        run_id = new_id()
        session.add(Run(id=run_id, task_id=task.id, thread_id=run_id, status="queued"))
        return task.id, run_id


def run_config(thread_id: str) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": get_settings().graph_recursion_limit,
    }


def initial_state(task: Task, run: Run) -> TaskState:
    return {
        "task_id": task.id,
        "run_id": run.id,
        "user_id": task.user_id,
        "request": task.request,
        "require_human_review": task.require_human_review,
        "memory_context": None,
        "working_memory_ref": None,
        "plan": None,
        "plan_errors": [],
        "plan_feedback": None,
        "subtask_status": {},
        "results": {},
        "reviews": {},
        "visits": {},
        "failures": {},
        "revisions": {},
        "feedback": {},
        "approach_hints": {},
        "actions": None,
        "pending_escalations": [],
        "escalations": [],
        "resume_at": None,
        "final_output": None,
        "error": None,
        "events": [],
    }


def execute_run(run_id: str) -> dict[str, Any]:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise KeyError(f"unknown run: {run_id}")
        task = run.task
        state = initial_state(task, run)
        thread_id, task_id = run.thread_id, task.id
    try:
        return get_graph().invoke(state, run_config(thread_id))
    except Exception as exc:
        log.exception("run crashed", extra={"fields": {"run_id": run_id}})
        error = f"{type(exc).__name__}: {exc}"
        update_run(run_id, status="failed", error=error, ended_at=utcnow())
        update_task(task_id, status="failed", completed_at=utcnow())
        raise


def run_state(thread_id: str) -> dict[str, Any]:
    snapshot = get_graph().get_state(run_config(thread_id))
    return dict(snapshot.values or {})
