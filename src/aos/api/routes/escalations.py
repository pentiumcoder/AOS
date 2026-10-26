from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from aos.config import get_settings
from aos.graph.runner import resume_run
from aos.hitl import chat
from aos.hitl.levels import ALLOWED_DECISIONS, ApprovalLevel
from aos.hitl.queue import DecisionError, get_escalation, list_escalations, record_decision
from aos.logging import get_logger
from aos.schemas.escalation import HumanDecision

log = get_logger(__name__)
router = APIRouter(prefix="/escalations", tags=["escalations"])


class EscalationSummary(BaseModel):
    id: str
    run_id: str
    task_id: str
    level: str
    trigger: str
    origin: str
    reason: str
    status: str
    subtask_id: str | None
    action_id: str | None
    allowed_decisions: list[str]
    created_at: datetime
    decided_at: datetime | None
    review_seconds: float | None


class EscalationDetail(EscalationSummary):
    context: dict[str, Any]
    proposed_action: dict[str, Any] | None
    decision: dict[str, Any] | None
    decided_by: str | None
    chat: list[dict[str, str]]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatReply(BaseModel):
    answer: str
    chat: list[dict[str, str]]


@router.get("", response_model=list[EscalationSummary])
def list_queue(
    status: str | None = "pending", run_id: str | None = None, task_id: str | None = None
) -> list[EscalationSummary]:
    rows = list_escalations(status=status or None, run_id=run_id, task_id=task_id)
    return [EscalationSummary(**_with_allowed(row)) for row in rows]


@router.get("/{escalation_id}", response_model=EscalationDetail)
def get_detail(escalation_id: str) -> EscalationDetail:
    row = get_escalation(escalation_id)
    if row is None:
        raise HTTPException(404, "escalation not found")
    return EscalationDetail(**_with_allowed(row))


@router.post("/{escalation_id}/decision", response_model=EscalationDetail)
def decide(
    escalation_id: str, decision: HumanDecision, background: BackgroundTasks
) -> EscalationDetail:
    try:
        row = record_decision(escalation_id, decision)
    except KeyError as exc:
        raise HTTPException(404, "escalation not found") from exc
    except DecisionError as exc:
        raise HTTPException(409, str(exc)) from exc

    payload = decision.model_dump(mode="json")
    if get_settings().task_execution == "inline":
        background.add_task(_resume_inline, row["run_id"], payload)
    else:
        from aos.worker.tasks import resume_run as resume_task

        resume_task.delay(row["run_id"], payload)
    return EscalationDetail(**_with_allowed(row))


@router.post("/{escalation_id}/chat", response_model=ChatReply)
def ask(escalation_id: str, body: ChatRequest) -> ChatReply:
    try:
        return ChatReply(**chat.answer(escalation_id, body.message))
    except KeyError as exc:
        raise HTTPException(404, "escalation not found") from exc


def _resume_inline(run_id: str, decision: dict[str, Any]) -> None:
    try:
        resume_run(run_id, decision)
    except Exception:
        log.exception("inline resume failed")


def _with_allowed(row: dict[str, Any]) -> dict[str, Any]:
    level = ApprovalLevel(row["level"])
    return {**row, "allowed_decisions": sorted(ALLOWED_DECISIONS[level])}
