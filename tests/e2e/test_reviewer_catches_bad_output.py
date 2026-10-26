import pytest
from harness import VECTOR_REQUEST

pytestmark = pytest.mark.e2e


def test_misquoted_figure_is_rejected_and_fixed(api):
    task = api.run(VECTOR_REQUEST)
    writer = next(s for s in task["run"]["subtasks"] if s["id"] == "s4")

    first, second = writer["reviews"]
    assert not first["approved"] and first["score"] < 0.5
    assert first["issues"][0] == "Figures not found in any tool result or input: 4,600"
    assert second["approved"]
    assert writer["attempts"] == 2
    assert "Milvus leads at 4,200 QPS" in task["final_output"]
    assert "4,600" not in task["final_output"]


def test_low_quality_work_escalates_after_the_last_revision(api):
    task = api.run("[test:low-score] announce the feature")
    [subtask] = task["run"]["subtasks"]
    assert [r["score"] for r in subtask["reviews"]] == [0.3, 0.3, 0.3]
    assert [e["trigger"] for e in task["run"]["escalations"]] == ["low_review_score"]
