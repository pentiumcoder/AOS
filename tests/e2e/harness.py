import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from fastapi.testclient import TestClient

VECTOR_REQUEST = (
    "Research the top 3 open-source vector databases, compare them using our benchmark "
    "data, write an executive summary and email it to the team"
)
FINISHED = ("completed", "failed")

Decide = Callable[[dict[str, Any]], dict[str, Any]]


def approve(escalation: dict[str, Any]) -> dict[str, Any]:
    if escalation["level"] == "TAKE_OVER":
        return {"action": "take_over", "payload": "Provided by the reviewer", "reviewer": "e2e"}
    return {"action": "approve", "reviewer": "e2e"}


class Api:
    """Drives the system over HTTP, either in-process or against a running stack."""

    def __init__(self, client: httpx.Client | TestClient, services: bool) -> None:
        self.client = client
        self.services = services
        self.user = f"e2e-{uuid.uuid4().hex[:8]}"

    def get(self, path: str, **params: Any) -> Any:
        response = self.client.get(path, params=params or None)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, body: dict[str, Any]) -> Any:
        response = self.client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    def submit(self, request: str, **fields: Any) -> str:
        body = {"request": request, "user_id": self.user, **fields}
        return self.post("/tasks", body)["task_id"]

    def wait(self, task_id: str, timeout: float = 180) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            task = self.get(f"/tasks/{task_id}")
            if task["status"] in (*FINISHED, "awaiting_human"):
                return task
            if time.monotonic() > deadline:
                raise TimeoutError(f"task {task_id} still {task['status']}")
            time.sleep(0.5)

    def finish(self, task_id: str, decide: Decide = approve) -> dict[str, Any]:
        for _ in range(10):
            task = self.wait(task_id)
            if task["status"] in FINISHED:
                return task
            for waiting in task["run"]["pending_escalations"]:
                escalation = self.get(f"/escalations/{waiting['id']}")
                self.post(f"/escalations/{waiting['id']}/decision", decide(escalation))
            self.wait_until_not_paused(task_id)
        raise AssertionError(f"task {task_id} kept asking for decisions")

    def wait_until_not_paused(self, task_id: str, timeout: float = 60) -> None:
        deadline = time.monotonic() + timeout
        while self.get(f"/tasks/{task_id}")["status"] == "awaiting_human":
            if time.monotonic() > deadline:
                raise TimeoutError(f"task {task_id} did not resume")
            time.sleep(0.5)

    def run(self, request: str, decide: Decide = approve, **fields: Any) -> dict[str, Any]:
        return self.finish(self.submit(request, **fields), decide)
