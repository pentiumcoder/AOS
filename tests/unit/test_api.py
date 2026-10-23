import pytest
from fastapi.testclient import TestClient

from aos.api.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_modes(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert (body["llm_mode"], body["storage_mode"]) == ("mock", "memory")


def test_submit_task_runs_and_reports_progress(client):
    response = client.post(
        "/tasks",
        json={"request": "[test:retry] compute the mean", "user_id": "alice"},
    )
    assert response.status_code == 202
    task_id = response.json()["task_id"]

    detail = client.get(f"/tasks/{task_id}").json()
    assert detail["status"] == "completed"
    assert detail["final_output"].strip() == "The mean is 5.0"
    [subtask] = detail["run"]["subtasks"]
    assert (subtask["id"], subtask["status"], subtask["attempts"]) == ("s1", "done", 2)

    calls = client.get(f"/tasks/{task_id}/tool-calls").json()
    assert [(c["tool"], c["success"]) for c in calls] == [("code_exec", False), ("code_exec", True)]
    assert [t["id"] for t in client.get("/tasks", params={"user_id": "alice"}).json()] == [task_id]


def test_rejects_empty_request_and_unknown_task(client):
    assert client.post("/tasks", json={"request": ""}).status_code == 422
    assert client.get("/tasks/does-not-exist").status_code == 404
