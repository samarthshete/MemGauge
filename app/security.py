"""Phase 7 security: bearer-token auth, per-client rate limiting, CORS wiring.

Public vs. protected policy (intentional — see ROADMAP R5):

* **PUBLIC** (no token): ``/healthz`` and ``/metrics`` (liveness probes and the
  Prometheus scraper must work unauthenticated), plus the read-only surfaces
  ``GET /report/{id}``, ``GET /v1/eval/runs``, ``GET /v1/memories`` and
  ``GET /v1/memories/search``. This is a benchmark/demo service: reads are safe to
  expose, and keeping ops/observability open avoids breaking probes and scrapes.
* **PROTECTED** (bearer token): every mutation / expensive operation —
  ``POST /v1/memories``, ``DELETE /v1/memories/{id}`` and ``POST /v1/eval/run``.

The token is compared in constant time against ``settings.memgauge_api_token``.
Rate limiting and the cache both **fail open** (never surface a 500 from infra
failure), mirroring the Redis cache behavior in ``app/routers/memories.py``.
"""

from __future__ import annotations

import secrets
import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis

# auto_error=False so a missing header yields ``None`` (our own 401) rather than
# FastAPI's default 403, and so we can return a ``WWW-Authenticate`` challenge.
_bearer_scheme = HTTPBearer(auto_error=False)
_BEARER_DEPENDENCY = Depends(_bearer_scheme)

# Probes and the metrics scraper must never be rate limited or authenticated.
PUBLIC_PATHS: frozenset[str] = frozenset({"/healthz", "/metrics"})


async def require_token(
    credentials: HTTPAuthorizationCredentials | None = _BEARER_DEPENDENCY,
) -> None:
    """FastAPI dependency enforcing a bearer token on protected routes.

    Raises 401 when the ``Authorization: Bearer <token>`` header is missing or
    does not match ``MEMGAUGE_API_TOKEN``. Imported lazily so settings reflect the
    current environment (and stay overridable in tests).
    """

    from app.config import get_settings

    expected = get_settings().memgauge_api_token
    presented = credentials.credentials if credentials is not None else ""
    scheme_ok = credentials is not None and credentials.scheme.lower() == "bearer"
    # constant-time compare avoids leaking the token via response timing.
    if not scheme_ok or not secrets.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_or_missing_token",
            headers={"WWW-Authenticate": "Bearer"},
        )


class RateLimiter:
    """Fixed-window per-client rate limiter that always fails open.

    Prefers a Redis counter (shared across workers) and falls back to an
    in-memory window when Redis is unreachable. Any backend error results in the
    request being *allowed* — the limiter never raises, so it can never turn an
    infra hiccup into a 500 (consistent with the fail-open cache).
    """

    def __init__(self, *, limit: int, redis_url: str, window_seconds: int = 60) -> None:
        self.limit = limit
        self.redis_url = redis_url
        self.window_seconds = window_seconds
        # client_id -> (count, window_start_epoch)
        self._memory: dict[str, tuple[int, float]] = {}

    async def allow(self, client_id: str) -> bool:
        """Return True if the client may proceed. Never raises (fail-open)."""

        if self.limit <= 0:
            # A non-positive limit disables rate limiting entirely.
            return True
        try:
            return await self._allow_redis(client_id)
        except Exception:
            try:
                return self._allow_memory(client_id)
            except Exception:
                return True

    async def _allow_redis(self, client_id: str) -> bool:
        client = Redis.from_url(self.redis_url, socket_connect_timeout=1, socket_timeout=1)
        try:
            window = int(time.time()) // self.window_seconds
            key = f"ratelimit:{client_id}:{window}"
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, self.window_seconds)
            return int(count) <= self.limit
        finally:
            await client.aclose()

    def _allow_memory(self, client_id: str) -> bool:
        now = time.time()
        window_start = now - (now % self.window_seconds)
        count, start = self._memory.get(client_id, (0, window_start))
        if start != window_start:
            count, start = 0, window_start
        count += 1
        self._memory[client_id] = (count, start)
        return count <= self.limit


def build_rate_limit_middleware(limiter: RateLimiter):  # type: ignore[no-untyped-def]
    """Build an HTTP middleware that enforces ``limiter`` per client IP.

    Exempts ``PUBLIC_PATHS`` (health/metrics) so probes and scrapes are never
    throttled. Over the limit returns 429; on any limiter error it serves the
    request (fail-open).
    """

    async def rate_limit_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        client_id = request.client.host if request.client else "anonymous"
        if not await limiter.allow(client_id):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"error": "rate_limited", "detail": "Too Many Requests"},
            )
        return await call_next(request)

    return rate_limit_middleware
