import contextvars
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from aos import context
from aos.config import get_settings
from aos.llm.base import ToolDef
from aos.logging import get_logger
from aos.observability import tracing
from aos.tools.base import ToolContext, ToolError, ToolResult, ToolSpec
from aos.tools.config import tool_config
from aos.tools.ratelimit import RateLimiter

log = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="tool")
MAX_LOGGED_CHARS = 50_000


class ToolRegistry:
    def __init__(self, limiter: RateLimiter | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._limiter = limiter or RateLimiter()

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def can_use(self, agent: str, name: str) -> bool:
        spec = self._tools.get(name)
        return spec is not None and agent in spec.allowed_agents

    def is_sensitive(self, name: str) -> bool:
        spec = self._tools.get(name)
        return spec is not None and spec.sensitive

    def list_for(self, agent: str) -> list[ToolDef]:
        return [self._tools[n].tool_def() for n in self.names() if self.can_use(agent, n)]

    def validate_args(self, name: str, args: dict[str, Any]) -> str | None:
        spec = self._tools.get(name)
        if spec is None:
            return f"unknown tool: {name}"
        try:
            _parse_input(spec, args)
        except ToolError as exc:
            return str(exc)
        return None

    def invoke(self, agent: str, name: str, args: dict[str, Any]) -> ToolResult:
        with tracing.span("tool.invoke", tool=name, agent=agent):
            result = self._replayed(agent, name, args) or self._invoke(agent, name, args)
            tracing.annotate(
                success=result.success,
                latency_ms=round(result.latency_ms, 1),
                error=result.error,
                status="success" if result.success else "warning",
            )
            _record(agent, name, args, result)
            return result

    def _replayed(self, agent: str, name: str, args: dict[str, Any]) -> ToolResult | None:
        from aos.replay.recorder import active_session

        replay = active_session(context.get("run_id"))
        if replay is None:
            return None
        if self.is_sensitive(name):
            tracing.annotate(replayed=True)
            return ToolResult(tool=name, success=True, output={"skipped": "not run during replay"})
        recorded = replay.tool_output(context.get("subtask_id"), agent, name, args)
        if recorded is None:
            return None
        tracing.annotate(replayed=True)
        return ToolResult(tool=name, **recorded)

    def _invoke(self, agent: str, name: str, args: dict[str, Any]) -> ToolResult:
        start = perf_counter()
        output: Any = None
        error: str | None = None
        try:
            spec = self._tools.get(name)
            if spec is None:
                raise ToolError(f"unknown tool: {name}")
            if agent not in spec.allowed_agents:
                raise ToolError(f"{agent} is not allowed to use {name}")
            parsed = _parse_input(spec, args)
            if not self._limiter.allow(name, spec.rate_limit_per_min):
                raise ToolError(f"rate limit of {spec.rate_limit_per_min}/min reached for {name}")
            output = _dump_output(spec, self._run(spec, parsed, agent))
        except ToolError as exc:
            error = str(exc)
        except Exception as exc:
            log.exception("tool crashed", extra={"fields": {"tool": name}})
            error = f"{type(exc).__name__}: {exc}"

        return ToolResult(
            tool=name,
            success=error is None,
            output=output,
            error=error,
            latency_ms=(perf_counter() - start) * 1000,
        )

    def _run(self, spec: ToolSpec, parsed: Any, agent: str) -> Any:
        run_id = context.get("run_id")
        ctx = ToolContext(agent=agent, run_id=run_id, workspace=workspace_for(run_id))
        future = _executor.submit(contextvars.copy_context().run, spec.handler, parsed, ctx)
        try:
            return future.result(timeout=spec.timeout_s)
        except FutureTimeout as exc:
            raise ToolError(f"{spec.name} timed out after {spec.timeout_s:g}s") from exc


def workspace_for(run_id: str | None) -> Path:
    path = get_settings().workspace_dir / (run_id or "adhoc")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_input(spec: ToolSpec, args: dict[str, Any]) -> Any:
    if not isinstance(args, dict):
        raise ToolError(f"arguments for {spec.name} must be an object")
    if spec.input_model is None:
        return args
    try:
        return spec.input_model.model_validate(args)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'args'}: {e['msg']}" for e in exc.errors()
        )
        raise ToolError(f"invalid arguments for {spec.name}: {problems}") from exc


def _dump_output(spec: ToolSpec, raw: Any) -> Any:
    if spec.output_model is not None:
        payload = raw.model_dump() if isinstance(raw, BaseModel) else raw
        return spec.output_model.model_validate(payload).model_dump(mode="json")
    if isinstance(raw, BaseModel):
        return raw.model_dump(mode="json")
    return raw


def _jsonable(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    text = json.dumps(value, default=str)
    if len(text) > MAX_LOGGED_CHARS:
        return {"truncated": text[:MAX_LOGGED_CHARS]}
    loaded = json.loads(text)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _record(agent: str, name: str, args: dict[str, Any], result: ToolResult) -> None:
    from aos.db.models import ToolCall
    from aos.db.session import session_scope

    try:
        with session_scope() as session:
            session.add(
                ToolCall(
                    run_id=context.get("run_id"),
                    subtask_id=context.get("subtask_id"),
                    agent=agent,
                    tool=name,
                    input=_jsonable(args),
                    output=_jsonable(result.output),
                    success=result.success,
                    error=result.error,
                    latency_ms=result.latency_ms,
                    span_id=tracing.current_span_id(),
                )
            )
    except Exception:
        log.exception("failed to record tool call", extra={"fields": {"tool": name}})


def build_registry() -> ToolRegistry:
    from aos.tools.builtin import builtin_tools
    from aos.tools.mcp_adapter import register_mcp_tools

    overrides = tool_config().get("tools", {})
    registry = ToolRegistry()
    for spec in builtin_tools():
        config = overrides.get(spec.name)
        if config is None or config.get("enabled", True) is False:
            continue
        spec.allowed_agents = frozenset(config.get("agents", []))
        spec.rate_limit_per_min = config.get("rate_limit_per_min", spec.rate_limit_per_min)
        spec.timeout_s = config.get("timeout_s", spec.timeout_s)
        spec.sensitive = config.get("sensitive", spec.sensitive)
        registry.register(spec)
    if get_settings().mcp_enabled:
        register_mcp_tools(registry, get_settings().config_dir / "mcp_servers.yaml")
    return registry


_registry: ToolRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> ToolRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = build_registry()
        return _registry


def reset_registry() -> None:
    global _registry
    with _registry_lock:
        _registry = None
    tool_config.cache_clear()
