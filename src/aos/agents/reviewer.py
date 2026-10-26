import json
import re

from aos import context
from aos.agents.prompting import render, section
from aos.config import get_settings
from aos.llm import Message, get_llm
from aos.schemas import Review, ReviewVerdict, SpecialistResult, Subtask

NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
UNSUPPORTED_SCORE_CAP = 0.45


def review(
    subtask: Subtask, result: SpecialistResult, *, request: str, dep_outputs: dict[str, str]
) -> Review:
    settings = get_settings()
    upstream = "\n\n".join(f"### {sid}\n{output}" for sid, output in dep_outputs.items())
    sources = [request, subtask.description, *subtask.inputs.values(), *result.evidence]
    unsupported = unsupported_figures(result.output, [*sources, *dep_outputs.values()])
    check = (
        f"These figures appear in no tool result or input: {', '.join(unsupported)}"
        if unsupported
        else None
    )
    prompt = (
        f"Overall request:\n{request}\n\n"
        f"Subtask ({subtask.id}, {subtask.specialist}):\n{subtask.description}\n\n"
        f"Expected output:\n{subtask.expected_output}"
        + section("Outputs of earlier subtasks", upstream)
        + section("Tool results the specialist saw", "\n\n".join(result.evidence))
        + section(
            "Structured data it reported",
            json.dumps(result.data, sort_keys=True) if result.data else None,
        )
        + section("Automatic check", check)
        + f"\n\nWork to review:\n{result.output}"
    )
    with context.bind(agent="reviewer", attempt=result.attempt):
        verdict: ReviewVerdict = (
            get_llm("reviewer", "medium")
            .complete(
                [Message.user(prompt)],
                system=render("reviewer", approve_score=settings.review_approve_score),
                schema=ReviewVerdict,
                meta={
                    "purpose": "review",
                    "request": request,
                    "subtask_id": subtask.id,
                    "attempt": result.attempt,
                },
            )
            .parsed
        )
    approved = verdict.approved and verdict.score >= settings.review_approve_score
    score, issues = verdict.score, list(verdict.issues)
    if unsupported:
        # Invented figures are never approved, whatever the model concluded.
        approved = False
        score = min(score, UNSUPPORTED_SCORE_CAP)
        issues.insert(0, f"Figures not found in any tool result or input: {', '.join(unsupported)}")
    return Review(
        subtask_id=subtask.id,
        attempt=result.attempt,
        approved=approved,
        score=score,
        issues=issues,
        feedback=verdict.feedback,
    )


def unsupported_figures(text: str, sources: list[str]) -> list[str]:
    """Figures in text that no source contains, allowing for rounding and percentages."""
    known = [value for source in sources for value in _numbers(source)]
    flagged = []
    for raw in dict.fromkeys(match.rstrip(",") for match in NUMBER.findall(text)):
        value = _parse(raw)
        if value is None or (value.is_integer() and value < 10):
            continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if not any(_same(value, candidate, decimals) for candidate in known):
            flagged.append(raw)
    return flagged


def _numbers(text: str) -> list[float]:
    values = (_parse(match.rstrip(",")) for match in NUMBER.findall(text))
    return [value for value in values if value is not None]


def _parse(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _same(figure: float, source: float, decimals: int) -> bool:
    return any(round(candidate, decimals) == figure for candidate in (source, source * 100))
