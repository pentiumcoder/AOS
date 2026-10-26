import pytest
from harness import VECTOR_REQUEST

pytestmark = pytest.mark.e2e


def test_failed_attempt_is_retried_with_another_approach(api):
    task = api.run("[test:retry] compute the mean")
    [subtask] = task["run"]["subtasks"]
    assert (subtask["status"], subtask["attempts"]) == ("done", 2)
    assert task["final_output"].strip() == "The mean is 5.0"
    assert any("retrying" in e["message"] for e in task["run"]["events"])


def test_second_failure_hands_the_subtask_to_a_human(api):
    def take_over(escalation):
        return {"action": "take_over", "payload": "March sales: 1,240 units", "reviewer": "e2e"}

    task = api.run("[test:fail-twice] sales summary", decide=take_over)
    statuses = {s["id"]: s["status"] for s in task["run"]["subtasks"]}
    assert statuses == {"s1": "done", "s2": "done"}
    assert "March sales: 1,240 units" in task["final_output"]


def test_paused_run_resumes_after_a_restart(api):
    task_id = api.submit(VECTOR_REQUEST)
    [waiting] = api.wait(task_id)["run"]["pending_escalations"]
    if not api.services:
        from aos.graph.builder import reset_graph

        # In-process stand-in for a restart: the compiled graph is rebuilt from scratch and
        # must pick the run up from its checkpoint. Against the stack, a separate worker
        # process does the resuming anyway.
        reset_graph()
    api.post(f"/escalations/{waiting['id']}/decision", {"action": "approve"})
    api.wait_until_not_paused(task_id)
    task = api.wait(task_id)
    assert task["status"] == "completed"
    assert [a["status"] for a in task["run"]["actions"]] == ["executed"]


def test_model_outage_falls_back_to_the_next_provider(api, monkeypatch):
    if api.services:
        pytest.skip("needs to swap model providers inside the API process")
    from aos.llm import router
    from aos.llm.base import LLMError, LLMProvider
    from aos.llm.mock_provider import MockProvider

    class Down(LLMProvider):
        name = "down"

        def complete(self, request):
            raise LLMError("503 service unavailable")

    monkeypatch.setattr(router, "providers_for", lambda *a: [Down("primary"), MockProvider()])
    task = api.run("[test:retry] compute the mean")
    assert task["status"] == "completed"
    metrics = api.get(f"/runs/{task['run']['id']}/metrics")
    assert set(metrics["llm"]["by_model"]) == {"mock:mock-1"}
