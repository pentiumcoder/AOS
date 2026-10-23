"""Rules for sensitive tools that hold no matter what a model decides.

A sensitive tool may only be used when the user's request asks for that kind of action,
and send_email may only reach known contacts or addresses written in the request.
"""

import re
from typing import Any

from aos.tools.config import tool_config

EMAIL_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def requested(tool: str, request: str) -> bool:
    words = (tool_config().get("tools", {}).get(tool) or {}).get("requested_by") or []
    lowered = request.lower()
    return any(re.search(rf"\b{re.escape(word.lower())}", lowered) for word in words)


def email_directory() -> dict[str, str]:
    return dict(tool_config().get("email_directory") or {})


def allowed_recipients(request: str) -> set[str]:
    known = {address.lower() for address in email_directory().values()}
    return known | {address.lower() for address in EMAIL_ADDRESS.findall(request)}


def contacts_text(request: str) -> str:
    lines = [f"- {name}: {address}" for name, address in email_directory().items()]
    lines += [f"- {address}" for address in EMAIL_ADDRESS.findall(request)]
    return "\n".join(lines)


def check_action(tool: str, args: dict[str, Any], request: str) -> str | None:
    if not requested(tool, request):
        return f"the request does not ask for {tool}"
    if tool == "send_email":
        allowed = allowed_recipients(request)
        unknown = [str(a) for a in args.get("to") or [] if str(a).lower() not in allowed]
        if unknown:
            choices = ", ".join(sorted(allowed)) or "none"
            return f"recipient not allowed: {', '.join(unknown)}; allowed recipients: {choices}"
    return None
