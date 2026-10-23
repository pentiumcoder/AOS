from typing import Any

from aos.graph.instrument import traced_node


@traced_node("retrieve_memory")
def retrieve_memory(state: dict[str, Any]) -> dict[str, Any]:
    return {"memory_context": None}


@traced_node("persist_memory")
def persist_memory(state: dict[str, Any]) -> dict[str, Any]:
    return {}
