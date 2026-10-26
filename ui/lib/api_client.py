import os
from typing import Any

import httpx

DEFAULT_URL = os.environ.get("API_URL", "http://localhost:8000")


class ApiError(Exception):
    pass


class Api:
    """Thin client for the AOS REST API. The UI never touches the database directly."""

    def __init__(self, base_url: str = DEFAULT_URL) -> None:
        self.base_url = base_url
        self._client = httpx.Client(base_url=base_url, timeout=60)

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(f"API unreachable at {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ApiError(f"{response.status_code}: {detail}")
        return response.json() if response.content else None

    def health(self) -> dict[str, Any]:
        return self._call("GET", "/health")

    def tasks(self, user_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if user_id:
            params["user_id"] = user_id
        return self._call("GET", "/tasks", params=params)

    def task(self, task_id: str) -> dict[str, Any]:
        return self._call("GET", f"/tasks/{task_id}")

    def submit(self, request: str, user_id: str, require_review: bool) -> dict[str, Any]:
        body = {"request": request, "user_id": user_id, "require_human_review": require_review}
        return self._call("POST", "/tasks", json=body)

    def escalations(self, status: str = "pending") -> list[dict[str, Any]]:
        return self._call("GET", "/escalations", params={"status": status})

    def escalation(self, escalation_id: str) -> dict[str, Any]:
        return self._call("GET", f"/escalations/{escalation_id}")

    def decide(
        self,
        escalation_id: str,
        action: str,
        *,
        payload: Any = None,
        comment: str = "",
        reviewer: str = "reviewer",
    ) -> dict[str, Any]:
        body = {"action": action, "payload": payload, "comment": comment, "reviewer": reviewer}
        return self._call("POST", f"/escalations/{escalation_id}/decision", json=body)

    def chat(self, escalation_id: str, message: str) -> dict[str, Any]:
        return self._call("POST", f"/escalations/{escalation_id}/chat", json={"message": message})

    def memories(self, user_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        params = {"kind": kind} if kind else {}
        return self._call("GET", f"/users/{user_id}/memories", params=params)

    def delete_memory(self, memory_id: str) -> None:
        self._call("DELETE", f"/memories/{memory_id}")

    def forget(self, user_id: str) -> dict[str, Any]:
        return self._call("DELETE", f"/users/{user_id}/memories")

    def maintain(self, user_id: str | None = None) -> dict[str, Any]:
        params = {"user_id": user_id} if user_id else {}
        return self._call("POST", "/memory/maintenance", params=params)
