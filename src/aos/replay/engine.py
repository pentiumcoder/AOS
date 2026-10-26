from typing import Any

from sqlalchemy import select

from aos.db.models import LLMCall, Run, Task
from aos.db.session import session_scope
from aos.graph.runner import create_task, execute_run, run_state
from aos.replay.recorder import Mode, activate, deactivate, load_session

PREVIEW = 160


def list_steps(run_id: str) -> list[dict[str, Any]]:
    """Every model decision of a run, in order: the points a replay can change."""
    with session_scope() as session:
        calls = session.scalars(
            select(LLMCall).where(LLMCall.run_id == run_id).order_by(LLMCall.created_at)
        ).all()
        return [
            {
                "index": index,
                "id": call.id,
                "agent": call.agent,
                "purpose": call.purpose,
                "subtask_id": call.subtask_id,
                "attempt": (call.messages.get("meta") or {}).get("attempt"),
                "call_key": call.call_key,
                "replayed": call.replayed,
                "preview": _preview(call.response),
                "response": call.response,
            }
            for index, call in enumerate(calls)
        ]


def prepare_replay(parent_run_id: str, request: str | None = None) -> tuple[str, str]:
    with session_scope() as session:
        parent = session.get(Run, parent_run_id)
        if parent is None:
            raise KeyError(parent_run_id)
        task = session.get(Task, parent.task_id)
        fields = (request or task.request, task.user_id, task.require_human_review)
    task_id, run_id = create_task(*fields)
    with session_scope() as session:
        run = session.get(Run, run_id)
        run.parent_run_id = parent_run_id
        run.replay_of_checkpoint = "replay"
    return task_id, run_id


def run_replay(
    run_id: str,
    parent_run_id: str,
    mode: Mode = "recorded",
    overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    with session_scope() as session:
        parent = session.get(Run, parent_run_id)
        thread_id = parent.thread_id
    memory_context = run_state(thread_id).get("memory_context")
    replay = load_session(run_id, parent_run_id, mode, overrides or {}, memory_context)
    activate(replay)
    try:
        final = execute_run(run_id)
    finally:
        deactivate(run_id)
    with session_scope() as session:
        run = session.get(Run, run_id)
        run.metrics = {**(run.metrics or {}), "replay": replay.summary()}
    return final


def replay(
    parent_run_id: str,
    mode: Mode = "recorded",
    overrides: dict[str, dict[str, Any]] | None = None,
    request: str | None = None,
) -> tuple[str, dict[str, Any]]:
    _, run_id = prepare_replay(parent_run_id, request)
    return run_id, run_replay(run_id, parent_run_id, mode, overrides)


def _preview(response: dict[str, Any]) -> str:
    if response.get("tool_calls"):
        calls = ", ".join(f"{c['name']}({_short(c.get('args'))})" for c in response["tool_calls"])
        return f"calls {calls}"[:PREVIEW]
    if response.get("parsed") is not None:
        return _short(response["parsed"])
    return (response.get("text") or "")[:PREVIEW]


def _short(value: Any) -> str:
    import json

    return json.dumps(value, default=str)[:PREVIEW]
