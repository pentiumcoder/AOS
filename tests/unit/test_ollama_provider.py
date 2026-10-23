import json

import httpx
import pytest
from pydantic import BaseModel

from aos.llm.base import LLMError, LLMRequest, Message, ToolCall, ToolDef, TransientLLMError
from aos.llm.ollama_provider import OllamaProvider


class Answer(BaseModel):
    value: int


DB_QUERY = ToolDef(name="db_query", description="query", parameters={"type": "object"})


def provider_with(*replies: dict, status: int = 200) -> tuple[OllamaProvider, list[dict]]:
    bodies: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        reply = replies[min(len(bodies) - 1, len(replies) - 1)]
        return httpx.Response(status, json=reply)

    provider = OllamaProvider(
        "qwen2.5:7b",
        "http://ollama.test/v1",
        num_ctx=8192,
        temperature=0.1,
        transport=httpx.MockTransport(handle),
    )
    return provider, bodies


def reply(content: str = "", tool_calls: list | None = None) -> dict:
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"message": message, "prompt_eval_count": 40, "eval_count": 7}


def schema_request(**overrides) -> LLMRequest:
    fields = {
        "role": "data_analysis",
        "messages": [Message.user("which is fastest?")],
        "system": "be exact",
        "tools": [DB_QUERY],
        "schema_name": "Answer",
        "response_schema": Answer.model_json_schema(),
        "max_tokens": 512,
    }
    return LLMRequest(**{**fields, **overrides})


def test_sends_context_size_and_temperature_to_native_api():
    provider, bodies = provider_with(reply('{"value": 3}'))
    result = provider.complete(schema_request(tools=[]))
    assert result.parsed == {"value": 3}
    body = bodies[0]
    assert body["options"] == {"num_ctx": 8192, "temperature": 0.1, "num_predict": 512}
    assert body["format"] == Answer.model_json_schema()
    assert body["messages"][0] == {"role": "system", "content": "be exact"}
    assert (result.usage.input_tokens, result.usage.output_tokens) == (40, 7)


def test_tool_phase_offers_only_real_tools():
    call = {"function": {"name": "db_query", "arguments": {"sql": "SELECT 1"}}}
    provider, bodies = provider_with(reply(tool_calls=[call]))
    result = provider.complete(schema_request())
    assert [(c.name, c.args) for c in result.tool_calls] == [("db_query", {"sql": "SELECT 1"})]
    assert [t["function"]["name"] for t in bodies[0]["tools"]] == ["db_query"]
    assert "format" not in bodies[0]


def test_prose_reply_is_followed_by_schema_enforced_answer():
    provider, bodies = provider_with(reply("Qdrant is fastest."), reply('{"value": 7}'))
    result = provider.complete(schema_request())
    assert result.parsed == {"value": 7}
    assert len(bodies) == 2
    assert "tools" not in bodies[1] and bodies[1]["format"] == Answer.model_json_schema()
    assert bodies[1]["messages"][-2] == {"role": "assistant", "content": "Qdrant is fastest."}
    assert result.usage.input_tokens == 80


def test_tool_results_carry_tool_names():
    provider, bodies = provider_with(reply("done"))
    history = [
        Message.user("q"),
        Message.assistant("", [ToolCall(id="c1", name="db_query", args={"sql": "SELECT 1"})]),
        Message.tool("c1", "db_query", '{"rows": [[1]]}'),
    ]
    provider.complete(LLMRequest(role="research", messages=history))
    sent = bodies[0]["messages"]
    assert sent[1]["tool_calls"] == [
        {"function": {"name": "db_query", "arguments": {"sql": "SELECT 1"}}}
    ]
    assert sent[2] == {"role": "tool", "content": '{"rows": [[1]]}', "tool_name": "db_query"}


@pytest.mark.parametrize(("status", "error"), [(503, TransientLLMError), (400, LLMError)])
def test_http_errors_map_to_retryable_or_final(status, error):
    provider, _ = provider_with({"error": "boom"}, status=status)
    with pytest.raises(error):
        provider.complete(LLMRequest(role="research", messages=[Message.user("q")]))
