from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from aos.config import get_settings
from aos.logging import get_logger
from aos.replay.compare import compare
from aos.replay.engine import list_steps, prepare_replay, run_replay

log = get_logger(__name__)
router = APIRouter(tags=["replay"])


class ReplayRequest(BaseModel):
    mode: Literal["recorded", "live"] = "recorded"
    overrides: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Recorded model call id -> replacement response {text, parsed, tool_calls}",
    )
    request: str | None = Field(default=None, description="Replace the task request")


class ReplayAccepted(BaseModel):
    task_id: str
    run_id: str
    parent_run_id: str


@router.get("/runs/{run_id}/steps")
def steps(run_id: str) -> list[dict[str, Any]]:
    return list_steps(run_id)


@router.post("/runs/{run_id}/replay", status_code=202, response_model=ReplayAccepted)
def start(run_id: str, body: ReplayRequest, background: BackgroundTasks) -> ReplayAccepted:
    try:
        task_id, new_run_id = prepare_replay(run_id, body.request)
    except KeyError as exc:
        raise HTTPException(404, "run not found") from exc
    if get_settings().task_execution == "inline":
        background.add_task(_run_inline, new_run_id, run_id, body.mode, body.overrides)
    else:
        from aos.worker.tasks import replay_run

        replay_run.delay(new_run_id, run_id, body.mode, body.overrides)
    return ReplayAccepted(task_id=task_id, run_id=new_run_id, parent_run_id=run_id)


@router.get("/runs/{run_a}/compare/{run_b}")
def compare_runs(run_a: str, run_b: str) -> dict[str, Any]:
    try:
        return compare(run_a, run_b)
    except KeyError as exc:
        raise HTTPException(404, "run not found") from exc


def _run_inline(run_id: str, parent: str, mode: str, overrides: dict[str, Any]) -> None:
    try:
        run_replay(run_id, parent, mode, overrides)
    except Exception:
        log.exception("inline replay failed")
