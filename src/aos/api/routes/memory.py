from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from aos.memory.longterm import LongTermMemory
from aos.memory.management import MaintenanceReport, forget_user, maintain
from aos.memory.scoring import effective_importance
from aos.schemas.memory import MEMORY_KINDS, StoredMemory

router = APIRouter(tags=["memory"])


class MemoryView(BaseModel):
    id: str
    user_id: str
    kind: str
    text: str
    outcome: str
    tags: list[str]
    importance: float
    effective_importance: float
    access_count: int
    created_at: datetime
    last_accessed_at: datetime
    source_run_id: str | None
    consolidated_into: str | None


class ForgetReport(BaseModel):
    memories_deleted: int
    retrievals_deleted: int


@router.get("/users/{user_id}/memories", response_model=list[MemoryView])
def list_memories(
    user_id: str,
    kind: str | None = None,
    sort: Literal["importance", "recent"] = "importance",
    include_consolidated: bool = True,
) -> list[MemoryView]:
    if kind is not None and kind not in MEMORY_KINDS:
        raise HTTPException(422, f"kind must be one of: {', '.join(MEMORY_KINDS)}")
    views = [_view(m) for m in LongTermMemory().list_user(user_id, kind)]
    if not include_consolidated:
        views = [v for v in views if v.consolidated_into is None]
    if sort == "recent":
        return sorted(views, key=lambda v: v.last_accessed_at, reverse=True)
    return sorted(views, key=lambda v: v.effective_importance, reverse=True)


@router.get("/memories/{memory_id}", response_model=MemoryView)
def get_memory(memory_id: str) -> MemoryView:
    memory = LongTermMemory().get(memory_id)
    if memory is None:
        raise HTTPException(404, "memory not found")
    return _view(memory)


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: str) -> Response:
    store = LongTermMemory()
    if store.get(memory_id) is None:
        raise HTTPException(404, "memory not found")
    store.delete([memory_id])
    return Response(status_code=204)


@router.delete("/users/{user_id}/memories", response_model=ForgetReport)
def forget(user_id: str) -> ForgetReport:
    return ForgetReport(**forget_user(user_id))


@router.post("/memory/maintenance", response_model=MaintenanceReport)
def run_maintenance(user_id: str | None = Query(default=None)) -> MaintenanceReport:
    return maintain(user_id)


def _view(memory: StoredMemory) -> MemoryView:
    return MemoryView(
        id=memory.id,
        user_id=memory.user_id,
        kind=memory.kind,
        text=memory.text,
        outcome=memory.outcome,
        tags=memory.tags,
        importance=memory.importance,
        effective_importance=round(effective_importance(memory), 4),
        access_count=memory.access_count,
        created_at=datetime.fromtimestamp(memory.created_at, UTC),
        last_accessed_at=datetime.fromtimestamp(memory.last_accessed_at, UTC),
        source_run_id=memory.source_run_id,
        consolidated_into=memory.consolidated_into,
    )
