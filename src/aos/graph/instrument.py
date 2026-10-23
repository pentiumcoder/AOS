import functools
from collections.abc import Callable
from time import perf_counter
from typing import Any

from langgraph.errors import GraphInterrupt

from aos import context
from aos.logging import get_logger

log = get_logger("aos.graph")


def traced_node(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Bind run context around a graph node and log its outcome and duration."""

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
            with context.bind(**fields):
                start = perf_counter()
                log.info("node started")
                try:
                    update = fn(state)
                except GraphInterrupt:
                    log.info("node paused for input")
                    raise
                except Exception:
                    duration = (perf_counter() - start) * 1000
                    log.exception("node failed", extra={"fields": {"duration_ms": duration}})
                    raise
                duration = (perf_counter() - start) * 1000
                log.info("node finished", extra={"fields": {"duration_ms": round(duration, 1)}})
                return update

        return wrapper

    return decorate
