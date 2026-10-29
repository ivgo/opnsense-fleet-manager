"""Tests for the per-identity rate limiter.

The limiter is exercised against a throwaway FastAPI application whose counter
backend is an in-process ``MemoryCounter`` with a fake clock, so the suite needs
neither Redis nor PostgreSQL and stays deterministic.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.core.config import settings
from app.core.rate_limit import (
    MemoryCounter,
    RateLimiter,
    RateLimitMiddleware,
    RedisCounter,
    identity_of,
    resolve_client_ip,
)


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeRedis:
    """Minimal ``INCR``/``EXPIRE`` surface used by ``RedisCounter``."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return True


def _build_app(limiter: RateLimiter) -> FastAPI:
    app = FastAPI()

    app.add_middleware(RateLimitMiddleware, limiter_instance=limiter)

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, str]:
        return {"status": "authenticated"}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def limiter(clock: FakeClock) -> RateLimiter:
    return RateLimiter(MemoryCounter(clock=clock))


@pytest.fixture
async def http(limiter: RateLimiter) -> Any:
    transport = ASGITransport(app=_build_app(limiter))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture(autouse=True)
def _enable_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_REQUESTS", 3)
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_REQUESTS", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60)


# --------------------------------------------------------------------- counters
@pytest.mark.asyncio
async def test_memory_counter_increments_within_window(clock: FakeClock) -> None:
    counter = MemoryCounter(clock=clock)
    assert [await counter.incr("k", 60) for _ in range(3)] == [1, 2, 3]
    clock.advance(59)
    assert await counter.incr("k", 60) == 4


@pytest.mark.asyncio
async def test_memory_counter_resets_after_window(clock: FakeClock) -> None:
    counter = MemoryCounter(clock=clock)
    await counter.incr("k", 60)
    clock.advance(61)
    assert await counter.incr("k", 60) == 1


@pytest.mark.asyncio
async def test_memory_counter_prunes_expired_keys() -> None:
    clock = FakeClock()
    counter = MemoryCounter(clock=clock)
    counter.MAX_KEYS = 2
    await counter.incr("a", 60)
    await counter.incr("b", 60)
    clock.advance(61)
    await counter.incr("c", 60)
    assert set(counter._counters) == {"c"}


@pytest.mark.asyncio
async def test_redis_counter_arms_ttl_once() -> None:
    client = FakeRedis()
    counter = RedisCounter(client)
    assert await counter.incr("k", 60) == 1
    assert client.ttls["k"] == 61
    assert await counter.incr("k", 60) == 2
    assert client.ttls["k"] == 61


@pytest.mark.asyncio
async def test_limiter_reports_remaining_and_retry_after(limiter: RateLimiter) -> None:
    allowed, remaining, retry_after = await limiter.hit("key", limit=2, window=30)
    assert (allowed, remaining, retry_after) == (True, 1, 0)
    allowed, remaining, retry_after = await limiter.hit("key", limit=2, window=30)
    assert (allowed, remaining, retry_after) == (True, 0, 0)
    allowed, remaining, retry_after = await limiter.hit("key", limit=2, window=30)
    assert (allowed, remaining, retry_after) == (False, 0, 30)


# ------------------------------------------------------------------- middleware
@pytest.mark.asyncio
async def test_requests_below_limit_pass_with_headers(http: AsyncClient) -> None:
    first = await http.get("/api/v1/ping")
    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "3"
    assert first.headers["x-ratelimit-remaining"] == "2"
    assert first.headers["x-ratelimit-window"] == "60"
    assert "retry-after" not in first.headers


@pytest.mark.asyncio
async def test_limit_exceeded_returns_429_envelope(http: AsyncClient) -> None:
    for _ in range(3):
        assert (await http.get("/api/v1/ping")).status_code == 200

    blocked = await http.get("/api/v1/ping")
    assert blocked.status_code == 429
    body = blocked.json()["error"]
    assert body["code"] == "rate_limited"
    assert body["details"] == {"limit": 3, "window_seconds": 60, "retry_after": 60}
    assert blocked.headers["retry-after"] == "60"
    assert blocked.headers["x-ratelimit-remaining"] == "0"


@pytest.mark.asyncio
async def test_window_expiry_releases_the_budget(http: AsyncClient, clock: FakeClock) -> None:
    for _ in range(3):
        await http.get("/api/v1/ping")
    assert (await http.get("/api/v1/ping")).status_code == 429
    clock.advance(61)
    assert (await http.get("/api/v1/ping")).status_code == 200


@pytest.mark.asyncio
async def test_authentication_endpoints_use_the_strict_budget(http: AsyncClient) -> None:
    assert (await http.post("/api/v1/auth/login")).status_code == 200
    assert (await http.post("/api/v1/auth/login")).status_code == 200
    blocked = await http.post("/api/v1/auth/login")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["details"]["limit"] == 2
    # The general API bucket is untouched by the auth bucket.
    assert (await http.get("/api/v1/ping")).status_code == 200


@pytest.mark.asyncio
async def test_health_and_metrics_are_never_limited(http: AsyncClient) -> None:
    for _ in range(20):
        assert (await http.get("/healthz")).status_code == 200
        assert (await http.get("/metrics")).status_code == 200


@pytest.mark.asyncio
async def test_credentials_are_bucketed_separately(http: AsyncClient) -> None:
    alice = {"Authorization": "Bearer alice-token"}
    bob = {"Authorization": "Bearer bob-token"}
    for _ in range(3):
        assert (await http.get("/api/v1/ping", headers=alice)).status_code == 200
    assert (await http.get("/api/v1/ping", headers=alice)).status_code == 429
    assert (await http.get("/api/v1/ping", headers=bob)).status_code == 200


@pytest.mark.asyncio
async def test_api_keys_are_bucketed_separately(http: AsyncClient) -> None:
    for _ in range(3):
        assert (await http.get("/api/v1/ping", headers={"X-API-Key": "key-one"})).status_code == 200
    assert (await http.get("/api/v1/ping", headers={"X-API-Key": "key-one"})).status_code == 429
    assert (await http.get("/api/v1/ping", headers={"X-API-Key": "key-two"})).status_code == 200


@pytest.mark.asyncio
async def test_device_agents_do_not_share_a_budget_behind_one_nat(
    http: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "*")
    first = {"X-Device-Id": "fw-01", "X-Forwarded-For": "203.0.113.10"}
    second = {"X-Device-Id": "fw-02", "X-Forwarded-For": "203.0.113.10"}
    for _ in range(3):
        assert (await http.get("/api/v1/ping", headers=first)).status_code == 200
    assert (await http.get("/api/v1/ping", headers=first)).status_code == 429
    assert (await http.get("/api/v1/ping", headers=second)).status_code == 200


@pytest.mark.asyncio
async def test_disabled_limiter_lets_everything_through(
    http: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    for _ in range(10):
        assert (await http.get("/api/v1/ping")).status_code == 200
    assert "x-ratelimit-limit" not in (await http.get("/api/v1/ping")).headers


# -------------------------------------------------------------------- identities
def _request(headers: dict[str, str], client: tuple[str, int] = ("198.51.100.7", 443)) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/ping",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
        "client": client,
    }
    return Request(scope)


def test_anonymous_identity_is_the_peer_address() -> None:
    assert identity_of(_request({})) == ("ip", "198.51.100.7")


def test_forwarded_for_is_ignored_for_untrusted_peers() -> None:
    request = _request({"X-Forwarded-For": "203.0.113.99"})
    assert resolve_client_ip(request) == "198.51.100.7"


def test_trusted_proxy_honours_x_real_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8")
    request = _request(
        {"X-Real-IP": "203.0.113.5", "X-Forwarded-For": "203.0.113.99"},
        client=("10.1.2.3", 1234),
    )
    assert resolve_client_ip(request) == "203.0.113.5"


def test_trusted_proxy_falls_back_to_forwarded_for(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.1.2.3")
    request = _request({"X-Forwarded-For": "203.0.113.5, 10.1.2.3"}, client=("10.1.2.3", 1234))
    assert resolve_client_ip(request) == "203.0.113.5"


def test_credential_digest_never_leaks_the_token() -> None:
    scope, identity = identity_of(_request({"Authorization": "Bearer super-secret"}))
    assert scope == "credential"
    assert identity != "super-secret"
    assert len(identity) == 24
