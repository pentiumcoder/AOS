import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from aos import context
from aos.agents import reviewer
from aos.config import get_settings
from aos.graph.helpers import dep_outputs, load_plan, load_results
from aos.graph.instrument import traced_node
from aos.graph.routing import failure_escalation, review_escalation
from aos.schemas import Review
from aos.schemas.state import event


@traced_node("review")
def review_node(state: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    plan, results = load_plan(state), load_results(state)
    status = dict(state.get("subtask_status") or {})
    reviews = {k: list(v) for k, v in (state.get("reviews") or {}).items()}
    failures = dict(state.get("failures") or {})
    revisions = dict(state.get("revisions") or {})
    feedback: dict[str, str] = {}
    hints: dict[str, str] = {}
    pending: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    to_review = [sid for sid, value in status.items() if value == "awaiting_review"]
    verdicts = _review_all(state["request"], plan, results, to_review)

    for sid in to_review:
        verdict = verdicts[sid]
        reviews[sid] = [*reviews.get(sid, []), verdict.model_dump()]
        if verdict.approved:
            status[sid] = "done"
            events.append(_event(sid, "approved", verdict))
            continue
        used = revisions.get(sid, 0)
        if used < settings.max_revisions:
            status[sid] = "needs_revision"
            revisions[sid] = used + 1
            feedback[sid] = _feedback_text(verdict)
            events.append(_event(sid, "rejected", verdict))
        elif escalation := review_escalation(verdict):
            status[sid] = "escalate"
            pending.append(escalation)
            events.append(_event(sid, "escalated", verdict))
        else:
            status[sid] = "done"
            events.append(_event(sid, "accepted after max revisions", verdict))

    for sid in [sid for sid, value in status.items() if value == "errored"]:
        count = failures.get(sid, 0) + 1
        failures[sid] = count
        error = results[sid].error
        if escalation := failure_escalation(sid, count, error):
            status[sid] = "escalate"
            pending.append(escalation)
            events.append(
                event("review", "escalated", f"{sid} failed {count} times", subtask_id=sid)
            )
        else:
            status[sid] = "retry"
            hints[sid] = f"The previous attempt failed: {error}. Use a different tool or approach."
            events.append(
                event("review", "retry", f"{sid} failed ({error}); retrying", subtask_id=sid)
            )

    return {
        "subtask_status": status,
        "reviews": reviews,
        "failures": failures,
        "revisions": revisions,
        "feedback": feedback,
        "approach_hints": hints,
        "pending_escalations": pending,
        "events": events,
    }


def _review_all(
    request: str, plan: Any, results: dict[str, Any], subtask_ids: list[str]
) -> dict[str, Review]:
    if not subtask_ids:
        return {}

    def review_one(sid: str) -> Review:
        subtask = plan.subtask(sid)
        with context.bind(subtask_id=sid):
            return reviewer.review(
                subtask, results[sid], request=request, dep_outputs=dep_outputs(subtask, results)
            )

    with ThreadPoolExecutor(max_workers=len(subtask_ids)) as pool:
        futures = {
            sid: pool.submit(contextvars.copy_context().run, review_one, sid) for sid in subtask_ids
        }
        return {sid: future.result() for sid, future in futures.items()}


def _feedback_text(review: Review) -> str:
    issues = "\n".join(f"- {issue}" for issue in review.issues)
    return f"{review.feedback}\n{issues}".strip()


def _event(sid: str, outcome: str, review: Review) -> dict[str, Any]:
    detail = f": {review.issues[0]}" if review.issues and not review.approved else ""
    return event(
        "review",
        "review",
        f"{sid} {outcome} (score {review.score:.2f}){detail}",
        subtask_id=sid,
        score=review.score,
    )
