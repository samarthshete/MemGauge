"""Tests for Phase 7 security: token auth, rate limiting, and CORS (ROADMAP R5).

Most cases run with no services (pure dependency / middleware behavior). The
full 401-vs-200 flow through a real protected route needs Postgres/Neo4j/Redis
and is marked ``integration``.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient

from app.security import RateLimiter, build_rate_limit_middleware, require_token

# A redis URL pointed at an unused port so _allow_redis fails fast and the
# limiter falls back to its in-memory window — deterministic, no live Redis.
UNREACHABLE_REDIS = "redis://127.0.0.1:6399/0"


# --------------------------------------------------------------------------- #
# Token auth (no services)
# --------------------------------------------------------------------------- #
async def test_require_token_rejects_missing_credentials() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_token(credentials=None)
    assert exc.value.status_code == 401


async def test_require_token_rejects_wrong_token() -> None:
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-the-token")
    with pytest.raises(HTTPException) as exc:
        await require_token(credentials=creds)
    assert exc.value.status_code == 401


async def test_require_token_accepts_correct_token() -> None:
    from app.config import get_settings

    token = get_settings().memgauge_api_token
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    # A matching token does not raise (the dependency returns None).
    await require_token(credentials=creds)


# --------------------------------------------------------------------------- #
# Rate limiting (no services)
# --------------------------------------------------------------------------- #
def _dummy_app(limiter: RateLimiter) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(build_rate_limit_middleware(limiter))

    @app.get("/ping")
    async def ping() -> dict[str, bool]:  # pragma: no cover - trivial
        return {"ok": True}

    return app


async def test_rate_limit_middleware_returns_429_over_limit() -> None:
    limiter = RateLimiter(limit=2, redis_url=UNREACHABLE_REDIS)
    app = _dummy_app(limiter)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/ping")).status_code == 200
        assert (await client.get("/ping")).status_code == 200
        # third call within the window exceeds RATE_LIMIT_PER_MIN -> 429
        assert (await client.get("/ping")).status_code == 429


async def test_rate_limiter_serves_when_redis_down() -> None:
    """Redis unreachable -> in-memory fallback still serves (no 500)."""

    limiter = RateLimiter(limit=5, redis_url=UNREACHABLE_REDIS)
    app = _dummy_app(limiter)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/ping")
    assert response.status_code == 200


async def test_rate_limiter_fails_open_when_both_backends_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If every backend raises, allow() returns True rather than propagating."""

    limiter = RateLimiter(limit=1, redis_url=UNREACHABLE_REDIS)

    async def boom_redis(_: str) -> bool:
        raise RuntimeError("redis exploded")

    def boom_memory(_: str) -> bool:
        raise RuntimeError("memory exploded")

    monkeypatch.setattr(limiter, "_allow_redis", boom_redis)
    monkeypatch.setattr(limiter, "_allow_memory", boom_memory)

    assert await limiter.allow("client-1") is True


# --------------------------------------------------------------------------- #
# CORS (no services — preflight is answered by the middleware, route untouched)
# --------------------------------------------------------------------------- #
def _build_app_with_cors(monkeypatch: pytest.MonkeyPatch, origins: str) -> FastAPI:
    from app.config import get_settings

    monkeypatch.setenv("CORS_ALLOW_ORIGINS", origins)
    get_settings.cache_clear()
    from app.main import create_app

    return create_app()


async def test_cors_header_present_for_allowed_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    app = _build_app_with_cors(monkeypatch, "https://allowed.example")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.options(
                "/v1/memories",
                headers={
                    "Origin": "https://allowed.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert response.headers.get("access-control-allow-origin") == "https://allowed.example"
    finally:
        get_settings.cache_clear()


async def test_cors_header_absent_for_disallowed_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    app = _build_app_with_cors(monkeypatch, "https://allowed.example")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.options(
                "/v1/memories",
                headers={
                    "Origin": "https://evil.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert "access-control-allow-origin" not in response.headers
    finally:
        get_settings.cache_clear()


async def test_cors_no_origins_allows_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    app = _build_app_with_cors(monkeypatch, "")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.options(
                "/v1/memories",
                headers={
                    "Origin": "https://anything.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert "access-control-allow-origin" not in response.headers
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# Full protected-route flow (needs services)
# --------------------------------------------------------------------------- #
@pytest.mark.integration
async def test_protected_route_requires_token(clean_stores: None) -> None:
    from app.main import create_app

    app = create_app()
    payload = {"text": "SecPhaseSeven likes oolong tea.", "user_id": "sec-user"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # No token -> 401.
        missing = await client.post("/v1/memories", json=payload)
        assert missing.status_code == 401

        # Wrong token -> 401.
        wrong = await client.post(
            "/v1/memories",
            json=payload,
            headers={"Authorization": "Bearer nope"},
        )
        assert wrong.status_code == 401

        # Correct token -> 200.
        ok = await client.post(
            "/v1/memories",
            json=payload,
            headers={"Authorization": "Bearer dev-token"},
        )
        assert ok.status_code == 200

        # Reads stay public (no token required).
        search = await client.get(
            "/v1/memories/search",
            params={"q": "What does SecPhaseSeven like?", "user_id": "sec-user"},
        )
        assert search.status_code == 200
