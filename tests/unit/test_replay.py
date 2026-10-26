from fastapi.testclient import TestClient
from sqlalchemy.orm.attributes import flag_modified

from aos.api.main import app
from aos.db.models import Escalation, LLMCall, OutboxMessage, Run
from aos.memory.longterm import LongTermMemory
from aos.replay.compare import compare
from aos.replay.engine import list_steps, replay

VECTOR_REQUEST = (
    "Research the top 3 open-source vector databases, compare them using our benchmark "
    "data, write an executive summary and email it to the team"
)


def step(run_id: str, agent: str, subtask_id: str, nth: int = -1) -> dict:
    finals = [
        s
        for s in list_steps(run_id)
        if s["agent"] == agent and s["subtask_id"] == subtask_id and s["response"].get("parsed")
    ]
    return finals[nth]


def edited(found: dict, old: str, new: str) -> dict:
    parsed = {**found["response"]["parsed"]}
    parsed["output"] = parsed["output"].replace(old, new)
    return {found["id"]: {**found["response"], "parsed": parsed}}


def test_unchanged_replay_reproduces_the_run_for_free(db, finish):
    original, _, parent = finish(VECTOR_REQUEST, user_id="ana")
    memories_before = len(LongTermMemory().list_user("ana"))

    run_id, final = replay(parent)
    summary = db.get(Run, run_id).metrics["replay"]
    assert summary["fresh_calls"] == 0 and summary["divergence"] is None
    assert summary["replayed_calls"] == db.query(LLMCall).filter_by(run_id=run_id).count()
    assert final["final_output"] == original["final_output"]
    assert db.get(Run, run_id).metrics["llm"]["cost_usd"] == 0.0

    assert [a["status"] for a in final["actions"]] == ["skipped"]
    assert db.query(OutboxMessage).filter_by(run_id=run_id).count() == 0
    assert db.query(Escalation).filter_by(run_id=run_id).count() == 0
    assert len(LongTermMemory().list_user("ana")) == memories_before
    assert db.get(Run, run_id).parent_run_id == parent


def test_injected_figure_is_caught_and_the_run_reconverges(db, finish):
    original, _, parent = finish(VECTOR_REQUEST)
    analysis = step(parent, "data_analysis", "s2")

    run_id, final = replay(parent, overrides=edited(analysis, "4,200", "4,900"))
    summary = db.get(Run, run_id).metrics["replay"]
    assert summary["overridden_calls"] == [analysis["id"]]
    assert summary["divergence"]["agent"] == "reviewer"
    assert summary["divergence"]["subtask_id"] == "s2"
    first_review = final["reviews"]["s2"][0]
    assert first_review["issues"][0] == "Figures not found in any tool result or input: 4,900"
    assert final["final_output"] == original["final_output"]

    writer = db.query(LLMCall).filter_by(run_id=run_id, agent="writing").all()
    assert writer and all(call.replayed for call in writer)


def test_edited_deliverable_changes_only_what_follows(finish):
    original, _, parent = finish(VECTOR_REQUEST)
    writer = step(parent, "writing", "s4")
    change = edited(writer, "Qdrant for latency-sensitive", "Qdrant for every latency-sensitive")

    run_id, final = replay(parent, overrides=change)
    assert final["final_output"] != original["final_output"]
    report = compare(parent, run_id)
    by_id = {row["id"]: row for row in report["subtasks"]}
    assert not by_id["s4"]["same_output"]
    assert all(by_id[sid]["same_output"] for sid in ("s1", "s2", "s3"))
    assert report["plan"]["same"]
    assert any("every latency-sensitive" in line for line in report["final_output"]["diff"])


def test_live_mode_asks_the_models_again(db, finish):
    _, _, parent = finish(VECTOR_REQUEST)
    run_id, _ = replay(parent, mode="live")
    summary = db.get(Run, run_id).metrics["replay"]
    assert summary["replayed_calls"] == 0
    assert summary["fresh_calls"] == db.query(LLMCall).filter_by(run_id=run_id).count()


def test_replay_through_the_api(finish):
    _, _, parent = finish("[test:retry] compute the mean")
    with TestClient(app) as client:
        steps = client.get(f"/runs/{parent}/steps").json()
        assert [s["agent"] for s in steps][:2] == ["supervisor", "code"]
        assert steps[1]["preview"].startswith("calls code_exec(")

        accepted = client.post(f"/runs/{parent}/replay", json={}).json()
        assert accepted["parent_run_id"] == parent
        detail = client.get(f"/tasks/{accepted['task_id']}").json()
        assert detail["status"] == "completed"

        report = client.get(f"/runs/{parent}/compare/{accepted['run_id']}").json()
        assert report["final_output"]["same"]
        assert report["replay"]["fresh_calls"] == 0
        assert client.post("/runs/nope/replay", json={}).status_code == 404
        assert client.get(f"/runs/{parent}/compare/nope").status_code == 404


def test_replay_matches_when_stored_json_comes_back_reordered(db, finish):
    """Postgres JSONB does not keep key order; replays must not depend on it."""

    def reorder(value):
        if isinstance(value, dict):
            return {k: reorder(value[k]) for k in reversed(list(value))}
        if isinstance(value, list):
            return [reorder(v) for v in value]
        return value

    _, _, parent = finish(VECTOR_REQUEST)
    for call in db.query(LLMCall).filter_by(run_id=parent):
        call.response = reorder(call.response)
        # Reordered dicts compare equal, so the change has to be flagged to be written.
        flag_modified(call, "response")
    db.commit()

    run_id, _ = replay(parent)
    summary = db.get(Run, run_id).metrics["replay"]
    assert summary["fresh_calls"] == 0, summary["divergence"]
