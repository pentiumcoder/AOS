from aos.db.models import LLMCall, OutboxMessage, Run, Task, ToolCall
from aos.graph import create_task, execute_run

VECTOR_REQUEST = (
    "Research the top 3 open-source vector databases, compare them using our benchmark "
    "data, write an executive summary and email it to the team"
)


def run(request: str, **kwargs) -> tuple[dict, str, str]:
    task_id, run_id = create_task(request, **kwargs)
    return execute_run(run_id), task_id, run_id


def messages(final: dict, kind: str | None = None) -> list[str]:
    return [e["message"] for e in final["events"] if kind is None or e["kind"] == kind]


def test_showcase_run_end_to_end(db, finish):
    final, task_id, run_id = finish(VECTOR_REQUEST)

    assert final["subtask_status"] == {"s1": "done", "s2": "done", "s3": "done", "s4": "done"}
    assert "dispatching s1, s2 in parallel" in messages(final, "dispatch")
    assert final["visits"]["s4"] == 2
    assert [r["score"] for r in final["reviews"]["s4"]] == [0.45, 0.91]
    assert "Milvus leads at 4,200 QPS" in final["final_output"]
    assert "### Benchmark detail" in final["final_output"]

    assert [(a["tool"], a["status"]) for a in final["actions"]] == [("send_email", "executed")]
    assert [(e["trigger"], e["decision"]) for e in final["escalations"]] == [
        ("sensitive_operation", "approve")
    ]
    email = db.query(OutboxMessage).filter_by(run_id=run_id).one()
    assert email.body == final["final_output"]

    assert db.get(Task, task_id).status == "completed"
    stored = db.get(Run, run_id)
    assert (stored.status, stored.task_type) == ("completed", "research_report")
    assert len(stored.plan["subtasks"]) == 4
    assert db.query(LLMCall).filter_by(run_id=run_id).count() >= 10
    assert db.query(ToolCall).filter_by(run_id=run_id).count() == 6


def test_generic_request_completes():
    final, _, _ = run("What is retrieval-augmented generation?")
    assert final["subtask_status"] == {"s1": "done", "s2": "done"}
    assert final["final_output"].startswith("Summary based on the research")
    assert final["actions"] == []


def test_failed_subtask_is_retried_with_alternative_approach():
    final, _, _ = run("[test:retry] compute the mean")
    assert final["subtask_status"] == {"s1": "done"}
    assert final["visits"]["s1"] == 2
    assert final["failures"]["s1"] == 1
    assert "different tool or approach" in final["approach_hints"]["s1"]
    assert final["final_output"].strip() == "The mean is 5.0"


def test_second_failure_escalates_for_a_human_to_take_over(finish):
    from aos.schemas.escalation import HumanDecision

    def take_over(escalation):
        return HumanDecision(action="take_over", payload="March sales: 1,240 units")

    final, _, _ = finish("[test:fail-twice] sales summary", decide=take_over)
    assert final["subtask_status"] == {"s1": "done", "s2": "done"}
    assert final["results"]["s1"]["specialist"] == "human"
    assert [(e["trigger"], e["level"]) for e in final["escalations"]] == [
        ("repeated_specialist_failure", "TAKE_OVER")
    ]
    assert "March sales: 1,240 units" in final["final_output"]


def test_low_plan_confidence_escalates_before_work_starts(finish):
    final, _, _ = finish("[test:low-confidence] do the thing")
    assert [(e["trigger"], e["level"]) for e in final["escalations"]] == [
        ("low_plan_confidence", "APPROVE_PLAN")
    ]
    order = [e["node"] for e in final["events"]]
    assert order.index("escalate") < order.index("schedule")


def test_low_review_score_after_max_revisions_escalates(finish):
    final, _, _ = finish("[test:low-score] announce the feature")
    assert final["visits"]["s1"] == 3
    assert final["revisions"]["s1"] == 2
    assert [e["trigger"] for e in final["escalations"]] == ["low_review_score"]
    assert final["subtask_status"]["s1"] == "done"


def test_requested_human_review_escalates_the_deliverable(finish):
    final, _, _ = finish("What is a vector index?", require_human_review=True)
    assert [(e["trigger"], e["origin"]) for e in final["escalations"]] == [
        ("user_requested_review", "synthesize")
    ]


def test_planning_failure_fails_the_run(db):
    final, task_id, run_id = run("[test:unplannable] anything")
    assert final["plan"] is None
    assert "plan has cycle" in final["error"]
    assert db.get(Task, task_id).status == "failed"
    assert db.get(Run, run_id).error.startswith("planning failed")
