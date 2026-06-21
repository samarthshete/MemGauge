"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.observability import (
    REQUEST_COUNT,
    REQUEST_LATENCY_SECONDS,
    configure_observability,
    get_trace_id,
    get_tracer,
    set_request_context,
)
from app.routers.eval import router as eval_router
from app.routers.health import router as health_router
from app.routers.memories import router as memories_router
from app.routers.report import router as report_router

settings = get_settings()
configure_observability(settings)
logger = logging.getLogger("memgauge.access")


def create_app() -> FastAPI:
    app = FastAPI(title="MemGauge", version="0.1.0")
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(health_router)
    app.include_router(memories_router)
    app.include_router(eval_router)
    app.include_router(report_router)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id", str(uuid4()))
        started_at = perf_counter()
        status_code = 500
        path = request.url.path

        with get_tracer().start_as_current_span(f"{request.method} {path}") as span:
            span_context = span.get_span_context()
            trace_id = f"{span_context.trace_id:032x}" if span_context.is_valid else request_id
            set_request_context(request_id=request_id, trace_id=trace_id)

            try:
                response = await call_next(request)
                status_code = response.status_code
                return response
            finally:
                duration = perf_counter() - started_at
                REQUEST_COUNT.labels(
                    method=request.method,
                    path=path,
                    status=str(status_code),
                ).inc()
                REQUEST_LATENCY_SECONDS.labels(method=request.method, path=path).observe(duration)
                logger.info(
                    "request_complete",
                    extra={
                        "method": request.method,
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": round(duration * 1000, 3),
                    },
                )
                if "response" in locals():
                    response.headers["x-request-id"] = request_id

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            extra={"method": request.method, "path": request.url.path, "status_code": 500},
        )
        trace_id = get_trace_id() or request.headers.get("x-request-id", "")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "trace_id": trace_id},
        )

    return app


app = create_app()
