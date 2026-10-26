from aos.db import get_redis
from aos.db.models import LLMCall, Run
from aos.memory import WorkingMemory

VECTOR_REQUEST = (
    "Research the top 3 open-source vector databases, compare them using our benchmark "
    "data, write an executive summary and email it to the team"
)


def test_round_trip_and_clear():
    memory = WorkingMemory("run-wm")
    memory.set_plan({"subtasks": []})
    memory.put_output("s1", "first", {"n": 1})
    memory.put_output("s2", "second")
    memory.add_note("research", "found three sources", "s1")
    memory.log_error("code", "timed out", "s3")

    assert memory.get_outputs(["s2", "s1", "s9"]) == {"s2": "second", "s1": "first"}
    snapshot = memory.snapshot()
    assert snapshot["outputs"]["s1"] == {"output": "first", "data": {"n": 1}}
    assert [n["text"] for n in snapshot["notes"]] == ["found three sources"]
    assert snapshot["errors"][0]["message"] == "timed out"
    assert 0 < get_redis().ttl(memory._key("outputs")) <= 24 * 3600

    memory.clear()
    assert get_redis().keys(f"{memory.prefix}:*") == []


def test_dependent_subtasks_read_upstream_output_from_working_memory(db, finish):
    _, _, run_id = finish(VECTOR_REQUEST)

    writer_prompt = (
        db.query(LLMCall)
        .filter_by(run_id=run_id, subtask_id="s4", purpose="specialist")
        .first()
        .messages["messages"][0]["content"]
    )
    assert "### s2" in writer_prompt
    assert "| Milvus | 4,200 |" in writer_prompt

    assert get_redis().keys(f"aos:wm:{run_id}:*") == []
    snapshot = db.get(Run, run_id).wm_snapshot
    assert set(snapshot["outputs"]) == {"s1", "s2", "s3", "s4"}
    assert snapshot["plan"]["task_type"] == "research_report"
    assert any(note["subtask_id"] == "s4" for note in snapshot["notes"])
