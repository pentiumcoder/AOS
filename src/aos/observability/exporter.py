from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import StatusCode

from aos.db.models import Span
from aos.db.session import session_scope
from aos.logging import get_logger

log = get_logger(__name__)


class PostgresSpanExporter(SpanExporter):
    """Writes finished spans to the spans table that the trace explorer reads."""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            with session_scope() as session:
                for finished in spans:
                    session.merge(_row(finished))
        except Exception:
            log.exception("span export failed")
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def _row(finished: ReadableSpan) -> Span:
    attributes: dict[str, Any] = dict(finished.attributes or {})
    status = attributes.get("aos.status")
    if status is None:
        status = "failure" if finished.status.status_code == StatusCode.ERROR else "success"
    start, end = finished.start_time or 0, finished.end_time or 0
    return Span(
        span_id=f"{finished.context.span_id:016x}",
        trace_id=f"{finished.context.trace_id:032x}",
        parent_span_id=f"{finished.parent.span_id:016x}" if finished.parent else None,
        run_id=attributes.get("aos.run_id"),
        name=finished.name,
        status=str(status),
        start_time=_moment(start),
        end_time=_moment(end),
        duration_ms=(end - start) / 1e6,
        attributes={k: list(v) if isinstance(v, tuple) else v for k, v in attributes.items()},
        events=[
            {
                "name": item.name,
                "time": _moment(item.timestamp).isoformat(),
                "attributes": dict(item.attributes or {}),
            }
            for item in finished.events
        ],
    )


def _moment(nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(nanoseconds / 1e9, UTC)
