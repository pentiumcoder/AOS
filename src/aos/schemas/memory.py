from typing import Literal

from pydantic import BaseModel, Field

MemoryKind = Literal[
    "task_episode", "approach", "tool_usage", "fact", "preference", "human_decision"
]
MEMORY_KINDS: tuple[str, ...] = MemoryKind.__args__


class MemoryItem(BaseModel):
    kind: MemoryKind
    text: str = Field(min_length=3, description="One or two self-contained sentences")
    outcome: Literal["success", "failure", "n/a"] = "n/a"
    importance: float = Field(default=0.5, ge=0, le=1)
    tags: list[str] = Field(default_factory=list)


class MemoryExtraction(BaseModel):
    memories: list[MemoryItem] = Field(default_factory=list, max_length=8)


class StoredMemory(MemoryItem):
    id: str
    user_id: str
    access_count: int = 0
    created_at: float
    last_accessed_at: float
    source_run_id: str | None = None
    consolidated_into: str | None = None
    similarity: float | None = None
