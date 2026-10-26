from functools import lru_cache
from typing import Any

import yaml

from aos.config import Settings, get_settings
from aos.hitl.levels import ApprovalLevel
from aos.schemas import ExecutionPlan, ProposedAction, Review
from aos.schemas.escalation import EscalationRequest


class EscalationPolicy:
    """Decides when a run must stop for a human, and at which approval level."""

    def __init__(self, triggers: dict[str, dict[str, Any]], settings: Settings) -> None:
        self._triggers = triggers
        self._settings = settings

    @classmethod
    def from_config(cls, settings: Settings | None = None) -> "EscalationPolicy":
        settings = settings or get_settings()
        path = settings.config_dir / "escalation.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(data.get("triggers") or {}, settings)

    def level(self, trigger: str) -> ApprovalLevel | None:
        config = self._triggers.get(trigger)
        if not config or config.get("enabled", True) is False:
            return None
        return ApprovalLevel(config["level"])

    def check_plan(self, plan: ExecutionPlan) -> EscalationRequest | None:
        settings = self._settings
        if plan.confidence < settings.plan_confidence_threshold:
            return self._request(
                "low_plan_confidence",
                "plan",
                f"plan confidence {plan.confidence:.2f} is below "
                f"{settings.plan_confidence_threshold:.2f}",
            )
        if plan.confidence < settings.plan_notify_threshold:
            return self._request(
                "borderline_plan_confidence",
                "plan",
                f"plan confidence {plan.confidence:.2f} is below "
                f"{settings.plan_notify_threshold:.2f}",
            )
        return None

    def check_subtask(
        self, subtask_id: str, failures: int, error: str | None
    ) -> EscalationRequest | None:
        if failures < self._settings.max_attempts:
            return None
        return self._request(
            "repeated_specialist_failure",
            "review",
            f"{subtask_id} failed {failures} times: {error}",
            subtask_id=subtask_id,
        )

    def check_review(self, review: Review) -> EscalationRequest | None:
        threshold = self._settings.review_escalate_score
        if review.score >= threshold:
            return None
        return self._request(
            "low_review_score",
            "review",
            f"{review.subtask_id} still scores {review.score:.2f} after the last revision",
            subtask_id=review.subtask_id,
        )

    def check_action(self, action: ProposedAction) -> EscalationRequest | None:
        return self._request(
            "sensitive_operation",
            "execute_actions",
            f"{action.agent} wants to run {action.tool}, which has side effects",
            subtask_id=action.subtask_id,
            action_id=action.id,
        )

    def check_final(self, require_human_review: bool) -> EscalationRequest | None:
        if not require_human_review:
            return None
        return self._request(
            "user_requested_review",
            "synthesize",
            "the task was submitted with human review of the deliverable",
        )

    def _request(
        self, trigger: str, origin: str, reason: str, **scope: str | None
    ) -> EscalationRequest | None:
        level = self.level(trigger)
        if level is None:
            return None
        key = scope.get("action_id") or scope.get("subtask_id") or "run"
        return EscalationRequest(
            step_key=f"{origin}:{trigger}:{key}",
            trigger=trigger,
            level=level.value,
            origin=origin,
            reason=reason,
            **scope,
        )


@lru_cache
def get_policy() -> EscalationPolicy:
    return EscalationPolicy.from_config()
