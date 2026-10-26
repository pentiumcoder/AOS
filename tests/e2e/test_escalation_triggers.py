import pytest
from harness import VECTOR_REQUEST

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize(
    ("request_text", "fields", "trigger", "level"),
    [
        ("[test:low-confidence] do the thing", {}, "low_plan_confidence", "APPROVE_PLAN"),
        ("[test:fail-twice] sales summary", {}, "repeated_specialist_failure", "TAKE_OVER"),
        (VECTOR_REQUEST, {}, "sensitive_operation", "APPROVE_ACTION"),
        ("[test:low-score] announce the feature", {}, "low_review_score", "APPROVE_ACTION"),
        (
            "What is a vector index?",
            {"require_human_review": True},
            "user_requested_review",
            "APPROVE_ACTION",
        ),
    ],
)
def test_trigger_pauses_at_the_right_level(api, request_text, fields, trigger, level):
    task_id = api.submit(request_text, **fields)
    task = api.wait(task_id)
    assert task["status"] == "awaiting_human"
    [waiting] = task["run"]["pending_escalations"]
    assert (waiting["trigger"], waiting["level"]) == (trigger, level)

    detail = api.get(f"/escalations/{waiting['id']}")
    assert detail["context"]["task"]["request"] == request_text
    finished = api.finish(task_id)
    assert finished["status"] == "completed"


def test_borderline_confidence_notifies_without_pausing(api):
    task_id = api.submit("[test:borderline] background please")
    task = api.wait(task_id)
    assert task["status"] == "completed"
    [notice] = api.get("/escalations", status="auto_proceeded", task_id=task_id)
    assert (notice["trigger"], notice["level"]) == ("borderline_plan_confidence", "NOTIFY")


def test_decisions_outside_the_level_are_refused(api):
    task_id = api.submit("[test:low-confidence] do the thing")
    [waiting] = api.wait(task_id)["run"]["pending_escalations"]
    refused = api.client.post(
        f"/escalations/{waiting['id']}/decision", json={"action": "take_over", "payload": "x"}
    )
    assert refused.status_code == 409
    assert api.finish(task_id)["status"] == "completed"
