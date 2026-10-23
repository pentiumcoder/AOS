import re
from functools import lru_cache
from typing import Any

import httpx
import yaml
from pydantic import BaseModel, Field

from aos.config import get_settings
from aos.tools.base import ToolContext, ToolError

TAVILY_URL = "https://api.tavily.com/search"


class WebSearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=400)
    max_results: int = Field(default=5, ge=1, le=10)


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str


class WebSearchOutput(BaseModel):
    query: str
    source: str
    results: list[SearchHit]


def web_search(args: WebSearchInput, ctx: ToolContext) -> WebSearchOutput:
    settings = get_settings()
    if settings.llm_mode == "mock":
        hits, source = _fixture_hits(args.query), "fixtures"
    elif settings.tavily_api_key:
        hits, source = _tavily(args.query, args.max_results, settings.tavily_api_key), "tavily"
    else:
        hits, source = _duckduckgo(args.query, args.max_results), "duckduckgo"
    return WebSearchOutput(query=args.query, source=source, results=hits[: args.max_results])


@lru_cache
def _fixtures() -> list[dict[str, Any]]:
    path = get_settings().fixtures_dir / "web" / "search.yaml"
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def _fixture_hits(query: str) -> list[SearchHit]:
    lowered = query.lower()
    for entry in _fixtures():
        if any(keyword in lowered for keyword in entry.get("match", [])):
            return [SearchHit(**hit) for hit in entry["results"]]
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")[:60]
    return [
        SearchHit(
            title=f"Overview: {query}",
            url=f"https://example.org/articles/{slug}",
            snippet=f"Background and key facts on {query}.",
        ),
        SearchHit(
            title=f"{query}: practical guide",
            url=f"https://example.org/guides/{slug}",
            snippet=f"How practitioners approach {query}, with trade-offs and examples.",
        ),
    ]


def _tavily(query: str, limit: int, api_key: str) -> list[SearchHit]:
    try:
        response = httpx.post(
            TAVILY_URL,
            json={"query": query, "max_results": limit},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ToolError(f"tavily search failed: {exc}") from exc
    return [
        SearchHit(title=r.get("title", ""), url=r.get("url", ""), snippet=r.get("content", ""))
        for r in response.json().get("results", [])
    ]


def _duckduckgo(query: str, limit: int) -> list[SearchHit]:
    from ddgs import DDGS

    try:
        results = DDGS().text(query, max_results=limit)
    except Exception as exc:
        raise ToolError(f"duckduckgo search failed: {exc}") from exc
    return [
        SearchHit(title=r.get("title", ""), url=r.get("href", ""), snippet=r.get("body", ""))
        for r in results
    ]
