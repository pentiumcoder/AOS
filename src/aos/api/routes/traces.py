from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from aos.db.models import LLMCall, Run, Span, ToolCall
from aos.db.session import session_scope

router = APIRouter(tags=["traces"])


class SpanNode(BaseModel):
    span_id: str
    parent_span_id: str | None
    name: str
    status: str
    start_time: datetime
    duration_ms: float
    attributes: dict[str, Any]
    events: list[dict[str, Any]]
    children: list["SpanNode"] = []


class RunTrace(BaseModel):
    run_id: str
    trace_id: str | None
    span_count: int
    roots: list[SpanNode]


class SpanDetail(SpanNode):
    trace_id: str
    llm_calls: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]


@router.get("/runs/{run_id}/trace", response_model=RunTrace)
def run_trace(run_id: str) -> RunTrace:
    with session_scope() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        if run.trace_id is None:
            return RunTrace(run_id=run_id, trace_id=None, span_count=0, roots=[])
        rows = session.scalars(
            select(Span).where(Span.trace_id == run.trace_id).order_by(Span.start_time)
        ).all()
        nodes = {row.span_id: _node(row) for row in rows}
        trace_id = run.trace_id
    roots = []
    for node in nodes.values():
        parent = nodes.get(node.parent_span_id or "")
        (parent.children if parent else roots).append(node)
    return RunTrace(run_id=run_id, trace_id=trace_id, span_count=len(nodes), roots=roots)


@router.get("/spans/{span_id}", response_model=SpanDetail)
def span_detail(span_id: str) -> SpanDetail:
    with session_scope() as session:
        row = session.get(Span, span_id)
        if row is None:
            raise HTTPException(404, "span not found")
        llm_calls = session.scalars(select(LLMCall).where(LLMCall.span_id == span_id)).all()
        tool_calls = session.scalars(select(ToolCall).where(ToolCall.span_id == span_id)).all()
        return SpanDetail(
            **_node(row).model_dump(),
            trace_id=row.trace_id,
            llm_calls=[_llm_call(call) for call in llm_calls],
            tool_calls=[_tool_call(call) for call in tool_calls],
        )


def _node(row: Span) -> SpanNode:
    return SpanNode(
        span_id=row.span_id,
        parent_span_id=row.parent_span_id,
        name=row.name,
        status=row.status,
        start_time=row.start_time,
        duration_ms=row.duration_ms,
        attributes=row.attributes or {},
        events=row.events or [],
    )


def _llm_call(call: LLMCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "agent": call.agent,
        "purpose": call.purpose,
        "provider": call.provider,
        "model": call.model,
        "messages": call.messages,
        "response": call.response,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
        "cost_usd": call.cost_usd,
        "latency_ms": call.latency_ms,
        "replayed": call.replayed,
    }


def _tool_call(call: ToolCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "agent": call.agent,
        "tool": call.tool,
        "input": call.input,
        "output": call.output,
        "success": call.success,
        "error": call.error,
        "latency_ms": call.latency_ms,
    }
