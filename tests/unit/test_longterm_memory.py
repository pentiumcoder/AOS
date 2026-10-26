from aos.graph.runner import create_task, run_to_completion
from aos.memory.embeddings import HashEmbedder
from aos.memory.longterm import LongTermMemory
from aos.schemas.escalation import HumanDecision
from aos.schemas.memory import MemoryItem

VECTOR_REQUEST = (
    "Research the top 3 open-source vector databases, compare them using our benchmark "
    "data, write an executive summary and email it to the team"
)


def approve(escalation: dict) -> HumanDecision:
    return HumanDecision(action="approve", comment="send it")


def run(request: str, user: str = "alice") -> tuple[dict, str]:
    _, run_id = create_task(request, user_id=user)
    return run_to_completion(run_id, approve), run_id


def test_hash_embedder_is_deterministic_and_normalised():
    first, again, other = HashEmbedder().embed(
        ["vector database benchmark", "vector database benchmark", "quarterly sales report"]
    )
    assert first == again
    assert abs(sum(v * v for v in first) - 1) < 1e-9
    similarity = sum(a * b for a, b in zip(first, other, strict=True))
    assert similarity < 0.2


def test_completed_run_stores_episode_and_lessons():
    final, run_id = run(VECTOR_REQUEST)
    memories = LongTermMemory().list_user("alice")

    assert {m.kind for m in memories} == {
        "task_episode",
        "approach",
        "fact",
        "preference",
        "human_decision",
    }
    [decision] = [m for m in memories if m.kind == "human_decision"]
    assert "the reviewer chose to approve. Comment: send it" in decision.text
    [episode] = [m for m in memories if m.kind == "task_episode"]
    assert episode.text.startswith(f"Task: {VECTOR_REQUEST}")
    assert "1 revision(s)" in episode.text
    assert episode.outcome == "success"
    assert episode.tags == ["research_report"]
    assert all(m.source_run_id == run_id for m in memories)
    assert "saved 5 new" in final["events"][-1]["message"]


def test_repeating_a_task_strengthens_instead_of_duplicating():
    run(VECTOR_REQUEST)
    first = {m.text: m.importance for m in LongTermMemory().list_user("alice")}
    final, _ = run(VECTOR_REQUEST)
    second = LongTermMemory().list_user("alice")

    assert len(second) == len(first)
    assert all(m.importance >= first[m.text] for m in second)
    assert "strengthened 5 existing" in final["events"][-1]["message"]


def test_memories_are_scoped_per_user():
    run(VECTOR_REQUEST, user="alice")
    store = LongTermMemory()
    assert store.list_user("bob") == []
    assert store.search("bob", VECTOR_REQUEST) == []
    [match] = store.search("alice", VECTOR_REQUEST, kinds=["task_episode"])
    assert match.similarity > 0.5


def test_failed_plan_stores_nothing():
    run("[test:unplannable] anything")
    assert LongTermMemory().list_user("alice") == []


def test_dedupe_only_merges_within_the_same_kind():
    store = LongTermMemory()
    text = "Executive summaries should stay under 200 words"
    store.add("alice", MemoryItem(kind="preference", text=text))
    _, merged = store.add("alice", MemoryItem(kind="fact", text=text))
    assert not merged
    assert len(store.list_user("alice")) == 2
