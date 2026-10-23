import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType}


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(128), index=True, default="default")
    request: Mapped[str] = mapped_column(Text)
    require_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    final_output: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    runs: Mapped[list["Run"]] = relationship(back_populates="task", order_by="Run.started_at")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    replay_of_checkpoint: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    task_type: Mapped[str | None] = mapped_column(String(64), index=True)
    plan: Mapped[dict[str, Any] | None]
    wm_snapshot: Mapped[dict[str, Any] | None]
    metrics: Mapped[dict[str, Any] | None]
    trace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    traceparent: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[Task] = relationship(back_populates="runs")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    subtask_id: Mapped[str | None] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(64), index=True)
    tool: Mapped[str] = mapped_column(String(128), index=True)
    input: Mapped[dict[str, Any] | None]
    output: Mapped[dict[str, Any] | None]
    success: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[float] = mapped_column(Float)
    span_id: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    subtask_id: Mapped[str | None] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(64), index=True)
    purpose: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    call_key: Mapped[str | None] = mapped_column(String(64), index=True)
    prompt_hash: Mapped[str] = mapped_column(String(64))
    messages: Mapped[dict[str, Any]]
    response: Mapped[dict[str, Any]]
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[float] = mapped_column(Float)
    replayed: Mapped[bool] = mapped_column(Boolean, default=False)
    span_id: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboxMessage(Base):
    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="email")
    recipient: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
