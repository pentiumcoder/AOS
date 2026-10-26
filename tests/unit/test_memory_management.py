import time

import pytest
from fastapi.testclient import TestClient

from aos.api.main import app
from aos.db.models import MemoryRetrieval
from aos.graph import create_task, execute_run
from aos.memory.longterm import LongTermMemory
from aos.memory.management import forget_user, maintain
from aos.schemas.memory import MemoryItem

DAY = 86_400


@pytest.fixture
def store():
    return LongTermMemory()


def add(store, kind, text, *, user="alice", idle_days=0.0, importance=0.5, dedupe=True):
    item = MemoryItem(kind=kind, text=text, importance=importance)
    memory, _ = store.add(user, item, dedupe=dedupe)
    if idle_days:
        store.update(memory.id, last_accessed_at=time.time() - idle_days * DAY)
    return memory


def test_stale_memories_expire_but_preferences_stay(store):
    stale = add(store, "fact", "Old benchmark figures from last year", idle_days=200)
    fresh = add(store, "fact", "Qdrant has the lowest p95 latency on our benchmark")
    old_preference = add(store, "preference", "Summaries under 200 words", idle_days=400)

    report = maintain("alice", store=store)
    remaining = {m.id for m in store.list_user("alice")}
    assert report.expired == 1
    assert stale.id not in remaining
    assert {fresh.id, old_preference.id} <= remaining


def test_near_duplicates_are_consolidated_and_hidden_from_search(store):
    texts = [
        "Compute benchmark figures with db_query before writing the summary",
        "Compute the benchmark figures with db_query before writing a summary",
        "Always compute benchmark figures with db_query before writing the summary",
    ]
    # Stored without dedupe, as when similar lessons accumulate across many runs.
    members = [add(store, "approach", text, dedupe=False) for text in texts]
    add(store, "approach", "Escalate when the plan confidence is low")

    report = maintain("alice", store=store)
    assert (report.consolidated_groups, report.consolidated_members) == (1, 3)

    everything = store.list_user("alice")
    [merged] = [m for m in everything if "consolidated" in m.tags]
    assert merged.text.endswith("(seen 3 times)")
    assert merged.importance == pytest.approx(0.6)
    assert all(store.get(m.id).consolidated_into == merged.id for m in members)
    hits = store.search("alice", texts[0], kinds=["approach"])
    assert merged.id in {h.id for h in hits}
    assert not {m.id for m in members} & {h.id for h in hits}


def test_maintenance_is_idempotent(store):
    for text in [
        "Use db_query for latency figures",
        "Use db_query for the latency figures",
        "Always use db_query for latency figures",
    ]:
        add(store, "tool_usage", text, dedupe=False)
    assert maintain("alice", store=store).consolidated_groups == 1
    second = maintain("alice", store=store)
    assert second.consolidated_groups == 0


def test_forget_user_removes_memories_and_retrieval_log(db):
    request = "[test:learning] Summarise the latency of our vector databases"
    for _ in range(2):
        _, run_id = create_task(request, user_id="alice")
        execute_run(run_id)
    assert db.query(MemoryRetrieval).filter_by(user_id="alice").count() > 0

    report = forget_user("alice")
    assert report["memories_deleted"] > 0
    assert LongTermMemory().list_user("alice") == []
    assert db.query(MemoryRetrieval).filter_by(user_id="alice").count() == 0


def test_memory_api(store):
    keep = add(store, "preference", "Email summaries to the team", importance=0.9)
    drop = add(store, "fact", "Milvus leads throughput at 4,200 QPS")
    add(store, "fact", "Bob prefers tables", user="bob")

    with TestClient(app) as client:
        listed = client.get("/users/alice/memories").json()
        assert [m["id"] for m in listed] == [keep.id, drop.id]
        assert listed[0]["effective_importance"] == pytest.approx(0.9, abs=0.01)
        assert client.get("/users/alice/memories", params={"kind": "nope"}).status_code == 422
        assert client.get(f"/memories/{drop.id}").json()["kind"] == "fact"

        assert client.delete(f"/memories/{drop.id}").status_code == 204
        assert client.get(f"/memories/{drop.id}").status_code == 404
        assert client.post("/memory/maintenance").json()["users"] == 2

        forgotten = client.delete("/users/alice/memories").json()
        assert forgotten["memories_deleted"] == 1
        assert client.get("/users/alice/memories").json() == []
        assert len(client.get("/users/bob/memories").json()) == 1


def test_paraphrased_lessons_consolidate_with_the_offline_embedder(store):
    lessons = [
        "For latency questions, query the internal benchmarks table with db_query instead "
        "of searching the web; web figures were rejected.",
        "Latency figures from web search were rejected by the reviewer; use db_query on the "
        "internal benchmarks table for latency questions.",
        "Answer vector database latency questions from the benchmarks table with db_query, "
        "because the reviewer rejected figures found on the web.",
    ]
    for text in lessons:
        add(store, "approach", text, dedupe=False)
    other = add(
        store,
        "approach",
        "For monthly cost questions, sort the benchmarks table by monthly_cost_usd with db_query.",
        dedupe=False,
    )
    report = maintain("alice", store=store)
    assert (report.consolidated_groups, report.consolidated_members) == (1, 3)
    assert store.get(other.id).consolidated_into is None
