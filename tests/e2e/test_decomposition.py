import pytest
from harness import VECTOR_REQUEST

pytestmark = pytest.mark.e2e

SPECIALISTS = {"research", "data_analysis", "writing", "code"}


@pytest.mark.parametrize(
    "request_text",
    [
        VECTOR_REQUEST,
        "What is retrieval-augmented generation?",
        "[test:retry] compute the mean",
        "[test:learning] Summarise the latency of our vector databases",
        "[test:low-score] announce the feature",
    ],
)
def test_requests_become_valid_dependency_graphs(api, request_text):
    task = api.run(request_text)
    plan = task["run"]["plan"]
    ids = [s["id"] for s in plan["subtasks"]]

    assert plan["subtasks"] and len(ids) == len(set(ids))
    assert 0 <= plan["confidence"] <= 1 and plan["task_type"]
    for subtask in plan["subtasks"]:
        assert subtask["specialist"] in SPECIALISTS
        assert subtask["expected_output"]
        assert set(subtask["depends_on"]) <= set(ids) - {subtask["id"]}
    order = {sid: index for index, sid in enumerate(_topological(plan["subtasks"]))}
    assert len(order) == len(ids)


def _topological(subtasks):
    remaining = {s["id"]: set(s["depends_on"]) for s in subtasks}
    done = []
    while remaining:
        ready = [sid for sid, deps in remaining.items() if deps <= set(done)]
        assert ready, f"cycle among {sorted(remaining)}"
        done.extend(ready)
        for sid in ready:
            del remaining[sid]
    return done
