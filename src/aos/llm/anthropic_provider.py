from time import perf_counter
from typing import Any

import anthropic

from aos.llm.base import (
    RESPOND_TOOL,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResult,
    Message,
    ToolCall,
    TransientLLMError,
    Usage,
    respond_tool,
)

TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str, api_key: str) -> None:
        super().__init__(model)
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=120)

    def complete(self, request: LLMRequest) -> LLMResult:
        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in request.tools
        ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "messages": _convert(request.messages),
        }
        if request.system:
            kwargs["system"] = request.system
        if request.response_schema is not None:
            respond = respond_tool(request.response_schema)
            tools.append(
                {
                    "name": respond.name,
                    "description": respond.description,
                    "input_schema": respond.parameters,
                }
            )
            kwargs["tool_choice"] = (
                {"type": "any"} if request.tools else {"type": "tool", "name": RESPOND_TOOL}
            )
        if tools:
            kwargs["tools"] = tools

        start = perf_counter()
        try:
            response = self._client.messages.create(**kwargs)
        except anthropic.APIConnectionError as exc:
            raise TransientLLMError(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            error_cls = TransientLLMError if exc.status_code in TRANSIENT_STATUS else LLMError
            raise error_cls(f"{exc.status_code}: {exc.message}") from exc

        text, calls, parsed = [], [], None
        for block in response.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                if block.name == RESPOND_TOOL:
                    parsed = block.input
                else:
                    calls.append(ToolCall(id=block.id, name=block.name, args=block.input))
        return LLMResult(
            text="".join(text),
            parsed=parsed,
            tool_calls=[] if parsed is not None else calls,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            provider=self.name,
            model=self.model,
            latency_ms=(perf_counter() - start) * 1000,
        )


def _convert(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.content,
            }
            previous = out[-1] if out else None
            if (
                previous
                and previous["role"] == "user"
                and isinstance(previous["content"], list)
                and previous["content"][0].get("type") == "tool_result"
            ):
                previous["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif message.role == "assistant":
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            content.extend(
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args}
                for c in message.tool_calls
            )
            out.append({"role": "assistant", "content": content or "(no content)"})
        else:
            out.append({"role": "user", "content": message.content})
    return out
