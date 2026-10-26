import functools
from collections.abc import Callable
from time import perf_counter
from typing import Any

from langgraph.errors import GraphInterrupt

from aos import context
from aos.logging import get_logger
from aos.observability import tracing

log = get_logger("aos.graph")

WARNING_WORDS = ("rejected", "failed", "retrying", "blocked", "escalated", "not saved")
DECISION_CHARS = 400


def traced_node(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Run a graph node inside its own span, with run context bound for logs and tools."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(state: dict[str, Any]) -> Any:
            fields: dict[str, Any] = {
                "run_id": state.get("run_id"),
                "task_id": state.get("task_id"),
                "node": name,
            }
            subtask = state.get("subtask")
            if isinstance(subtask, dict):
                fields["subtask_id"] = subtask.get("id")
            attributes = {"node": name, "subtask_id": fields.get("subtask_id")}
            with context.bind(**fields), tracing.span(f"node.{name}", **attributes):
                start = perf_counter()
                try:
                    update = fn(state)
                except GraphInterrupt:
                    log.info("node paused for input")
                    raise
                except Exception:
                    duration = (perf_counter() - start) * 1000
                    log.exception("node failed", extra={"fields": {"duration_ms": duration}})
                    raise
                _summarise(name, update)
                duration = (perf_counter() - start) * 1000
                log.info("node finished", extra={"fields": {"duration_ms": round(duration, 1)}})
                return update

        return wrapper

    return decorate


def _summarise(name: str, update: Any) -> None:
    """Copy the node's own event messages onto its span as the decision it made."""
    events = update.get("events") if isinstance(update, dict) else None
    if not events:
        return
    messages = [item["message"] for item in events]
    decision = "; ".join(messages)[:DECISION_CHARS]
    if name == "escalate" and any(item["kind"] == "decision" for item in events):
        status = "escalated"
    elif any(word in message for message in messages for word in WARNING_WORDS):
        status = "warning"
    else:
        status = "success"
    tracing.annotate(decision=decision, status=status)
