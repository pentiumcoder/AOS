from typing import Any

from aos.graph.runner import execute_run, is_paused
from aos.graph.runner import resume_run as resume_graph
from aos.worker.celery_app import celery_app


def _outcome(final: dict[str, Any]) -> str:
    if is_paused(final):
        return "awaiting_human"
    return "completed" if final.get("final_output") else "failed"


@celery_app.task(name="aos.run_task")
def run_task(run_id: str) -> str:
    return _outcome(execute_run(run_id))


@celery_app.task(name="aos.resume_run")
def resume_run(run_id: str, decision: dict[str, Any]) -> str:
    return _outcome(resume_graph(run_id, decision))


@celery_app.task(name="aos.memory_maintenance")
def memory_maintenance() -> dict[str, int]:
    from aos.memory.management import maintain

    return maintain().model_dump()
