from typing import Any, Literal

from pydantic import BaseModel, Field

DecisionAction = Literal["approve", "modify", "reject", "take_over"]


class EscalationRequest(BaseModel):
    step_key: str
    trigger: str
    level: str
    origin: Literal["plan", "review", "synthesize", "execute_actions"]
    reason: str
    subtask_id: str | None = None
    action_id: str | None = None


class HumanDecision(BaseModel):
    action: DecisionAction
    payload: Any = Field(
        default=None,
        description="Edited plan, action arguments or deliverable for modify; output for take_over",
    )
    comment: str = ""
    reviewer: str = "reviewer"
