from aos.agents.reviewer import unsupported_figures
from aos.tools.builtin.db_query import summarize

ROWS = [["Milvus", 18.4, 1450.0], ["Qdrant", 14.9, 1180.0], ["pgvector", 34.8, 760.0]]


def test_summary_names_lowest_and_highest_rows():
    summary = summarize(["database", "p95_latency_ms", "monthly_cost_usd"], ROWS)
    assert summary["p95_latency_ms"]["lowest"] == {"value": 14.9, "database": "Qdrant"}
    assert summary["monthly_cost_usd"]["lowest"] == {"value": 760.0, "database": "pgvector"}
    assert summary["monthly_cost_usd"]["highest"]["database"] == "Milvus"
    assert "database" not in summary
    assert summarize(["database", "qps"], [["Milvus", 4200]]) == {}


def test_supported_figures_allow_commas_rounding_and_percentages():
    sources = ['{"rows": [["Milvus", 4200, 0.962, 0.13319]]}']
    text = "Milvus serves 4,200 QPS at 96.2% recall for $0.13 per million queries (s1, p95)."
    assert unsupported_figures(text, sources) == []


def test_invented_figures_are_flagged_and_small_counts_ignored():
    sources = ["Qdrant 14.9 ms, pgvector $760.00"]
    text = "- Qdrant: 14.9 ms\n- pgvector: $620.00\n- 3 options, top 2 compared in 2026."
    assert unsupported_figures(text, sources) == ["620.00", "2026"]
