import pytest
from fastapi.testclient import TestClient

from aos.api.main import app
from aos.db.models import LLMCall, Run
from aos.observability.costs import cost_of, price_for

VECTOR_REQUEST = (
    "Research the top 3 open-source vector databases, compare them using our benchmark "
    "data, write an executive summary and email it to the team"
)


def test_prices_come_from_model_then_provider():
    assert cost_of("mock", "mock-1", 1_000_000, 250_000) == pytest.approx(1.0 + 1.0)
    assert price_for("mock", "mock-1").simulated
    assert cost_of("ollama", "qwen2.5:7b", 50_000, 9_000) == 0.0
    assert cost_of("anthropic", "claude-sonnet-5-5", 1_000, 1_000) is None


def test_every_call_is_priced_and_the_run_is_summarised(db, finish):
    _, _, run_id = finish(VECTOR_REQUEST)
    calls = db.query(LLMCall).filter_by(run_id=run_id).all()
    assert all(
        c.cost_usd == pytest.approx(cost_of(c.provider, c.model, c.input_tokens, c.output_tokens))
        for c in calls
    )

    metrics = db.get(Run, run_id).metrics
    llm = metrics["llm"]
    assert llm["calls"] == len(calls)
    assert llm["input_tokens"] == sum(c.input_tokens for c in calls)
    assert llm["cost_usd"] == pytest.approx(sum(c.cost_usd for c in calls), abs=1e-6)
    assert llm["simulated_prices"] is True
    assert set(llm["by_agent"]) >= {
        "supervisor",
        "research",
        "data_analysis",
        "writing",
        "reviewer",
        "memory",
    }
    assert metrics["tools"]["by_tool"]["db_query"] == {"calls": 1, "failures": 0}
    assert metrics["escalations"] == 1
    assert metrics["human_review_seconds"] >= 0
    assert metrics["wall_clock_seconds"] >= metrics["agent_seconds"]


def test_summary_across_runs(finish):
    finish(VECTOR_REQUEST)
    finish("What is retrieval-augmented generation?")
    finish("[test:retry] compute the mean")
    with TestClient(app) as client:
        summary = client.get("/metrics/summary", params={"days": 1}).json()
        runs = summary["runs"]
        assert runs["total"] == 3
        assert runs["by_status"] == {"completed": 3}
        assert runs["escalation_rate"] == pytest.approx(1 / 3, abs=1e-3)
        types = {row["task_type"] for row in summary["cost_by_task_type"]}
        assert types == {"research_report", "research_summary", "calculation"}
        code = next(row for row in summary["tools"] if row["tool"] == "code_exec")
        assert code["calls"] == 3 and code["failure_rate"] == pytest.approx(1 / 3, abs=1e-3)
        assert summary["escalations"]["by_trigger"] == {"sensitive_operation": 1}
        assert sum(day["runs"] for day in summary["daily"]) == 3

        run_id = client.get("/tasks").json()[0]["id"]
        detail = client.get(f"/tasks/{run_id}").json()["run"]["id"]
        assert client.get(f"/runs/{detail}/metrics").json()["status"] == "completed"
        assert client.get("/runs/missing/metrics").status_code == 404
