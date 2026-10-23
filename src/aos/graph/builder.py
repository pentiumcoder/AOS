import threading

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from aos.graph import nodes, routing
from aos.graph.checkpointer import get_checkpointer
from aos.schemas.state import SpecialistTask, TaskState


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    graph = StateGraph(TaskState)
    graph.add_node("intake", nodes.intake)
    graph.add_node("retrieve_memory", nodes.retrieve_memory)
    graph.add_node("plan", nodes.plan_node)
    graph.add_node("schedule", nodes.schedule)
    graph.add_node("run_specialist", nodes.run_specialist, input_schema=SpecialistTask)
    graph.add_node("review", nodes.review_node)
    graph.add_node("synthesize", nodes.synthesize)
    graph.add_node("execute_actions", nodes.execute_actions)
    graph.add_node("escalate", nodes.escalate)
    graph.add_node("deliver", nodes.deliver)
    graph.add_node("persist_memory", nodes.persist_memory)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "retrieve_memory")
    graph.add_edge("retrieve_memory", "plan")
    graph.add_conditional_edges("plan", routing.after_plan, ["escalate", "schedule", "deliver"])
    graph.add_conditional_edges(
        "schedule", routing.dispatch, ["run_specialist", "synthesize", "deliver"]
    )
    graph.add_edge("run_specialist", "review")
    graph.add_conditional_edges("review", routing.after_review, ["escalate", "schedule"])
    graph.add_conditional_edges(
        "synthesize", routing.after_synthesize, ["escalate", "execute_actions"]
    )
    graph.add_conditional_edges("execute_actions", routing.after_actions, ["escalate", "deliver"])
    graph.add_conditional_edges(
        "escalate", routing.after_escalation, ["schedule", "execute_actions", "deliver"]
    )
    graph.add_edge("deliver", "persist_memory")
    graph.add_edge("persist_memory", END)
    return graph.compile(checkpointer=checkpointer)


_graph: CompiledStateGraph | None = None
_lock = threading.Lock()


def get_graph() -> CompiledStateGraph:
    global _graph
    with _lock:
        if _graph is None:
            _graph = build_graph(get_checkpointer())
        return _graph


def reset_graph() -> None:
    global _graph
    with _lock:
        _graph = None
