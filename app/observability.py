"""Tracing, metrics, and structured logging."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from time import perf_counter
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from app.config import Settings

REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")

REGISTRY = CollectorRegistry()
REQUEST_COUNT = Counter(
    "memgauge_http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
    registry=REGISTRY,
)
REQUEST_LATENCY_SECONDS = Histogram(
    "memgauge_http_request_latency_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
    registry=REGISTRY,
)
OPERATION_LATENCY_SECONDS = Histogram(
    "memgauge_memory_operation_latency_seconds",
    "Memory operation latency in seconds.",
    ["operation"],
    registry=REGISTRY,
)
EVAL_RECALL_AT_5 = Gauge(
    "memgauge_eval_recall_at_5",
    "Latest evaluation recall@5.",
    registry=REGISTRY,
)
EVAL_PASSED = Gauge(
    "memgauge_eval_passed",
    "Latest evaluation pass status, 1 for pass and 0 for fail.",
    registry=REGISTRY,
)

_configured = False


class JsonFormatter(logging.Formatter):
    """Small JSON formatter that carries request and trace context."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": REQUEST_ID.get(),
            "trace_id": TRACE_ID.get(),
        }
        for field in ("method", "path", "status_code", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"))


def configure_observability(settings: Settings) -> None:
    """Configure logging and tracing once per process."""

    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

    resource = Resource.create({"service.name": "memgauge-api"})
    provider = TracerProvider(resource=resource)
    if settings.otel_exporter_otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stdout)))
    trace.set_tracer_provider(provider)

    _configured = True


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("memgauge")


def set_request_context(request_id: str, trace_id: str) -> None:
    REQUEST_ID.set(request_id)
    TRACE_ID.set(trace_id)


def get_request_id() -> str:
    return REQUEST_ID.get()


def get_trace_id() -> str:
    return TRACE_ID.get()


def record_operation_latency(operation: str, started_at: float) -> None:
    OPERATION_LATENCY_SECONDS.labels(operation=operation).observe(perf_counter() - started_at)
