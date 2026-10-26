import pytest

from aos.config import get_settings
from aos.hitl.levels import ApprovalLevel, allowed
from aos.hitl.policy import EscalationPolicy
from aos.schemas import ExecutionPlan, ProposedAction, Review


def plan(confidence: float) -> ExecutionPlan:
    return ExecutionPlan(task_type="t", rationale="r", confidence=confidence, subtasks=[])


def review(score: float) -> Review:
    return Review(subtask_id="s2", approved=False, score=score)


ACTION = ProposedAction(id="s4-a1", subtask_id="s4", agent="writing", tool="send_email")


@pytest.fixture
def policy():
    return EscalationPolicy.from_config()


@pytest.mark.parametrize(
    ("check", "trigger", "level", "origin", "scope"),
    [
        (lambda p: p.check_plan(plan(0.4)), "low_plan_confidence", "APPROVE_PLAN", "plan", None),
        (
            lambda p: p.check_plan(plan(0.7)),
            "borderline_plan_confidence",
            "NOTIFY",
            "plan",
            None,
        ),
        (
            lambda p: p.check_subtask("s3", 2, "timeout"),
            "repeated_specialist_failure",
            "TAKE_OVER",
            "review",
            "s3",
        ),
        (
            lambda p: p.check_review(review(0.3)),
            "low_review_score",
            "APPROVE_ACTION",
            "review",
            "s2",
        ),
        (
            lambda p: p.check_action(ACTION),
            "sensitive_operation",
            "APPROVE_ACTION",
            "execute_actions",
            "s4-a1",
        ),
        (
            lambda p: p.check_final(True),
            "user_requested_review",
            "APPROVE_ACTION",
            "synthesize",
            None,
        ),
    ],
)
def test_each_trigger_maps_to_its_level(policy, check, trigger, level, origin, scope):
    request = check(policy)
    assert (request.trigger, request.level, request.origin) == (trigger, level, origin)
    assert request.step_key == f"{origin}:{trigger}:{scope or 'run'}"


def test_nothing_escalates_when_all_is_well(policy):
    assert policy.check_plan(plan(0.9)) is None
    assert policy.check_subtask("s1", 1, "flaky") is None
    assert policy.check_review(review(0.65)) is None
    assert policy.check_final(False) is None


def test_disabled_trigger_never_fires():
    triggers = {"low_plan_confidence": {"level": "APPROVE_PLAN", "enabled": False}}
    assert EscalationPolicy(triggers, get_settings()).check_plan(plan(0.1)) is None


def test_allowed_decisions_per_level():
    assert allowed(ApprovalLevel.APPROVE_ACTION, "take_over")
    assert allowed(ApprovalLevel.APPROVE_PLAN, "modify")
    assert not allowed(ApprovalLevel.APPROVE_PLAN, "take_over")
    assert allowed(ApprovalLevel.TAKE_OVER, "approve")
    assert not allowed(ApprovalLevel.TAKE_OVER, "reject")
    assert not allowed(ApprovalLevel.NOTIFY, "approve")
