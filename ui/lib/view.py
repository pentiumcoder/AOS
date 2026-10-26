from datetime import UTC, datetime

import streamlit as st

from lib.api_client import Api

STATUS_COLOR = {
    "queued": "gray",
    "running": "blue",
    "awaiting_human": "orange",
    "completed": "green",
    "failed": "red",
}
LEVEL_COLOR = {
    "NOTIFY": "blue",
    "APPROVE_ACTION": "orange",
    "APPROVE_PLAN": "violet",
    "TAKE_OVER": "red",
}


@st.cache_resource
def api() -> Api:
    return Api()


def words(value: str) -> str:
    return value.replace("_", " ")


def status_badge(status: str) -> str:
    return f":{STATUS_COLOR.get(status, 'gray')}-badge[{words(status)}]"


def level_badge(level: str) -> str:
    return f":{LEVEL_COLOR.get(level, 'gray')}-badge[{words(level)}]"


def age(timestamp: str | None) -> str:
    if not timestamp:
        return ""
    moment = datetime.fromisoformat(timestamp)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    seconds = int((datetime.now(UTC) - moment).total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86_400}d ago"


def subtask_rows(run: dict) -> list[dict]:
    return [
        {
            "id": s["id"],
            "specialist": s["specialist"],
            "status": words(s["status"]),
            "attempts": s["attempts"],
            "after": ", ".join(s["depends_on"]),
            "description": s["description"],
        }
        for s in run.get("subtasks", [])
    ]
