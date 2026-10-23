import uuid
from time import perf_counter
from typing import Any

import httpx

from aos.llm.base import (
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResult,
    Message,
    ToolCall,
    TransientLLMError,
    Usage,
    json_from_text,
)
from aos.llm.openai_provider import function_def, parse_args

TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}
FINAL_ANSWER_PROMPT = "Give your final answer now, as JSON in the required structure."


class OllamaProvider(LLMProvider):
    """Local models through Ollama's native chat API.

    The native API is used rather than the OpenAI-compatible one because only it accepts
    num_ctx and sampling options; the compatible endpoint runs every model at 4096 tokens
    of context and temperature 0.8.
    """

    name = "ollama"

    def __init__(
        self,
        model: str,
        base_url: str,
        *,
        num_ctx: int = 8192,
        temperature: float = 0.2,
        keep_alive: str = "15m",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(model)
        self._client = httpx.Client(
            base_url=base_url.rstrip("/").removesuffix("/v1"), timeout=300, transport=transport
        )
        self._options = {"num_ctx": num_ctx, "temperature": temperature}
        self._keep_alive = keep_alive

    def complete(self, request: LLMRequest) -> LLMResult:
        if request.response_schema is not None and request.tools:
            return self._tools_then_answer(request)
        return self._chat(request)

    def _tools_then_answer(self, request: LLMRequest) -> LLMResult:
        # Small models often stuff a final answer into a real tool call when an answer tool
        # sits next to it. Offer only the real tools, and once the model replies in prose,
        # ask again with the JSON schema enforced by Ollama's format option.
        first = self._chat(request.model_copy(update={"response_schema": None}))
        if first.tool_calls:
            return first
        draft = [Message.assistant(first.text)] if first.text.strip() else []
        final = self._chat(
            request.model_copy(
                update={
                    "tools": [],
                    "messages": [*request.messages, *draft, Message.user(FINAL_ANSWER_PROMPT)],
                }
            )
        )
        final.usage = Usage(
            input_tokens=first.usage.input_tokens + final.usage.input_tokens,
            output_tokens=first.usage.output_tokens + final.usage.output_tokens,
        )
        final.latency_ms += first.latency_ms
        return final

    def _chat(self, request: LLMRequest) -> LLMResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": _convert(request.system, request.messages),
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {**self._options, "num_predict": request.max_tokens},
        }
        if request.tools:
            body["tools"] = [
                function_def(t.name, t.description, t.parameters) for t in request.tools
            ]
        elif request.response_schema is not None:
            body["format"] = request.response_schema

        start = perf_counter()
        try:
            response = self._client.post("/api/chat", json=body)
        except httpx.TransportError as exc:
            raise TransientLLMError(f"ollama unreachable: {exc}") from exc
        if response.status_code >= 400:
            error_cls = TransientLLMError if response.status_code in TRANSIENT_STATUS else LLMError
            raise error_cls(f"{response.status_code}: {response.text[:300]}")

        data = response.json()
        message = data.get("message") or {}
        text = message.get("content") or ""
        calls = [
            ToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name=call["function"]["name"],
                args=parse_args(call["function"].get("arguments")),
            )
            for call in message.get("tool_calls") or []
        ]
        parsed = None
        if "format" in body and text:
            try:
                parsed = json_from_text(text)
            except ValueError:
                parsed = None
        return LLMResult(
            text=text,
            parsed=parsed,
            tool_calls=calls,
            usage=Usage(
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            ),
            provider=self.name,
            model=self.model,
            latency_ms=(perf_counter() - start) * 1000,
        )


def _convert(system: str | None, messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
    for message in messages:
        if message.role == "tool":
            out.append({"role": "tool", "content": message.content, "tool_name": message.name})
        elif message.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {"function": {"name": c.name, "arguments": c.args}} for c in message.tool_calls
                ]
            out.append(entry)
        else:
            out.append({"role": "user", "content": message.content})
    return out
