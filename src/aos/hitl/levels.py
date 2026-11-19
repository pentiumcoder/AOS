from enum import StrEnum


class ApprovalLevel(StrEnum):
    NOTIFY = "NOTIFY"
    APPROVE_ACTION = "APPROVE_ACTION"
    APPROVE_PLAN = "APPROVE_PLAN"
    TAKE_OVER = "TAKE_OVER"


# with TAKE_OVER, approve = retry the subtask once more using the reviewer's hint
ALLOWED_DECISIONS: dict[ApprovalLevel, frozenset[str]] = {
    ApprovalLevel.NOTIFY: frozenset(),
    ApprovalLevel.APPROVE_ACTION: frozenset({"approve", "modify", "reject", "take_over"}),
    ApprovalLevel.APPROVE_PLAN: frozenset({"approve", "modify", "reject"}),
    ApprovalLevel.TAKE_OVER: frozenset({"take_over", "approve"}),
}


def allowed(level: str, action: str) -> bool:
    return action in ALLOWED_DECISIONS[ApprovalLevel(level)]
