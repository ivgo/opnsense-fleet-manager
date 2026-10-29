"""Per-identity request rate limiting.

The security architecture requires rate limits per user/IP/tenant on the API
surface (``docs/SECURITY_ARCHITECTURE.md``). This module implements them as an
ASGI middleware in front of the v1 router:

* authenticated traffic is bucketed by a digest of the presented credential
  (JWT, API key or ``X-API-Key``), so one noisy session cannot exhaust another;
* device-agent traffic is bucketed by ``X-Device-Id`` (a fleet behind one NAT
  address must not share a budget);
* anonymous traffic is bucketed by client IP;
* authentication endpoints (login, LDAP login, refresh, MFA, OIDC callback) get
  a much smaller budget because they are the expensive, guessable surface.

Counters live in Redis so the limit is shared by every API replica; when Redis
is unreachable the limiter degrades to an in-process counter (still enforcing,
but per replica) and logs a warning once. Health probes, metrics, the OpenAPI
document and the WebSocket endpoint are never limited.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Protocol

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.logging import get_logger
from app.observability.metrics import RATE_LIMITED_TOTAL

log = get_logger("ofme.ratelimit")

#: Endpoints that must stay reachable regardless of client behaviour.
SKIP_PATHS = ("/healthz", "/metrics", "/openapi.json")
SKIP_PREFIXES = ("/docs", "/redoc", "/ws")

#: Suffixes (after the version prefix) with a stricter budget.
SENSITIVE_SUFFIXES = (
    "/auth/login",
    "/auth/ldap/login",
    "/auth/refresh",
    "/auth/mfa/verify",
    "/auth/mfa/verify-setup",
    "/auth/oidc/callback",
    "/auth/oidc/authorize",
)

_CREDENTIAL_HEADERS = ("authorization", "x-api-key")


class CounterBackend(Protocol):
    """Minimal interface required from a counter store."""

    async def incr(self, key: str, window: int) -> int:
        """Increment ``key`` and return the value within the window."""


class MemoryCounter:
    """Process-local fixed-window counter, used when Redis is unavailable."""

    #: Safety valve so a Redis outage cannot grow memory without bound.
    MAX_KEYS = 50_000

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._counters: dict[str, tuple[int, float]] = {}

    async def incr(self, key: str, window: int) -> int:
        now = self._clock()
        count, expires_at = self._counters.get(key, (0, 0.0))
        if expires_at <= now:
            count = 0
            expires_at = now + window
        count += 1
        self._counters[key] = (count, expires_at)
        if len(self._counters) > self.MAX_KEYS:
            self._counters = {k: v for k, v in self._counters.items() if v[1] > now}
        return count

    def clear(self) -> None:
        self._counters.clear()


class RedisCounter:
    """Fixed-window counter backed by Redis ``INCR`` + ``EXPIRE``."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def incr(self, key: str, window: int) -> int:
        count = int(await self._client.incr(key))
        if count == 1:
            # First hit in the window: (re)arm the TTL. Later hits leave it
            # alone so the window does not slide forward on every request.
            await self._client.expire(key, window + 1)
        return count


class RateLimiter:
    """Fixed-window limiter with a Redis backend and an in-process fallback."""

    def __init__(self, backend: CounterBackend | None = None) -> None:
        self._backend: CounterBackend | None = backend
        self._client: Any | None = None
        self._lock = asyncio.Lock()
        self._degraded = False

    async def backend(self) -> CounterBackend:
        if self._backend is not None:
            return self._backend
        async with self._lock:
            if self._backend is not None:
                return self._backend
            try:
                from redis.asyncio import Redis

                client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
                await client.ping()
                self._client = client
                self._backend = RedisCounter(client)
                log.info("ratelimit.backend_ready", backend="redis")
            except Exception as exc:  # noqa: BLE001 - in-process fallback is intentional
                self._degraded = True
                log.warning("ratelimit.redis_unavailable", error=str(exc), fallback="memory")
                self._backend = MemoryCounter()
            return self._backend

    async def hit(self, key: str, *, limit: int, window: int) -> tuple[bool, int, int]:
        """Register one request.

        Returns ``(allowed, remaining, retry_after_seconds)``. ``retry_after``
        is the full window because counters are fixed, not sliding.
        """
        limit = max(limit, 1)
        window = max(window, 1)
        backend = await self.backend()
        try:
            count = await backend.incr(key, window)
        except Exception as exc:  # noqa: BLE001 - never fail closed on a cache outage
            if not self._degraded:
                self._degraded = True
                log.warning("ratelimit.counter_failed", error=str(exc), fallback="memory")
            backend = MemoryCounter()
            self._backend = backend
            count = await backend.incr(key, window)
        remaining = max(limit - count, 0)
        return count <= limit, remaining, window if count > limit else 0

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:  # noqa: BLE001 - shutdown must not fail
                log.debug("ratelimit.close_failed", error=str(exc))
            self._client = None
            self._backend = None

    @property
    def degraded(self) -> bool:
        return self._degraded


limiter = RateLimiter()


def resolve_client_ip(request: Request) -> str:
    """Return the caller address, honouring proxies only when they are trusted.

    ``TRUSTED_PROXY_IPS`` accepts exact addresses, CIDR blocks or ``*``. Behind a
    proxy, ``X-Real-IP`` (which the bundled nginx overwrites) is preferred over
    ``X-Forwarded-For`` because the latter is appended to, and therefore
    spoofable, unless the proxy sanitises it.
    """
    peer = request.client.host if request.client and request.client.host else ""
    if peer and _is_trusted_proxy(peer):
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer or "unknown"


def _is_trusted_proxy(peer: str) -> bool:
    import ipaddress

    for entry in settings.trusted_proxy_ips:
        if entry == "*":
            return True
        try:
            if ipaddress.ip_address(peer) in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def identity_of(request: Request) -> tuple[str, str]:
    """Return ``(scope, identity)`` used to build the counter key."""
    device_id = request.headers.get("x-device-id")
    if device_id:
        return "device", hashlib.sha256(device_id.encode()).hexdigest()[:24]
    for header in _CREDENTIAL_HEADERS:
        credential = request.headers.get(header)
        if credential:
            return "credential", hashlib.sha256(credential.encode("utf-8")).hexdigest()[:24]
    return "ip", resolve_client_ip(request)


def _is_skipped(path: str) -> bool:
    if path in SKIP_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
        return True
    api_prefix = settings.API_V1_PREFIX
    if path == f"{api_prefix}/openapi.json":
        return True
    health_prefix = f"{api_prefix}/health"
    return path == health_prefix or path.startswith(f"{health_prefix}/")


def _is_sensitive(path: str) -> bool:
    return any(path.endswith(suffix) for suffix in SENSITIVE_SUFFIXES)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests that exceed the configured fixed-window budget."""

    def __init__(self, app: ASGIApp, limiter_instance: RateLimiter | None = None) -> None:
        super().__init__(app)
        self.limiter = limiter_instance or limiter

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        if not settings.RATE_LIMIT_ENABLED or _is_skipped(request.url.path):
            return await call_next(request)

        window = settings.RATE_LIMIT_WINDOW_SECONDS
        scope, identity = identity_of(request)
        sensitive = _is_sensitive(request.url.path)
        bucket = "auth" if sensitive else "api"
        limit = settings.RATE_LIMIT_AUTH_REQUESTS if sensitive else settings.RATE_LIMIT_REQUESTS

        key = f"ofme:rl:{bucket}:{scope}:{identity}"
        allowed, remaining, retry_after = await self.limiter.hit(key, limit=limit, window=window)

        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Window": str(window),
        }
        if retry_after:
            headers["Retry-After"] = str(retry_after)
            headers["X-RateLimit-Reset"] = str(retry_after)

        if not allowed:
            RATE_LIMITED_TOTAL.labels(scope=bucket).inc()
            log.warning(
                "ratelimit.exceeded",
                scope=bucket,
                identity=f"{scope}:{identity}",
                path=request.url.path,
                limit=limit,
                window=window,
            )
            headers["X-Request-ID"] = getattr(request.state, "request_id", "")
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": (f"Rate limit exceeded: {limit} requests per {window} seconds"),
                        "details": {
                            "limit": limit,
                            "window_seconds": window,
                            "retry_after": retry_after,
                        },
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
                headers=headers,
            )

        response = await call_next(request)
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response


async def close_rate_limiter() -> None:
    await limiter.close()


__all__ = [
    "CounterBackend",
    "MemoryCounter",
    "RateLimitMiddleware",
    "RateLimiter",
    "RedisCounter",
    "close_rate_limiter",
    "identity_of",
    "limiter",
    "resolve_client_ip",
]
