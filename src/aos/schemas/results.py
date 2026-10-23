from typing import Any, Literal

from pydantic import BaseModel, Field


class ProposedAction(BaseModel):
    id: str
    subtask_id: str
    agent: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""
    status: Literal["proposed", "approved", "rejected", "executed", "failed"] = "proposed"
    result: Any = None


class SpecialistOutput(BaseModel):
    """Final answer a specialist returns when its subtask is done."""

    output: str = Field(description="The deliverable for this subtask, in the expected format")
    data: dict[str, Any] = Field(default_factory=dict, description="Structured facts or figures")
    confidence: float = Field(default=0.7, ge=0, le=1)
    completed: bool = Field(default=True, description="False if the subtask could not be done")
    blocker: str | None = Field(default=None, description="Why it could not be done")


class SpecialistResult(BaseModel):
    subtask_id: str
    specialist: str
    status: Literal["success", "failed"]
    output: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list, description="Tool results the agent saw")
    confidence: float = 0.0
    attempt: int = 1
    error: str | None = None
