import time

from pydantic import BaseModel, Field

from aos.config import get_settings
from aos.db.models import MemoryRetrieval
from aos.db.session import session_scope
from aos.memory.longterm import LongTermMemory
from aos.memory.scoring import rank
from aos.schemas.memory import StoredMemory

SHORT_ID = 8
SECTIONS = (
    ("similar_tasks", "Similar past tasks"),
    ("worked", "What worked before"),
    ("failed", "What failed before"),
    ("preferences", "User preferences"),
    ("facts", "Known facts"),
    ("decisions", "Past human decisions"),
)
GROUPS = {
    "similar_tasks": ["task_episode"],
    "worked": ["approach", "tool_usage"],
    "failed": ["approach"],
    "preferences": ["preference"],
    "facts": ["fact"],
    "decisions": ["human_decision"],
}


class PlanningContext(BaseModel):
    similar_tasks: list[StoredMemory] = Field(default_factory=list)
    worked: list[StoredMemory] = Field(default_factory=list)
    failed: list[StoredMemory] = Field(default_factory=list)
    preferences: list[StoredMemory] = Field(default_factory=list)
    facts: list[StoredMemory] = Field(default_factory=list)
    decisions: list[StoredMemory] = Field(default_factory=list)

    def memories(self) -> list[StoredMemory]:
        return [m for field, _ in SECTIONS for m in getattr(self, field)]

    def is_empty(self) -> bool:
        return not self.memories()

    def resolve(self, memory_id: str) -> StoredMemory | None:
        """Match a full id or the short id shown to the planner."""
        wanted = memory_id.strip().strip("[]").lower()
        if len(wanted) < SHORT_ID:
            return None
        return next((m for m in self.memories() if m.id.startswith(wanted)), None)

    def render(self) -> str:
        parts = []
        for field, title in SECTIONS:
            memories = getattr(self, field)
            if memories:
                lines = "\n".join(f"- [{m.id[:SHORT_ID]}] {m.text}" for m in memories)
                parts.append(f"{title}:\n{lines}")
        parts.append(
            "Apply these where they fit this request. List each one you rely on in "
            "memory_influence, using the id in brackets."
        )
        return "\n\n".join(parts)

    def ids_by_kind(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for memory in self.memories():
            grouped.setdefault(memory.kind, []).append(memory.id[:SHORT_ID])
        return grouped


def retrieve_for_planning(
    user_id: str,
    request: str,
    *,
    run_id: str | None = None,
    store: LongTermMemory | None = None,
) -> PlanningContext:
    settings = get_settings()
    store = store or LongTermMemory()
    now = time.time()
    seen: set[str] = set()
    context = PlanningContext()
    for field, _ in SECTIONS:
        minimum = store.min_similarity
        if field == "preferences":
            # Preferences apply across tasks, so a loose topical match is enough.
            minimum /= 2
        found = store.search(
            user_id, request, kinds=GROUPS[field], k=settings.memory_top_k, min_similarity=minimum
        )
        if field == "worked":
            found = [m for m in found if m.outcome != "failure"]
        elif field == "failed":
            found = [m for m in found if m.outcome == "failure"]
        chosen = [m for m in sorted(found, key=lambda m: rank(m, now), reverse=True)]
        chosen = [m for m in chosen if m.id not in seen]
        seen.update(m.id for m in chosen)
        setattr(context, field, chosen)

    recalled = context.memories()
    if recalled:
        store.touch([m.id for m in recalled])
        _log_retrievals(user_id, run_id, request, recalled)
    return context


def mark_used(run_id: str, memory_ids: list[str]) -> None:
    if not memory_ids:
        return
    with session_scope() as session:
        rows = session.query(MemoryRetrieval).filter(
            MemoryRetrieval.run_id == run_id, MemoryRetrieval.memory_id.in_(memory_ids)
        )
        for row in rows:
            row.used_in_plan = True


def _log_retrievals(
    user_id: str, run_id: str | None, request: str, memories: list[StoredMemory]
) -> None:
    with session_scope() as session:
        session.add_all(
            MemoryRetrieval(
                run_id=run_id,
                user_id=user_id,
                memory_id=memory.id,
                kind=memory.kind,
                query=request,
                score=memory.similarity or 0.0,
            )
            for memory in memories
        )
