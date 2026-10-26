from typing import Any

import httpx

from aos.config import get_settings
from aos.db.models import Notification
from aos.db.session import session_scope
from aos.logging import get_logger

log = get_logger(__name__)


def notify(escalation: dict[str, Any]) -> None:
    verb = "needs a decision" if escalation["status"] == "pending" else "was raised"
    message = (
        f"[{escalation['level']}] {escalation['trigger'].replace('_', ' ')} {verb}: "
        f"{escalation['reason']}"
    )
    with session_scope() as session:
        session.add(Notification(escalation_id=escalation["id"], message=message))
    webhook = get_settings().notify_webhook_url
    if not webhook:
        return
    payload = {
        "text": message,
        "escalation_id": escalation["id"],
        "run_id": escalation["run_id"],
        "level": escalation["level"],
    }
    try:
        httpx.post(webhook, json=payload, timeout=5)
    except httpx.HTTPError as exc:
        log.warning("notification webhook failed", extra={"fields": {"error": str(exc)}})
