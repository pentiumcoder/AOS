import pytest

from aos.agents import PlanningError, get_specialist, plan, review
from aos.db.models import LLMCall, OutboxMessage
from aos.schemas import validate_plan

VECTOR_REQUEST = (
    "Research the top 3 open-source vector databases, compare them using our benchmark "
    "data, write an executive summary and email it to the team"
)


@pytest.fixture
def vector_plan():
    return plan(VECTOR_REQUEST)


def test_supervisor_decomposes_into_dependency_graph(vector_plan):
    assert validate_plan(vector_plan) == []
    assert [s.specialist for s in vector_plan.subtasks] == [
        "research",
        "data_analysis",
        "research",
        "writing",
    ]
    assert vector_plan.subtask("s4").depends_on == ["s1", "s2", "s3"]


def test_supervisor_replans_once_when_plan_is_invalid(db):
    result = plan("[test:invalid-plan] summarise something")
    assert validate_plan(result) == []
    assert db.query(LLMCall).filter_by(purpose="plan").count() == 2


def test_supervisor_gives_up_after_second_invalid_plan():
    with pytest.raises(PlanningError) as caught:
        plan("[test:unplannable] anything")
    assert caught.value.errors == ["plan has cycle: s1 -> s2 -> s1"]


def test_research_specialist_cites_search_results(vector_plan):
    result = get_specialist("research").run(
        vector_plan.subtask("s1"), request=VECTOR_REQUEST, dep_outputs={}
    )
    assert result.status == "success"
    assert result.tools_used == ["web_search"]
    assert "https://milvus.io" in result.output


def test_analysis_specialist_computes_from_database(vector_plan):
    result = get_specialist("data_analysis").run(
        vector_plan.subtask("s2"), request=VECTOR_REQUEST, dep_outputs={}
    )
    assert result.status == "success"
    assert result.tools_used == ["code_exec", "db_query"]
    assert "| Milvus | 4,200 | 18.4 | 0.962 | 1,450 | 0.133 |" in result.output
    assert "Lowest cost per 1M queries: Qdrant ($0.125)" in result.output


def test_writing_specialist_proposes_email_instead_of_sending(db, vector_plan):
    result = get_specialist("writing").run(
        vector_plan.subtask("s4"), request=VECTOR_REQUEST, dep_outputs={}
    )
    assert result.status == "success"
    assert [(a.tool, a.args["to"]) for a in result.proposed_actions] == [
        ("send_email", ["team@example.com"])
    ]
    assert result.proposed_actions[0].args["body"] == "{{final_output}}"
    assert db.query(OutboxMessage).count() == 0


def test_specialist_reports_blocker_as_failure():
    subtask = plan("[test:retry] compute").subtask("s1")
    result = get_specialist("code").run(subtask, request="[test:retry] compute", dep_outputs={})
    assert result.status == "failed"
    assert "ZeroDivisionError" in result.error


def test_reviewer_rejects_misquoted_figure_then_approves_revision(vector_plan):
    analysis = get_specialist("data_analysis").run(
        vector_plan.subtask("s2"), request=VECTOR_REQUEST, dep_outputs={}
    )
    upstream = {"s2": analysis.output}
    writer = get_specialist("writing")
    subtask = vector_plan.subtask("s4")
    draft = writer.run(subtask, request=VECTOR_REQUEST, dep_outputs=upstream, attempt=1)
    revision = writer.run(subtask, request=VECTOR_REQUEST, dep_outputs=upstream, attempt=2)

    first = review(subtask, draft, request=VECTOR_REQUEST, dep_outputs=upstream)
    second = review(subtask, revision, request=VECTOR_REQUEST, dep_outputs=upstream)
    assert not first.approved
    assert first.score == 0.45
    assert first.issues[0] == "Figures not found in any tool result or input: 4,600"
    assert any("3,650 QPS" in issue for issue in first.issues)
    assert "Milvus 4,200 QPS" in first.feedback
    assert second.approved


def test_reviewer_overrides_approval_of_invented_figures(vector_plan):
    from aos.schemas import SpecialistResult

    subtask = vector_plan.subtask("s1")
    invented = SpecialistResult(
        subtask_id="s1",
        specialist="research",
        status="success",
        output="Milvus handles 9,999 QPS according to https://milvus.io",
        evidence=["web_search -> Milvus is a distributed vector database"],
    )
    verdict = review(subtask, invented, request=VECTOR_REQUEST, dep_outputs={})
    assert not verdict.approved
    assert verdict.score <= 0.45
    assert verdict.issues[0].endswith("9,999")


def test_queued_action_is_withdrawn_so_the_agent_must_answer(monkeypatch, vector_plan):
    from aos.agents.specialists import base
    from aos.llm.base import LLMProvider, LLMResult, ToolCall
    from aos.llm.router import LLMClient

    email = {"to": ["team@example.com"], "subject": "Summary", "body": "{{final_output}}"}
    offered: list[list[str]] = []

    class KeepsEmailing(LLMProvider):
        name = "looper"

        def complete(self, request):
            names = [t.name for t in request.tools]
            offered.append(names)
            if "send_email" in names:
                calls = [ToolCall(id=f"c{i}", name="send_email", args=email) for i in range(3)]
                return LLMResult(tool_calls=calls, provider=self.name, model=self.model)
            answer = {"output": "Summary text", "confidence": 0.8}
            return LLMResult(parsed=answer, provider=self.name, model=self.model)

    monkeypatch.setattr(base, "get_llm", lambda *a: LLMClient("writing", [KeepsEmailing("x")]))
    result = get_specialist("writing").run(
        vector_plan.subtask("s4"), request=VECTOR_REQUEST, dep_outputs={}
    )
    assert result.status == "success"
    assert len(result.proposed_actions) == 1
    assert "send_email" in offered[0] and "send_email" not in offered[1]
