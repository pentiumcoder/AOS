from pydantic import BaseModel, Field


class ReviewVerdict(BaseModel):
    approved: bool
    score: float = Field(ge=0, le=1, description="Overall quality from 0 to 1")
    issues: list[str] = Field(default_factory=list, description="Concrete problems found")
    feedback: str = Field(default="", description="What the specialist must change")


class Review(ReviewVerdict):
    subtask_id: str
    attempt: int = 1
