from pathlib import Path

import pytest
import yaml
from harness import VECTOR_REQUEST

pytestmark = pytest.mark.e2e

CONFIG = Path(__file__).resolve().parents[2] / "config"


def allowed_agents() -> dict[str, set[str]]:
    tools = yaml.safe_load((CONFIG / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    servers = yaml.safe_load((CONFIG / "mcp_servers.yaml").read_text(encoding="utf-8"))["servers"]
    allowed = {name: set(cfg["agents"]) for name, cfg in tools.items()}
    for server, cfg in servers.items():
        allowed[f"mcp__{server}__*"] = set(cfg["agents"])
    return allowed


def permitted(tool: str, agent: str, allowed: dict[str, set[str]]) -> bool:
    if tool.startswith("mcp__"):
        server = tool.split("__")[1]
        return agent in allowed.get(f"mcp__{server}__*", set())
    return agent in allowed.get(tool, set())


def test_specialists_use_only_their_own_tools(api):
    task = api.run(VECTOR_REQUEST)
    calls = api.get(f"/tasks/{task['id']}/tool-calls")
    allowed = allowed_agents()

    successful = [c for c in calls if c["success"]]
    assert all(permitted(c["tool"], c["agent"], allowed) for c in successful)
    used = {(c["agent"], c["tool"]) for c in successful}
    assert {
        ("research", "web_search"),
        ("data_analysis", "db_query"),
        ("data_analysis", "code_exec"),
        ("writing", "send_email"),
    } <= used
    [email] = [c for c in calls if c["tool"] == "send_email"]
    assert email["input"]["to"] == ["team@example.com"]


def test_failed_tool_calls_are_recorded(api):
    task = api.run("[test:retry] compute the mean")
    calls = api.get(f"/tasks/{task['id']}/tool-calls")
    assert [(c["tool"], c["success"]) for c in calls] == [("code_exec", False), ("code_exec", True)]
    assert "ZeroDivisionError" in calls[0]["error"]
