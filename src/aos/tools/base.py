import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from aos.llm.base import ToolDef


class ToolError(Exception):
    """An expected tool failure. The message is returned to the calling agent."""


@dataclass(frozen=True)
class ToolContext:
    agent: str
    run_id: str | None
    workspace: Path


Handler = Callable[[Any, ToolContext], Any]


@dataclass
class ToolSpec:
    name: str
    description: str
    handler: Handler
    input_model: type[BaseModel] | None = None
    output_model: type[BaseModel] | None = None
    input_schema: dict[str, Any] | None = None
    allowed_agents: frozenset[str] = field(default_factory=frozenset)
    rate_limit_per_min: int = 60
    timeout_s: float = 30.0
    sensitive: bool = False

    def parameters(self) -> dict[str, Any]:
        if self.input_model is not None:
            return self.input_model.model_json_schema()
        return self.input_schema or {"type": "object", "properties": {}}

    def tool_def(self) -> ToolDef:
        return ToolDef(name=self.name, description=self.description, parameters=self.parameters())


class ToolResult(BaseModel):
    tool: str
    success: bool
    output: Any = None
    error: str | None = None
    latency_ms: float = 0.0

    def as_text(self, limit: int = 6000) -> str:
        if not self.success:
            return f"ERROR: {self.error}"
        # Sorted keys keep the text identical after a round trip through Postgres JSONB,
        # which replay relies on when it compares prompts.
        text = (
            self.output
            if isinstance(self.output, str)
            else json.dumps(self.output, default=str, sort_keys=True)
        )
        if len(text) <= limit:
            return text
        return f"{text[:limit]}... [truncated {len(text) - limit} chars]"
