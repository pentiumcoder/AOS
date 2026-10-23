import json
import re
from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

RESPOND_TOOL = "respond"


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: list[ToolCall] | None = None) -> "Message":
        return cls(role="assistant", content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool(cls, call_id: str, name: str, content: str) -> "Message":
        return cls(role="tool", content=content, tool_call_id=call_id, name=name)


class ToolDef(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMRequest(BaseModel):
    role: str
    messages: list[Message]
    system: str | None = None
    tools: list[ToolDef] = Field(default_factory=list)
    schema_name: str | None = None
    response_schema: dict[str, Any] | None = None
    max_tokens: int = 2048
    meta: dict[str, Any] = Field(default_factory=dict)


class LLMResult(BaseModel):
    text: str = ""
    parsed: Any = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    provider: str
    model: str
    latency_ms: float = 0.0


class LLMError(Exception):
    pass


class TransientLLMError(LLMError):
    pass


class StructuredOutputError(LLMError):
    pass


class LLMUnavailable(LLMError):
    pass


class LLMProvider(ABC):
    name: str = "base"

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResult: ...

    def __repr__(self) -> str:
        return f"{self.name}:{self.model}"


def respond_tool(schema: dict[str, Any]) -> ToolDef:
    return ToolDef(
        name=RESPOND_TOOL,
        description="Return your final answer in the required structure. Call it once, when done.",
        parameters=schema,
    )


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def json_from_text(text: str) -> Any:
    cleaned = _FENCE.sub("", text.strip())
    start = min((i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError("no JSON object in response text")
    return json.loads(cleaned[start:])
