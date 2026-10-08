"""Local OpenTelemetry traces, safe structured events; no global or external exporter."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TextIO

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Span, get_current_span


class ObservationError(Exception):
    pass


class Observer:
    def __init__(self, stream: TextIO | None = None) -> None:
        self.events: list[dict[str, str | int | float]] = []
        self._stream = stream
        self._exporter = InMemorySpanExporter()
        self._provider = TracerProvider()
        self._provider.add_span_processor(SimpleSpanProcessor(self._exporter))
        self._tracer = self._provider.get_tracer("modam-agi", "0.2.0")

    @contextmanager
    def span(self, name: str) -> Iterator[Span]:
        with self._tracer.start_as_current_span(
            name, record_exception=False, set_status_on_exception=False
        ) as span:
            yield span

    def emit(
        self,
        event: str,
        *,
        request_id: str,
        run_id: str,
        trace_id: str,
        status: str,
        model_calls: int = 0,
        tool_calls: int = 0,
        duration_ms: float = 0,
        error_code: str | None = None,
    ) -> None:
        current = get_current_span()
        span_context = current.get_span_context()
        parent = getattr(current, "parent", None)
        row: dict[str, str | int | float] = {
            "span_id": f"{span_context.span_id:016x}",
            "parent_span_id": f"{parent.span_id:016x}" if parent is not None else "",
            "step": event.split(".")[0],
            "timestamp": datetime.now(UTC).isoformat(),
            "event_name": event,
            "request_id": request_id,
            "run_id": run_id,
            "trace_id": trace_id,
            "status": status,
            "model_calls": model_calls,
            "tool_calls": tool_calls,
            "duration_ms": duration_ms,
        }
        if error_code is not None:
            row["error_code"] = error_code
        if self._stream is not None:
            try:
                self._stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                self._stream.flush()
            except (OSError, RuntimeError):
                raise ObservationError("observability_unavailable") from None
        self.events.append(row)

    def spans(self) -> tuple[ReadableSpan, ...]:
        return self._exporter.get_finished_spans()

    def close(self) -> None:
        self._provider.shutdown()
