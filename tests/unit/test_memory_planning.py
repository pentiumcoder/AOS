import time

from aos.db.models import MemoryRetrieval
from aos.graph import create_task, execute_run
from aos.memory.longterm import LongTermMemory
from aos.memory.retrieval import PlanningContext, retrieve_for_planning
from aos.memory.scoring import decay, effective_importance, rank
from aos.schemas.memory import MemoryItem, StoredMemory

FIRST = "[test:learning] Summarise the latency of our vector databases"
SECOND = "[test:learning] Briefly summarise vector database latency"


def run(request: str) -> tuple[dict, str]:
    _, run_id = create_task(request, user_id="alice")
    return execute_run(run_id), run_id


def test_second_similar_task_plans_from_the_stored_lesson(db):
    first, _ = run(FIRST)
    assert first["plan"]["subtasks"][0]["specialist"] == "research"
    assert first["revisions"] == {"s2": 1}

    second, run_id = run(SECOND)
    plan = second["plan"]
    assert [s["specialist"] for s in plan["subtasks"]] == ["data_analysis", "writing"]
    assert second["revisions"] == {}
    assert "14.9 ms" in second["final_output"]

    [influence] = plan["memory_influence"]
    lesson = LongTermMemory().get(influence["memory_id"])
    assert lesson.kind == "approach" and lesson.outcome == "failure"
    assert lesson.access_count >= 1
    assert (
        "recalled" in next(e for e in second["events"] if e["node"] == "retrieve_memory")["message"]
    )

    used = db.query(MemoryRetrieval).filter_by(run_id=run_id, used_in_plan=True).all()
    assert [row.memory_id for row in used] == [lesson.id]


def test_planner_cannot_cite_memories_it_was_not_given():
    from aos.agents.supervisor import _ground_influence
    from aos.schemas import ExecutionPlan

    memory = stored("approach", "Use the benchmarks table", memory_id="abcdef1234567890")
    plan = ExecutionPlan(
        task_type="t",
        rationale="r",
        confidence=0.9,
        subtasks=[],
        memory_influence=[
            {"memory_id": "abcdef12", "how_used": "real"},
            {"memory_id": "ffffffff", "how_used": "invented"},
        ],
    )
    grounded = _ground_influence(plan, PlanningContext(worked=[memory]))
    assert [i.memory_id for i in grounded.memory_influence] == ["abcdef1234567890"]


def test_retrieval_separates_lessons_and_skips_other_users():
    store = LongTermMemory()
    store.add(
        "alice",
        MemoryItem(kind="approach", text="Query benchmarks table for latency", outcome="success"),
    )
    store.add(
        "alice",
        MemoryItem(kind="approach", text="Web latency figures were rejected", outcome="failure"),
    )
    store.add("bob", MemoryItem(kind="fact", text="Bob's latency benchmark notes"))
    recalled = retrieve_for_planning("alice", "latency of vector databases", store=store)
    assert [m.outcome for m in recalled.worked] == ["success"]
    assert [m.outcome for m in recalled.failed] == ["failure"]
    assert recalled.facts == []
    assert "What failed before" in recalled.render()


def stored(kind: str, text: str, *, memory_id: str = "m" * 16, **fields) -> StoredMemory:
    now = time.time()
    values = {"importance": 0.5, "access_count": 0, "last_accessed_at": now, **fields}
    return StoredMemory(
        id=memory_id, user_id="alice", kind=kind, text=text, created_at=now, **values
    )


def test_importance_grows_with_use_and_decays_with_idle_time():
    now = time.time()
    fresh = stored("fact", "some fact", importance=0.5)
    used = stored("fact", "some fact", importance=0.5, access_count=9)
    idle = stored("fact", "some fact", importance=0.5, last_accessed_at=now - 30 * 86_400)
    preference = stored(
        "preference", "some preference", importance=0.5, last_accessed_at=now - 30 * 86_400
    )

    assert effective_importance(used, now) > effective_importance(fresh, now)
    assert abs(decay(idle, now) - 0.5) < 1e-6
    assert decay(preference, now) > 0.85
    close = fresh.model_copy(update={"similarity": 0.8})
    far = fresh.model_copy(update={"similarity": 0.4})
    assert rank(close, now) > rank(far, now)
