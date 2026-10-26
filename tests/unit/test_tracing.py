from collections import Counter

from fastapi.testclient import TestClient

from aos.api.main import app
from aos.db.models import LLMCall, Run, Span, ToolCall

VECTOR_REQUEST = (
    "Research the top 3 open-source vector databases, compare them using our benchmark "
    "data, write an executive summary and email it to the team"
)


def test_paused_and_resumed_run_is_one_trace(db, finish):
    _, _, run_id = finish(VECTOR_REQUEST)
    run = db.get(Run, run_id)
    spans = db.query(Span).filter_by(trace_id=run.trace_id).all()
    names = Counter(s.name for s in spans)

    assert names["task.run"] == 1 and names["task.resume"] == 1
    [root] = [s for s in spans if s.name == "task.run"]
    [resume] = [s for s in spans if s.name == "task.resume"]
    assert root.parent_span_id is None and resume.parent_span_id == root.span_id
    assert root.status == "escalated"
    assert names["node.run_specialist"] == 5
    assert names["memory.retrieve"] == names["memory.persist"] == 1

    escalations = [s for s in spans if s.name == "hitl.escalation"]
    assert [s.status for s in escalations] == ["escalated", "escalated"]
    decided = [s for s in escalations if "aos.escalation.decision" in s.attributes]
    assert decided[0].attributes["aos.escalation.decision"] == "approve"


def test_every_model_and_tool_call_links_to_a_nested_span(db, finish):
    _, _, run_id = finish(VECTOR_REQUEST)
    spans = {s.span_id: s for s in db.query(Span).all()}

    for call in db.query(LLMCall).filter_by(run_id=run_id):
        span = spans[call.span_id]
        assert span.name == "llm.call"
        assert span.attributes["aos.call_key"] == call.call_key
        assert span.attributes["aos.tokens.input"] == call.input_tokens
        assert spans[span.parent_span_id].name.startswith(("node.", "memory."))
    for call in db.query(ToolCall).filter_by(run_id=run_id):
        span = spans[call.span_id]
        assert (span.name, span.attributes["aos.tool"]) == ("tool.invoke", call.tool)
        assert spans[span.parent_span_id].name in ("node.run_specialist", "node.execute_actions")


def test_node_spans_carry_the_decision_and_a_status(db, finish):
    _, _, run_id = finish(VECTOR_REQUEST)
    reviews = (
        db.query(Span).filter_by(run_id=run_id, name="node.review").order_by(Span.start_time).all()
    )
    statuses = [(s.status, s.attributes["aos.decision"][:13]) for s in reviews]
    assert ("warning", "s4 rejected (") in statuses
    assert all(status in ("success", "warning") for status, _ in statuses)
    plan = db.query(Span).filter_by(run_id=run_id, name="node.plan").one()
    assert plan.attributes["aos.decision"].startswith("4 subtasks")


def test_trace_api(finish):
    _, _, run_id = finish(VECTOR_REQUEST)
    with TestClient(app) as client:
        trace = client.get(f"/runs/{run_id}/trace").json()
        [root] = trace["roots"]
        assert root["name"] == "task.run"
        assert trace["span_count"] > 40
        plan = next(c for c in root["children"] if c["name"] == "node.plan")
        [llm] = [c for c in plan["children"] if c["name"] == "llm.call"]

        detail = client.get(f"/spans/{llm['span_id']}").json()
        [call] = detail["llm_calls"]
        assert call["purpose"] == "plan"
        assert call["messages"]["system"].startswith("You lead a team")
        assert client.get("/spans/0000000000000000").status_code == 404
        assert client.get("/runs/nope/trace").status_code == 404
