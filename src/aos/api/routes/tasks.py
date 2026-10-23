from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from aos.config import get_settings
from aos.db.models import Run, Task, ToolCall, utcnow
from aos.db.session import session_scope
from aos.graph.runner import create_task, execute_run, run_state
from aos.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    request: str = Field(min_length=1, max_length=10_000)
    user_id: str = Field(default="default", min_length=1, max_length=128)
    require_human_review: bool = False


class TaskAccepted(BaseModel):
    task_id: str
    run_id: str
    status: str


class TaskSummary(BaseModel):
    id: str
    user_id: str
    request: str
    status: str
    created_at: datetime
    completed_at: datetime | None


class SubtaskView(BaseModel):
    id: str
    description: str
    specialist: str
    depends_on: list[str]
    status: str
    attempts: int
    output: str | None
    error: str | None
    reviews: list[dict[str, Any]]


class RunView(BaseModel):
    id: str
    status: str
    task_type: str | None
    error: str | None
    started_at: datetime
    ended_at: datetime | None
    plan: dict[str, Any] | None
    subtasks: list[SubtaskView]
    actions: list[dict[str, Any]]
    escalations: list[dict[str, Any]]
    events: list[dict[str, Any]]


class TaskDetail(TaskSummary):
    require_human_review: bool
    final_output: str | None
    run: RunView | None


class ToolCallView(BaseModel):
    id: str
    subtask_id: str | None
    agent: str
    tool: str
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    success: bool
    error: str | None
    latency_ms: float
    created_at: datetime


@router.post("", status_code=202, response_model=TaskAccepted)
def submit_task(body: TaskCreate, background: BackgroundTasks) -> TaskAccepted:
    task_id, run_id = create_task(body.request, body.user_id, body.require_human_review)
    if get_settings().task_execution == "inline":
        background.add_task(_run_inline, run_id)
    else:
        from aos.worker.tasks import run_task

        try:
            run_task.delay(run_id)
        except Exception as exc:
            log.exception("could not enqueue run")
            _mark_failed(task_id, run_id, f"could not enqueue run: {exc}")
            raise HTTPException(503, "task queue unavailable") from exc
    return TaskAccepted(task_id=task_id, run_id=run_id, status="queued")


@router.get("", response_model=list[TaskSummary])
def list_tasks(
    user_id: str | None = None, limit: int = Query(default=20, ge=1, le=200)
) -> list[TaskSummary]:
    with session_scope() as session:
        query = select(Task).order_by(Task.created_at.desc()).limit(limit)
        if user_id:
            query = query.where(Task.user_id == user_id)
        return [_summary(task) for task in session.scalars(query)]


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(task_id: str) -> TaskDetail:
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(404, "task not found")
        run = task.runs[-1] if task.runs else None
        return TaskDetail(
            **_summary(task).model_dump(),
            require_human_review=task.require_human_review,
            final_output=task.final_output,
            run=_run_view(run) if run else None,
        )


@router.get("/{task_id}/tool-calls", response_model=list[ToolCallView])
def get_tool_calls(task_id: str) -> list[ToolCallView]:
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(404, "task not found")
        run_ids = [run.id for run in task.runs]
        calls = session.scalars(
            select(ToolCall).where(ToolCall.run_id.in_(run_ids)).order_by(ToolCall.created_at)
        )
        return [ToolCallView.model_validate(call, from_attributes=True) for call in calls]


def _run_inline(run_id: str) -> None:
    try:
        execute_run(run_id)
    except Exception:
        log.exception("inline run failed")


def _mark_failed(task_id: str, run_id: str, error: str) -> None:
    with session_scope() as session:
        run = session.get(Run, run_id)
        run.status, run.error, run.ended_at = "failed", error, utcnow()
        task = session.get(Task, task_id)
        task.status, task.completed_at = "failed", utcnow()


def _summary(task: Task) -> TaskSummary:
    return TaskSummary(
        id=task.id,
        user_id=task.user_id,
        request=task.request,
        status=task.status,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )


def _run_view(run: Run) -> RunView:
    state = run_state(run.thread_id) if run.status != "queued" else {}
    plan = state.get("plan") or run.plan
    status = state.get("subtask_status") or {}
    results = state.get("results") or {}
    reviews = state.get("reviews") or {}
    visits = state.get("visits") or {}
    subtasks = [
        SubtaskView(
            id=s["id"],
            description=s["description"],
            specialist=s["specialist"],
            depends_on=s.get("depends_on", []),
            status=status.get(s["id"], "pending"),
            attempts=visits.get(s["id"], 0),
            output=(results.get(s["id"]) or {}).get("output"),
            error=(results.get(s["id"]) or {}).get("error"),
            reviews=reviews.get(s["id"], []),
        )
        for s in (plan or {}).get("subtasks", [])
    ]
    return RunView(
        id=run.id,
        status=run.status,
        task_type=run.task_type,
        error=run.error,
        started_at=run.started_at,
        ended_at=run.ended_at,
        plan=plan,
        subtasks=subtasks,
        actions=state.get("actions") or [],
        escalations=state.get("escalations") or [],
        events=state.get("events") or [],
    )
