import json
from time import perf_counter
from typing import Any

import openai

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
    json_from_text,
    respond_tool,
)

TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504}


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, model: str, api_key: str, base_url: str | None = None) -> None:
        super().__init__(model)
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=180)

    def complete(self, request: LLMRequest) -> LLMResult:
        tools = [function_def(t.name, t.description, t.parameters) for t in request.tools]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": _convert(request.system, request.messages),
            "max_completion_tokens": request.max_tokens,
        }
        if request.response_schema is not None:
            respond = respond_tool(request.response_schema)
            tools.append(function_def(respond.name, respond.description, respond.parameters))
            kwargs["tool_choice"] = (
                "required"
                if request.tools
                else {"type": "function", "function": {"name": RESPOND_TOOL}}
            )
        if tools:
            kwargs["tools"] = tools

        start = perf_counter()
        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.APIConnectionError as exc:
            raise TransientLLMError(str(exc)) from exc
        except openai.APIStatusError as exc:
            error_cls = TransientLLMError if exc.status_code in TRANSIENT_STATUS else LLMError
            raise error_cls(f"{exc.status_code}: {exc.message}") from exc

        message = response.choices[0].message
        text = message.content or ""
        calls, parsed = [], None
        for call in message.tool_calls or []:
            args = parse_args(call.function.arguments)
            if call.function.name == RESPOND_TOOL:
                parsed = args
            else:
                calls.append(ToolCall(id=call.id, name=call.function.name, args=args))
        if request.response_schema is not None and parsed is None and not calls and text:
            try:
                parsed = json_from_text(text)
            except ValueError:
                parsed = None

        usage = response.usage
        return LLMResult(
            text=text,
            parsed=parsed,
            tool_calls=[] if parsed is not None else calls,
            usage=Usage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
            provider=self.name,
            model=self.model,
            latency_ms=(perf_counter() - start) * 1000,
        )


def function_def(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def parse_args(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return value if isinstance(value, dict) else {"value": value}


def _convert(system: str | None, messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
    for message in messages:
        if message.role == "tool":
            out.append(
                {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
            )
        elif message.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": message.content or None}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.args)},
                    }
                    for c in message.tool_calls
                ]
            out.append(entry)
        else:
            out.append({"role": "user", "content": message.content})
    return out
