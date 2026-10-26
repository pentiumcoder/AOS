import time
from typing import Any

from pydantic import BaseModel, Field

from aos import context
from aos.config import get_settings
from aos.db.models import MemoryRetrieval
from aos.db.session import session_scope
from aos.llm import LLMError, Message, get_llm
from aos.logging import get_logger
from aos.memory.longterm import LongTermMemory
from aos.memory.scoring import effective_importance
from aos.schemas.memory import MemoryItem, StoredMemory

log = get_logger(__name__)

NEVER_EXPIRE = {"preference"}
NOT_CONSOLIDATED = {"task_episode"}
MIN_CLUSTER = 3
CONSOLIDATION_PROMPT = (
    "These memories say nearly the same thing. Merge them into one or two self-contained "
    "sentences that keep every distinct fact, figure and condition."
)


class Consolidated(BaseModel):
    text: str = Field(min_length=3)


class MaintenanceReport(BaseModel):
    users: int = 0
    expired: int = 0
    consolidated_groups: int = 0
    consolidated_members: int = 0
    remaining: int = 0


def maintain(user_id: str | None = None, store: LongTermMemory | None = None) -> MaintenanceReport:
    store = store or LongTermMemory()
    users = [user_id] if user_id else store.user_ids()
    report = MaintenanceReport(users=len(users))
    now = time.time()
    for user in users:
        report.expired += _expire(store, user, now)
        groups, members = _consolidate(store, user)
        report.consolidated_groups += groups
        report.consolidated_members += members
        report.remaining += len(store.list_user(user))
    log.info("memory maintenance finished", extra={"fields": report.model_dump()})
    return report


def forget_user(user_id: str, store: LongTermMemory | None = None) -> dict[str, int]:
    deleted = (store or LongTermMemory()).delete_user(user_id)
    with session_scope() as session:
        retrievals = session.query(MemoryRetrieval).filter_by(user_id=user_id).delete()
    return {"memories_deleted": deleted, "retrievals_deleted": retrievals}


def _expire(store: LongTermMemory, user_id: str, now: float) -> int:
    threshold = get_settings().memory_expire_below
    stale = [
        m.id
        for m in store.list_user(user_id)
        if m.kind not in NEVER_EXPIRE and effective_importance(m, now) < threshold
    ]
    store.delete(stale)
    return len(stale)


def _consolidate(store: LongTermMemory, user_id: str) -> tuple[int, int]:
    threshold = store.consolidate_similarity
    active = [
        m
        for m in store.list_user(user_id)
        if not m.consolidated_into and m.kind not in NOT_CONSOLIDATED
    ]
    vectors = store.vectors([m.id for m in active])
    groups = members = 0
    for kind in sorted({m.kind for m in active}):
        pool = sorted(
            (m for m in active if m.kind == kind), key=lambda m: m.importance, reverse=True
        )
        assigned: set[str] = set()
        for seed in pool:
            if seed.id in assigned:
                continue
            cluster = [
                m
                for m in pool
                if m.id not in assigned and _cosine(vectors[seed.id], vectors[m.id]) >= threshold
            ]
            if len(cluster) < MIN_CLUSTER:
                continue
            merged = _merge(store, user_id, cluster)
            for member in cluster:
                store.update(member.id, consolidated_into=merged.id)
                assigned.add(member.id)
            groups += 1
            members += len(cluster)
    return groups, members


def _merge(store: LongTermMemory, user_id: str, cluster: list[StoredMemory]) -> StoredMemory:
    outcomes = [m.outcome for m in cluster]
    item = MemoryItem(
        kind=cluster[0].kind,
        text=_summarise(cluster),
        outcome=max(set(outcomes), key=outcomes.count),
        importance=min(1.0, max(m.importance for m in cluster) + 0.1),
        tags=sorted({tag for m in cluster for tag in m.tags} | {"consolidated"}),
    )
    memory, _ = store.add(user_id, item, dedupe=False)
    return memory


def _summarise(cluster: list[StoredMemory]) -> str:
    texts = [m.text for m in cluster]
    listing = "\n".join(f"- {text}" for text in texts)
    meta: dict[str, Any] = {"purpose": "memory_consolidation", "texts": texts}
    with context.bind(agent="memory"):
        try:
            result = get_llm("memory", "low").complete(
                [Message.user(listing)],
                system=CONSOLIDATION_PROMPT,
                schema=Consolidated,
                max_tokens=512,
                meta=meta,
            )
            return result.parsed.text
        except LLMError as exc:
            log.warning("consolidation summary failed", extra={"fields": {"error": str(exc)}})
            return texts[0]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return dot / norm if norm else 0.0
