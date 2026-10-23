import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from mcp import Client, StdioServerParameters

from aos.config import ROOT_DIR
from aos.logging import get_logger
from aos.tools.base import ToolContext, ToolError, ToolSpec

log = get_logger(__name__)


@dataclass
class McpServer:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    agents: list[str] = field(default_factory=list)
    rate_limit_per_min: int = 60
    timeout_s: float = 30.0

    def params(self) -> StdioServerParameters:
        command = sys.executable if self.command in ("python", "python3") else self.command
        args = [str(ROOT_DIR / a) if (ROOT_DIR / a).is_file() else a for a in self.args]
        return StdioServerParameters(command=command, args=args, env=self.env, cwd=str(ROOT_DIR))


def tool_name(server: str, tool: str) -> str:
    # Provider APIs only accept [A-Za-z0-9_-] in tool names.
    return f"mcp__{server}__{tool}"


def load_servers(path: Path) -> list[McpServer]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [McpServer(name=name, **cfg) for name, cfg in (data.get("servers") or {}).items()]


def _run_sync(coro_factory: Any) -> Any:
    # Each call gets its own event loop on a worker thread, so this is safe to call from
    # sync graph nodes and from inside a running loop such as the API.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro_factory())).result()


async def _list_tools(server: McpServer) -> list[Any]:
    async with Client(server.params()) as client:
        return list((await client.list_tools()).tools)


async def _call_tool(server: McpServer, name: str, arguments: dict[str, Any]) -> Any:
    async with Client(server.params(), read_timeout_seconds=server.timeout_s) as client:
        return await client.call_tool(name, arguments)


def _handler(server: McpServer, name: str):
    def handle(args: dict[str, Any], ctx: ToolContext) -> Any:
        result = _run_sync(lambda: _call_tool(server, name, args))
        text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        if result.is_error:
            raise ToolError(text or f"{name} failed")
        if result.structured_content:
            return result.structured_content
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}

    return handle


def register_mcp_tools(registry: Any, config_path: Path) -> list[str]:
    registered = []
    for server in load_servers(config_path):
        try:
            tools = _run_sync(lambda server=server: _list_tools(server))
        except Exception as exc:
            log.warning(
                "mcp server unavailable",
                extra={"fields": {"server": server.name, "error": str(exc)}},
            )
            continue
        for tool in tools:
            name = tool_name(server.name, tool.name)
            registry.register(
                ToolSpec(
                    name=name,
                    description=tool.description or tool.name,
                    handler=_handler(server, tool.name),
                    input_schema=tool.input_schema,
                    allowed_agents=frozenset(server.agents),
                    rate_limit_per_min=server.rate_limit_per_min,
                    timeout_s=server.timeout_s + 10,
                )
            )
            registered.append(name)
    return registered
