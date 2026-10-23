import time

import pytest
from pydantic import BaseModel

from aos import context
from aos.db.models import ToolCall
from aos.tools import ToolError, ToolRegistry, ToolSpec
from aos.tools.registry import get_registry


class Empty(BaseModel):
    pass


def spec(name: str, handler, **kwargs) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=name,
        handler=handler,
        input_model=Empty,
        allowed_agents=frozenset({"code"}),
        **kwargs,
    )


def test_agent_without_permission_is_refused():
    result = get_registry().invoke("writing", "db_query", {"sql": "SELECT 1"})
    assert not result.success
    assert result.error == "writing is not allowed to use db_query"


def test_unknown_tool_and_invalid_arguments():
    registry = get_registry()
    assert registry.invoke("code", "rm_rf", {}).error == "unknown tool: rm_rf"
    error = registry.invoke("research", "web_search", {"query": "x", "max_results": 50}).error
    assert error.startswith("invalid arguments for web_search")


def test_rate_limit_trips_after_quota():
    registry = ToolRegistry()
    registry.register(spec("ping", lambda args, ctx: "pong", rate_limit_per_min=2))
    outcomes = [registry.invoke("code", "ping", {}).success for _ in range(3)]
    assert outcomes == [True, True, False]
    assert "rate limit of 2/min" in registry.invoke("code", "ping", {}).error


def test_handler_errors_and_timeouts_are_returned_not_raised():
    def broken(args, ctx):
        raise RuntimeError("disk on fire")

    def expected_failure(args, ctx):
        raise ToolError("nothing to do")

    registry = ToolRegistry()
    registry.register(spec("broken", broken))
    registry.register(spec("refuses", expected_failure))
    registry.register(spec("slow", lambda args, ctx: time.sleep(2), timeout_s=0.2))
    assert registry.invoke("code", "broken", {}).error == "RuntimeError: disk on fire"
    assert registry.invoke("code", "refuses", {}).error == "nothing to do"
    assert registry.invoke("code", "slow", {}).error == "slow timed out after 0.2s"


def test_every_call_is_logged(db):
    registry = get_registry()
    with context.bind(run_id="run-7", subtask_id="s1"):
        registry.invoke("code", "code_exec", {"code": "print(1)"})
        registry.invoke("writing", "code_exec", {"code": "print(1)"})
    rows = db.query(ToolCall).order_by(ToolCall.created_at).all()
    assert [(r.agent, r.success, r.run_id) for r in rows] == [
        ("code", True, "run-7"),
        ("writing", False, "run-7"),
    ]
    assert rows[0].output["stdout"] == "1\n"


def test_workspace_files_cannot_escape():
    registry = get_registry()
    with context.bind(run_id="run-files"):
        assert registry.invoke("code", "file_write", {"path": "out/a.txt", "content": "hi"}).success
        read = registry.invoke("code", "file_read", {"path": "out/a.txt"})
        escaped = registry.invoke("code", "file_write", {"path": "../../x.txt", "content": "x"})
    assert read.output["content"] == "hi"
    assert escaped.error == "path escapes the workspace: ../../x.txt"


def test_code_exec_success_failure_and_timeout():
    registry = get_registry()
    ok = registry.invoke("code", "code_exec", {"code": "print(6 * 7)"})
    crash = registry.invoke("code", "code_exec", {"code": "raise SystemExit(3)"})
    slow = registry.invoke("code", "code_exec", {"code": "while True: pass", "timeout_s": 1})
    assert ok.output["stdout"] == "42\n"
    assert crash.error.startswith("exit code 3")
    assert slow.error == "code timed out after 1s"


def test_code_exec_does_not_inherit_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")
    code = "import os; print(os.environ.get('ANTHROPIC_API_KEY'))"
    result = get_registry().invoke("code", "code_exec", {"code": code})
    assert result.output["stdout"] == "None\n"


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("DELETE FROM benchmarks", "only SELECT queries are allowed"),
        ("SELECT 1; DROP TABLE benchmarks", "only one statement is allowed"),
        ("WITH x AS (DELETE FROM benchmarks RETURNING *) SELECT * FROM x", "keyword not allowed"),
    ],
)
def test_db_query_refuses_writes(sql, error):
    result = get_registry().invoke("data_analysis", "db_query", {"sql": sql})
    assert error in result.error


def test_db_query_reads_demo_benchmarks():
    sql = "SELECT database, qps FROM benchmarks WHERE database LIKE 'M%' ORDER BY qps DESC"
    result = get_registry().invoke("data_analysis", "db_query", {"sql": sql})
    assert result.output["rows"] == [["Milvus", 4200]]


def test_http_get_enforces_allowlist():
    result = get_registry().invoke("research", "http_get", {"url": "https://evil.example.com/x"})
    assert result.error == "evil.example.com is not on the HTTP allowlist"


def test_sensitive_flags_come_from_specs():
    registry = get_registry()
    assert registry.is_sensitive("send_email")
    assert registry.is_sensitive("file_delete")
    assert not registry.is_sensitive("web_search")


@pytest.mark.mcp
def test_mcp_tools_are_discovered_and_callable(monkeypatch):
    from aos.config import get_settings
    from aos.tools.mcp_adapter import register_mcp_tools

    registry = ToolRegistry()
    names = register_mcp_tools(registry, get_settings().config_dir / "mcp_servers.yaml")
    assert "mcp__demo__unit_convert" in names
    assert "mcp__demo__unit_convert" in [d.name for d in registry.list_for("research")]
    result = registry.invoke(
        "research", "mcp__demo__unit_convert", {"value": 3, "from_unit": "km", "to_unit": "m"}
    )
    assert result.output == {"value": 3000.0, "unit": "m"}
    bad = registry.invoke(
        "research", "mcp__demo__unit_convert", {"value": 1, "from_unit": "kg", "to_unit": "km"}
    )
    assert not bad.success
