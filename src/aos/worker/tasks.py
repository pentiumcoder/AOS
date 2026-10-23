from typing import Any

from aos.graph.runner import execute_run
from aos.worker.celery_app import celery_app


@celery_app.task(name="aos.run_task")
def run_task(run_id: str) -> str:
    final = execute_run(run_id)
    return "completed" if final.get("final_output") else "failed"


@celery_app.task(name="aos.resume_run")
def resume_run(run_id: str, decision: dict[str, Any]) -> str:
    raise NotImplementedError("resuming a paused run requires the approval queue")
