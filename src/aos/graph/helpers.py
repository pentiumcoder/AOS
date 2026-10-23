from typing import Any

from aos.db.models import Run, Task
from aos.db.session import session_scope
from aos.schemas import ExecutionPlan, SpecialistResult, Subtask


def load_plan(state: dict[str, Any]) -> ExecutionPlan:
    return ExecutionPlan.model_validate(state["plan"])


def load_results(state: dict[str, Any]) -> dict[str, SpecialistResult]:
    return {
        sid: SpecialistResult.model_validate(data)
        for sid, data in (state.get("results") or {}).items()
    }


def dep_outputs(subtask: Subtask, results: dict[str, SpecialistResult]) -> dict[str, str]:
    return {
        dep: results[dep].output
        for dep in subtask.depends_on
        if dep in results and results[dep].status == "success"
    }


def update_run(run_id: str, **fields: Any) -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)


def update_task(task_id: str, **fields: Any) -> None:
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            return
        for key, value in fields.items():
            setattr(task, key, value)
