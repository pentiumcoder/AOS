import pytest

from aos import context
from aos.agents import get_specialist
from aos.db.models import ToolCall as ToolCallRow
from aos.graph.nodes.actions import execute_actions
from aos.llm.base import LLMProvider, LLMResult, ToolCall
from aos.llm.router import LLMClient
from aos.schemas import ExecutionPlan, ProposedAction, SpecialistResult, Subtask
from aos.tools import policy

EMAIL = {"to": ["team@example.com"], "subject": "Summary", "body": "{{final_output}}"}


class Script(LLMProvider):
    """Replays a fixed list of tool calls, then answers."""

    name = "script"

    def __init__(self, *calls: ToolCall) -> None:
        super().__init__("script-1")
        self.calls = list(calls)
        self.offered: list[list[str]] = []
        self.tool_replies: list[str] = []

    def complete(self, request):
        self.offered.append([t.name for t in request.tools])
        if request.messages[-1].role == "tool":
            self.tool_replies.append(request.messages[-1].content)
        if self.calls:
            return LLMResult(tool_calls=[self.calls.pop(0)], provider=self.name, model=self.model)
        return LLMResult(parsed={"output": "done"}, provider=self.name, model=self.model)


@pytest.fixture
def scripted(monkeypatch):
    from aos.agents.specialists import base

    def install(*calls: ToolCall) -> Script:
        provider = Script(*calls)
        monkeypatch.setattr(base, "get_llm", lambda *a: LLMClient("x", [provider]))
        return provider

    return install


def writing_subtask(actions: list[str] | None = None) -> Subtask:
    return Subtask(
        id="s1",
        description="Write the summary",
        specialist="writing",
        expected_output="Three bullet points",
        actions=actions or [],
    )


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ("Summarise this and email it to the team", True),
        ("Draft the emails for Monday", True),
        ("Summarise the benchmark results", False),
        ("Send me the numbers", False),
    ],
)
def test_email_must_be_requested(request_text, expected):
    assert policy.requested("send_email", request_text) is expected


def test_recipients_must_be_known_or_written_in_the_request():
    request = "Email the summary to the team and to ana@corp.example"
    assert policy.check_action("send_email", EMAIL, request) is None
    assert policy.check_action("send_email", {**EMAIL, "to": ["ana@corp.example"]}, request) is None
    problem = policy.check_action("send_email", {**EMAIL, "to": ["john.doe@example.com"]}, request)
    assert problem.startswith("recipient not allowed: john.doe@example.com")
    assert "team@example.com" in problem


def test_send_email_is_hidden_unless_plan_and_request_ask_for_it():
    writer = get_specialist("writing")
    asked = "Summarise and email it to the team"
    names = lambda subtask, request: [t.name for t in writer.offered_tools(subtask, request)]  # noqa: E731
    assert "send_email" not in names(writing_subtask(), asked)
    assert "send_email" not in names(writing_subtask(["send_email"]), "Summarise the results")
    assert "send_email" in names(writing_subtask(["send_email"]), asked)


def test_unoffered_email_call_is_refused(scripted):
    provider = scripted(ToolCall(id="c1", name="send_email", args=EMAIL))
    result = get_specialist("writing").run(
        writing_subtask(), request="Summarise the results", dep_outputs={}
    )
    assert result.status == "success"
    assert result.proposed_actions == []
    assert "send_email" not in provider.offered[0]


def test_invented_recipient_is_refused_with_allowed_list(scripted):
    bad = {**EMAIL, "to": ["john.doe@example.com"]}
    provider = scripted(ToolCall(id="c1", name="send_email", args=bad))
    result = get_specialist("writing").run(
        writing_subtask(["send_email"]), request="Email it to the team", dep_outputs={}
    )
    assert result.proposed_actions == []
    assert provider.tool_replies[0].startswith("ERROR: recipient not allowed: john.doe@example.com")
    assert "team@example.com" in provider.tool_replies[0]


def test_repeated_identical_tool_call_is_not_rerun(scripted, db):
    query = {"sql": "SELECT database FROM benchmarks ORDER BY p95_latency_ms LIMIT 1"}
    scripted(
        ToolCall(id="c1", name="db_query", args=query),
        ToolCall(id="c2", name="db_query", args=query),
    )
    subtask = Subtask(
        id="s1", description="Fastest?", specialist="data_analysis", expected_output="Name"
    )
    with context.bind(run_id="run-repeat"):
        result = get_specialist("data_analysis").run(subtask, request="Fastest?", dep_outputs={})
    assert db.query(ToolCallRow).filter_by(run_id="run-repeat").count() == 1
    assert len(result.evidence) == 1
    assert "Qdrant" in result.evidence[0]


def action_state(*actions: ProposedAction, request: str) -> dict:
    plan = ExecutionPlan(
        task_type="t", rationale="r", confidence=0.9, subtasks=[writing_subtask(["send_email"])]
    )
    result = SpecialistResult(
        subtask_id="s1", specialist="writing", status="success", proposed_actions=list(actions)
    )
    return {
        "request": request,
        "plan": plan.model_dump(),
        "subtask_status": {"s1": "done"},
        "results": {"s1": result.model_dump()},
        "actions": None,
        "final_output": "Final text",
    }


def proposal(action_id: str, **args) -> ProposedAction:
    return ProposedAction(
        id=action_id, subtask_id="s1", agent="writing", tool="send_email", args={**EMAIL, **args}
    )


def test_duplicate_proposals_are_merged():
    state = action_state(proposal("a1"), proposal("a2"), request="Email it to the team")
    update = execute_actions(state)
    assert [a["id"] for a in update["actions"]] == ["a1"]
    assert len(update["pending_escalations"]) == 1


def test_policy_violations_are_blocked_without_escalating():
    state = action_state(proposal("a1", to=["mallory@evil.example"]), request="Email the team")
    update = execute_actions(state)
    assert update["actions"][0]["status"] == "rejected"
    assert update["pending_escalations"] == []


def test_approved_action_is_rechecked_before_it_runs(db):
    state = action_state(request="Email the team")
    edited = proposal("a1", to=["mallory@evil.example"]).model_dump()
    edited["status"] = "approved"
    update = execute_actions({**state, "actions": [edited]})
    assert update["actions"][0]["status"] == "rejected"
    assert db.query(ToolCallRow).filter_by(tool="send_email").count() == 0
