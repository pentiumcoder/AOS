import difflib
from typing import Any

from aos.db.models import Run
from aos.db.session import session_scope
from aos.graph.runner import run_state
from aos.observability.costs import run_metrics

DIFF_LINES = 80


def compare(run_a: str, run_b: str) -> dict[str, Any]:
    """How run_b differs from run_a, step by step."""
    states, metrics, replay = {}, {}, None
    with session_scope() as session:
        for run_id in (run_a, run_b):
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            states[run_id] = run_state(run.thread_id)
            if run_id == run_b:
                replay = (run.metrics or {}).get("replay")
    for run_id in (run_a, run_b):
        metrics[run_id] = run_metrics(run_id)
    a, b = states[run_a], states[run_b]
    return {
        "run_a": run_a,
        "run_b": run_b,
        "replay": replay,
        "plan": _plan_changes(a.get("plan") or {}, b.get("plan") or {}),
        "subtasks": _subtasks(a, b),
        "escalations": {
            "a": [(e["trigger"], e.get("decision")) for e in a.get("escalations") or []],
            "b": [(e["trigger"], e.get("decision")) for e in b.get("escalations") or []],
        },
        "final_output": {
            "same": (a.get("final_output") or "") == (b.get("final_output") or ""),
            "diff": _diff(a.get("final_output"), b.get("final_output")),
        },
        "metrics": _metric_deltas(metrics[run_a], metrics[run_b]),
    }


def _plan_changes(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    left = {s["id"]: s for s in a.get("subtasks", [])}
    right = {s["id"]: s for s in b.get("subtasks", [])}
    changed = {
        sid: [
            k
            for k in ("description", "specialist", "depends_on", "expected_output")
            if left[sid].get(k) != right[sid].get(k)
        ]
        for sid in left.keys() & right.keys()
    }
    return {
        "same": left == right,
        "added": sorted(right.keys() - left.keys()),
        "removed": sorted(left.keys() - right.keys()),
        "changed": {sid: fields for sid, fields in sorted(changed.items()) if fields},
    }


def _subtasks(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    ids = list(dict.fromkeys([*(a.get("results") or {}), *(b.get("results") or {})]))
    for sid in ids:
        left = (a.get("results") or {}).get(sid) or {}
        right = (b.get("results") or {}).get(sid) or {}
        rows.append(
            {
                "id": sid,
                "status": [
                    (a.get("subtask_status") or {}).get(sid),
                    (b.get("subtask_status") or {}).get(sid),
                ],
                "visits": [(a.get("visits") or {}).get(sid), (b.get("visits") or {}).get(sid)],
                "scores": [_scores(a, sid), _scores(b, sid)],
                "same_output": left.get("output") == right.get("output"),
                "diff": _diff(left.get("output"), right.get("output")),
            }
        )
    return rows


def _scores(state: dict[str, Any], sid: str) -> list[float]:
    return [review["score"] for review in (state.get("reviews") or {}).get(sid, [])]


def _diff(left: str | None, right: str | None) -> list[str]:
    lines = difflib.unified_diff(
        (left or "").splitlines(), (right or "").splitlines(), "original", "replay", lineterm=""
    )
    return list(lines)[:DIFF_LINES]


def _metric_deltas(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "llm_calls": lambda m: m["llm"]["calls"],
        "replayed_calls": lambda m: m["llm"]["replayed"],
        "input_tokens": lambda m: m["llm"]["input_tokens"],
        "output_tokens": lambda m: m["llm"]["output_tokens"],
        "cost_usd": lambda m: m["llm"]["cost_usd"],
        "tool_calls": lambda m: m["tools"]["calls"],
        "wall_clock_seconds": lambda m: m["wall_clock_seconds"],
    }
    return {name: {"a": read(a), "b": read(b)} for name, read in fields.items()}
