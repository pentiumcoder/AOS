import json
import re
import threading
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

from aos import context
from aos.config import get_settings
from aos.llm.base import LLMProvider, LLMRequest, LLMResult, ToolCall, Usage

_TOKEN = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

DEFAULT_REVIEW = {
    "approved": True,
    "score": 0.86,
    "issues": [],
    "feedback": "Meets the expected output.",
}


class MockProvider(LLMProvider):
    """Deterministic responses scripted per scenario in tests/fixtures/mock_llm/*.yaml.

    A scenario is chosen by matching its `match` keywords against the task request.
    Specialist scripts are indexed by attempt, then by tool step within the attempt.
    """

    name = "mock"
    _lock = threading.Lock()
    _counters: dict[tuple[str, str], int] = {}
    _scripts: list[dict[str, Any]] | None = None

    def __init__(self, model: str = "mock-1") -> None:
        super().__init__(model)

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._counters.clear()
            cls._scripts = None

    @classmethod
    def scripts(cls) -> list[dict[str, Any]]:
        with cls._lock:
            if cls._scripts is None:
                cls._scripts = _load_scripts(get_settings().fixtures_dir / "mock_llm")
            return cls._scripts

    def complete(self, request: LLMRequest) -> LLMResult:
        start = perf_counter()
        script = self._script_for(str(request.meta.get("request", "")))
        purpose = request.meta.get("purpose", "default")
        handler = getattr(self, f"_{purpose}", self._default)
        text, parsed, calls = handler(script, request)
        output_chars = len(text) + (len(json.dumps(parsed)) if parsed is not None else 0)
        input_chars = len(request.system or "") + sum(len(m.content) for m in request.messages)
        return LLMResult(
            text=text,
            parsed=parsed,
            tool_calls=calls,
            usage=Usage(input_tokens=input_chars // 4 + 1, output_tokens=output_chars // 4 + 1),
            provider=self.name,
            model=self.model,
            latency_ms=(perf_counter() - start) * 1000,
        )

    def _script_for(self, task_request: str) -> dict[str, Any]:
        lowered = task_request.lower()
        scripts = self.scripts()
        for script in scripts:
            if any(keyword.lower() in lowered for keyword in script.get("match", [])):
                return script
        return next((s for s in scripts if s["name"] == "generic"), {"name": "empty"})

    def _next(self, purpose: str, request: LLMRequest) -> int:
        key = (context.get("run_id") or str(request.meta.get("request", "")), purpose)
        with self._lock:
            index = self._counters.get(key, 0)
            self._counters[key] = index + 1
        return index

    def _plan(self, script, request):
        entries = script.get("plan") or []
        if not entries:
            raise KeyError(f"mock scenario {script['name']} has no plan")
        index = self._next("plan", request)
        return "", _render(_pick(entries, index), _base_ctx(request)), []

    def _synthesize(self, script, request):
        entries = script.get("synthesize")
        outputs = request.meta.get("outputs", {})
        if not entries:
            return "\n\n".join(str(v) for v in outputs.values()), None, []
        index = self._next("synthesize", request)
        return _render(_pick(entries, index), _base_ctx(request)), None, []

    def _specialist(self, script, request):
        meta = request.meta
        subtasks = script.get("subtasks", {})
        attempts = (
            subtasks.get(meta.get("subtask_id"))
            or subtasks.get(f"default_{meta.get('agent')}")
            or [{"steps": [{"final": {"output": "Completed: {{subtask}}", "confidence": 0.7}}]}]
        )
        steps = _pick(attempts, int(meta.get("attempt", 1)) - 1)["steps"]
        step_index = sum(1 for m in request.messages if m.role == "assistant" and m.tool_calls)
        step = _pick(steps, step_index)
        ctx = _base_ctx(request)
        if "tool" in step:
            call = ToolCall(
                id=f"call_{meta.get('subtask_id')}_{step_index}",
                name=step["tool"],
                args=_render(step.get("args", {}), ctx),
            )
            return step.get("say", ""), None, [call]
        return "", _render(step["final"], ctx), []

    def _review(self, script, request):
        reviews = script.get("review", {})
        entries = reviews.get(request.meta.get("subtask_id")) or reviews.get("default")
        attempt = int(request.meta.get("attempt", 1)) - 1
        verdict = _pick(entries, attempt) if entries else DEFAULT_REVIEW
        return "", _render(verdict, _base_ctx(request)), []

    def _default(self, script, request):
        entries = script.get(str(request.meta.get("purpose")))
        if entries:
            return "", _render(_pick(entries, self._next("default", request)), {}), []
        return "ok", None, []


def _load_scripts(directory: Path) -> list[dict[str, Any]]:
    scripts = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data["name"] = path.stem
        scripts.append(data)
    return scripts


def _pick(entries: list[Any], index: int) -> Any:
    return entries[min(max(index, 0), len(entries) - 1)]


def _base_ctx(request: LLMRequest) -> dict[str, Any]:
    tool_messages = [m for m in request.messages if m.role == "tool"]
    last = tool_messages[-1].content if tool_messages else ""
    try:
        parsed = json.loads(last) if last else {}
    except json.JSONDecodeError:
        parsed = {}
    return {**request.meta, "tool_output": last, "tool_result": parsed}


def _lookup(ctx: dict[str, Any], path: str) -> Any:
    value: Any = ctx
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    return value


def _render(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: _render(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, ctx) for v in value]
    if not isinstance(value, str):
        return value

    def substitute(match: re.Match[str]) -> str:
        try:
            found = _lookup(ctx, match.group(1))
        except KeyError:
            return match.group(0)
        return found if isinstance(found, str) else json.dumps(found)

    return _TOKEN.sub(substitute, value)
