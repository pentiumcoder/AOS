import pytest

pytestmark = pytest.mark.e2e

FIRST = "[test:learning] Summarise the latency of our vector databases"
SECOND = "[test:learning] Briefly summarise vector database latency"


def attempts(task):
    return sum(s["attempts"] for s in task["run"]["subtasks"])


def test_second_similar_task_learns_from_the_first(api):
    first = api.run(FIRST)
    second = api.run(SECOND)

    assert first["run"]["plan"]["memory_influence"] == []
    [influence] = second["run"]["plan"]["memory_influence"]
    memory = api.get(f"/memories/{influence['memory_id']}")
    assert memory["kind"] == "approach" and memory["user_id"] == api.user

    assert attempts(second) < attempts(first)
    first_cost = api.get(f"/runs/{first['run']['id']}/metrics")["llm"]
    second_cost = api.get(f"/runs/{second['run']['id']}/metrics")["llm"]
    assert second_cost["input_tokens"] < first_cost["input_tokens"]
    assert "14.9 ms" in second["final_output"]


def test_memories_belong_to_their_user(api):
    api.run(FIRST)
    mine = api.get(f"/users/{api.user}/memories")
    assert {m["kind"] for m in mine} >= {"task_episode", "approach"}
    assert api.get(f"/users/{api.user}-someone-else/memories") == []
