import pytest
from fastapi.testclient import TestClient

from aos.api.main import app
from aos.db.models import Escalation, LLMCall, Notification, OutboxMessage, Run, Task
from aos.graph.builder import reset_graph
from aos.graph.runner import create_task, execute_run, is_paused, resume_run
from aos.hitl.queue import DecisionError, list_escalations, record_decision
from aos.schemas.escalation import HumanDecision

VECTOR_REQUEST = (
    "Research the top 3 open-source vector databases, compare them using our benchmark "
    "data, write an executive summary and email it to the team"
)


def decisions(*answers: HumanDecision):
    """A decide() callback that gives these answers in order."""
    queue = list(answers)
    return lambda escalation: queue.pop(0)


def test_rejected_email_is_never_sent(db, finish):
    final, _, run_id = finish(
        VECTOR_REQUEST, decide=decisions(HumanDecision(action="reject", comment="not yet"))
    )
    [action] = final["actions"]
    assert (action["status"], action["result"]) == ("rejected", "rejected by reviewer: not yet")
    assert db.query(OutboxMessage).filter_by(run_id=run_id).count() == 0
    assert db.get(Run, run_id).status == "completed"


def test_modified_email_is_sent_with_reviewer_changes(db, finish):
    edit = HumanDecision(action="modify", payload={"subject": "Weekly vector DB summary"})
    _, _, run_id = finish(VECTOR_REQUEST, decide=decisions(edit))
    email = db.query(OutboxMessage).filter_by(run_id=run_id).one()
    assert email.subject == "Weekly vector DB summary"
    assert email.recipient == "team@example.com"


def test_reviewer_edit_cannot_bypass_recipient_policy(db, finish):
    edit = HumanDecision(action="modify", payload={"to": ["mallory@evil.example"]})
    final, _, run_id = finish(VECTOR_REQUEST, decide=decisions(edit))
    assert final["actions"][0]["status"] == "rejected"
    assert db.query(OutboxMessage).filter_by(run_id=run_id).count() == 0


def test_plan_can_be_replaced_by_the_reviewer(finish):
    edited = {
        "task_type": "research_summary",
        "rationale": "Reviewer added a writing step.",
        "confidence": 0.9,
        "subtasks": [
            {
                "id": "s1",
                "description": "Gather background",
                "specialist": "research",
                "expected_output": "Notes",
            },
            {
                "id": "s2",
                "description": "Summarise s1",
                "specialist": "writing",
                "depends_on": ["s1"],
                "expected_output": "Two sentences",
            },
        ],
    }
    final, _, _ = finish(
        "[test:low-confidence] do the thing",
        decide=decisions(HumanDecision(action="modify", payload=edited)),
    )
    assert [s["id"] for s in final["plan"]["subtasks"]] == ["s1", "s2"]
    assert final["subtask_status"] == {"s1": "done", "s2": "done"}


def test_rejected_plan_is_replanned_with_the_comment(db, finish):
    answers = decisions(
        HumanDecision(action="reject", comment="Use the internal wiki instead"),
        HumanDecision(action="approve"),
    )
    final, _, run_id = finish("[test:low-confidence] do the thing", decide=answers)
    rows = db.query(Escalation).filter_by(run_id=run_id).order_by(Escalation.created_at).all()
    assert [r.step_key for r in rows] == [
        "plan:low_plan_confidence:run#0",
        "plan:low_plan_confidence:run#1",
    ]
    assert [r.status for r in rows] == ["rejected", "approved"]
    replan = db.query(LLMCall).filter_by(run_id=run_id, purpose="plan").all()[-1]
    assert "Use the internal wiki instead" in replan.messages["messages"][0]["content"]
    assert final["final_output"]


def test_take_over_level_can_retry_with_a_hint_first(finish):
    answers = decisions(
        HumanDecision(action="approve", comment="The warehouse is back up, try again"),
        HumanDecision(action="take_over", payload="Sales were 1,240 units"),
    )
    final, _, _ = finish("[test:fail-twice] sales summary", decide=answers)
    assert len(final["escalations"]) == 2
    assert final["approach_hints"]["s1"] == "The warehouse is back up, try again"
    assert final["results"]["s1"]["output"] == "Sales were 1,240 units"


def test_rejected_deliverable_goes_back_to_the_writer(db, finish):
    answers = decisions(
        HumanDecision(action="reject", comment="Mention retrieval latency"),
        HumanDecision(action="approve"),
    )
    final, _, run_id = finish("What is a vector index?", require_human_review=True, decide=answers)
    assert final["visits"]["s2"] == 2
    prompts = db.query(LLMCall).filter_by(run_id=run_id, subtask_id="s2", purpose="specialist")
    assert "Mention retrieval latency" in prompts.all()[-1].messages["messages"][0]["content"]
    assert [e["decision"] for e in final["escalations"]] == ["reject", "approve"]


def test_notify_level_informs_without_pausing(db):
    _, run_id = create_task("[test:borderline] background please")
    final = execute_run(run_id)
    assert not is_paused(final)
    [row] = db.query(Escalation).filter_by(run_id=run_id).all()
    assert (row.level, row.status) == ("NOTIFY", "auto_proceeded")
    assert db.query(Notification).filter_by(escalation_id=row.id).count() == 1


def test_resume_survives_a_rebuilt_graph(db):
    _, run_id = create_task(VECTOR_REQUEST)
    assert is_paused(execute_run(run_id))
    reset_graph()
    [escalation] = list_escalations(status="pending", run_id=run_id)
    decision = HumanDecision(action="approve")
    record_decision(escalation["id"], decision)
    final = resume_run(run_id, decision.model_dump())
    assert final["actions"][0]["status"] == "executed"


def test_decisions_are_validated(db):
    _, run_id = create_task("[test:low-confidence] do the thing")
    execute_run(run_id)
    [escalation] = list_escalations(status="pending", run_id=run_id)
    with pytest.raises(DecisionError, match="take_over is not allowed for APPROVE_PLAN"):
        record_decision(escalation["id"], HumanDecision(action="take_over", payload="x"))
    record_decision(escalation["id"], HumanDecision(action="approve"))
    with pytest.raises(DecisionError, match="already approved"):
        record_decision(escalation["id"], HumanDecision(action="approve"))
    assert db.get(Escalation, escalation["id"]).review_seconds >= 0


def test_webhook_receives_escalations(monkeypatch):
    sent = []
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.example.test/aos")
    from aos.config import get_settings
    from aos.hitl import notifications

    get_settings.cache_clear()
    monkeypatch.setattr(notifications.httpx, "post", lambda url, **kw: sent.append((url, kw)))
    _, run_id = create_task(VECTOR_REQUEST)
    execute_run(run_id)
    [(url, request)] = sent
    assert url == "https://hooks.example.test/aos"
    assert request["json"]["level"] == "APPROVE_ACTION"


def test_review_through_the_api(db):
    with TestClient(app) as client:
        task_id = client.post("/tasks", json={"request": VECTOR_REQUEST}).json()["task_id"]
        task = client.get(f"/tasks/{task_id}").json()
        assert task["status"] == "awaiting_human"
        [waiting] = task["run"]["pending_escalations"]

        [queued] = client.get("/escalations").json()
        assert queued["id"] == waiting["id"]
        assert queued["allowed_decisions"] == ["approve", "modify", "reject", "take_over"]

        detail = client.get(f"/escalations/{waiting['id']}").json()
        assert detail["proposed_action"]["tool"] == "send_email"
        assert [c["id"] for c in detail["context"]["completed"]] == ["s1", "s2", "s3", "s4"]

        reply = client.post(
            f"/escalations/{waiting['id']}/chat", json={"message": "Why are you asking?"}
        ).json()
        assert "has side effects" in reply["answer"]
        assert [m["role"] for m in reply["chat"]] == ["reviewer", "agent"]

        decided = client.post(
            f"/escalations/{waiting['id']}/decision",
            json={"action": "approve", "reviewer": "ana"},
        )
        assert decided.json()["status"] == "approved"
        assert client.get(f"/tasks/{task_id}").json()["status"] == "completed"
        again = client.post(f"/escalations/{waiting['id']}/decision", json={"action": "approve"})
        assert again.status_code == 409
        assert client.get("/escalations").json() == []
    assert db.get(Task, task_id).final_output
