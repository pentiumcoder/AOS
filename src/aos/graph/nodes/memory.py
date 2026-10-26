from typing import Any

from aos.graph.instrument import traced_node
from aos.logging import get_logger
from aos.memory.extraction import remember_run
from aos.memory.retrieval import SECTIONS, retrieve_for_planning
from aos.schemas.state import event

log = get_logger(__name__)


@traced_node("retrieve_memory")
def retrieve_memory(state: dict[str, Any]) -> dict[str, Any]:
    try:
        recalled = retrieve_for_planning(
            state.get("user_id") or "default", state["request"], run_id=state["run_id"]
        )
    except Exception as exc:
        log.exception("memory retrieval failed")
        return {
            "memory_context": None,
            "events": [event("retrieve_memory", "error", f"memory unavailable: {exc}")],
        }
    if recalled.is_empty():
        return {
            "memory_context": None,
            "events": [event("retrieve_memory", "memory", "no relevant memories")],
        }
    counts = ", ".join(
        f"{len(getattr(recalled, field))} {title.lower()}"
        for field, title in SECTIONS
        if getattr(recalled, field)
    )
    return {
        "memory_context": recalled.model_dump(mode="json"),
        "events": [event("retrieve_memory", "memory", f"recalled {counts}")],
    }


@traced_node("persist_memory")
def persist_memory(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("plan") is None:
        return {}
    try:
        stored = remember_run(state)
    except Exception as exc:
        # The deliverable is already saved; losing a memory must not fail the run.
        log.exception("memory persistence failed")
        return {"events": [event("persist_memory", "error", f"memory not saved: {exc}")]}
    merged = sum(1 for _, was_merged in stored if was_merged)
    kinds = ", ".join(sorted({memory.kind for memory, _ in stored}))
    return {
        "events": [
            event(
                "persist_memory",
                "memory",
                f"saved {len(stored) - merged} new and strengthened {merged} existing "
                f"memories ({kinds})",
            )
        ]
    }
