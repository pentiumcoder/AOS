from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from aos.tools.base import ToolContext, ToolError
from aos.tools.config import http_allowlist


class HttpGetInput(BaseModel):
    url: str = Field(max_length=2000)
    max_chars: int = Field(default=20_000, ge=100, le=100_000)


def http_get(args: HttpGetInput, ctx: ToolContext) -> dict:
    parsed = urlparse(args.url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError("only http and https URLs are allowed")
    host = (parsed.hostname or "").lower()
    allowed = http_allowlist()
    if not any(host == domain or host.endswith(f".{domain}") for domain in allowed):
        raise ToolError(f"{host or 'url'} is not on the HTTP allowlist")
    try:
        # Redirects are not followed so a response can never leave the allowlist.
        response = httpx.get(args.url, timeout=10, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise ToolError(f"request failed: {exc}") from exc
    return {
        "url": args.url,
        "status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "location": response.headers.get("location"),
        "text": response.text[: args.max_chars],
    }
