import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langgraph.errors import GraphInterrupt
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from aos import context
from aos.config import get_settings

STATUS = "aos.status"
_propagator = TraceContextTextMapPropagator()
_provider: TracerProvider | None = None
_lock = threading.Lock()
# The span of the graph invocation currently running each run. LangGraph runs nodes on
# its own worker threads, so node spans attach here rather than to the thread's context.
_run_contexts: dict[str, Context] = {}


def provider() -> TracerProvider:
    global _provider
    with _lock:
        if _provider is None:
            from aos.observability.exporter import PostgresSpanExporter

            settings = get_settings()
            _provider = TracerProvider(
                resource=Resource.create({"service.name": settings.otel_service_name})
            )
            # Batched; the runner flushes after every graph invocation, so a finished run's
            # spans are in the table before anyone asks for its trace.
            _provider.add_span_processor(
                BatchSpanProcessor(PostgresSpanExporter(), schedule_delay_millis=500)
            )
            if settings.otel_exporter_otlp_endpoint:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces"
                _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint)))
        return _provider


def tracer() -> trace.Tracer:
    return provider().get_tracer("aos")


def flush() -> None:
    provider().force_flush()


def reset_tracing() -> None:
    global _provider
    with _lock:
        if _provider is not None:
            _provider.shutdown()
        _provider = None
        _run_contexts.clear()


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Span]:
    """Open a span under the current one, or under the run's invocation span."""
    run_id = attributes.pop("run_id", None) or context.get("run_id")
    current = trace.get_current_span().get_span_context()
    parent = None if current.is_valid or run_id is None else _run_contexts.get(run_id)
    initial = _clean({"aos.run_id": run_id, STATUS: "success", **_named(attributes)})
    with tracer().start_as_current_span(
        name,
        context=parent,
        attributes=initial,
        record_exception=False,
        set_status_on_exception=False,
    ) as current_span:
        try:
            yield current_span
        except GraphInterrupt:
            current_span.set_attribute(STATUS, "escalated")
            raise
        except Exception as exc:
            current_span.set_attribute(STATUS, "failure")
            current_span.record_exception(exc)
            raise


@contextmanager
def run_span(run_id: str, task_id: str, *, resume: bool, traceparent: str | None) -> Iterator[Span]:
    """Span one graph invocation. A resumed run joins the trace of its first invocation."""
    parent = Context()
    if resume and traceparent:
        parent = _propagator.extract({"traceparent": traceparent})
    name = "task.resume" if resume else "task.run"
    attributes = {"aos.run_id": run_id, "aos.task_id": task_id, STATUS: "success"}
    with tracer().start_as_current_span(
        name,
        context=parent,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as root:
        _run_contexts[run_id] = trace.set_span_in_context(root)
        try:
            yield root
        except Exception as exc:
            root.set_attribute(STATUS, "failure")
            root.record_exception(exc)
            raise
        finally:
            _run_contexts.pop(run_id, None)


def annotate(**attributes: Any) -> None:
    trace.get_current_span().set_attributes(_clean(_named(attributes)))


def traceparent(target: Span) -> str:
    carrier: dict[str, str] = {}
    _propagator.inject(carrier, context=trace.set_span_in_context(target))
    return carrier["traceparent"]


def trace_id(target: Span) -> str:
    return f"{target.get_span_context().trace_id:032x}"


def current_span_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    return f"{span_context.span_id:016x}" if span_context.is_valid else None


def _named(attributes: dict[str, Any]) -> dict[str, Any]:
    """Keyword names use underscores for dots: escalation__level -> aos.escalation.level."""
    return {
        key if key.startswith("aos.") else "aos." + key.replace("__", "."): value
        for key, value in attributes.items()
    }


def _clean(attributes: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, bool | int | float | str):
            cleaned[key] = value
        elif isinstance(value, list | tuple) and all(isinstance(v, str) for v in value):
            cleaned[key] = list(value)
        else:
            cleaned[key] = json.dumps(value, default=str)
    return cleaned
