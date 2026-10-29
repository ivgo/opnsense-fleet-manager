"""ASGI middleware: correlation IDs, structured access logs, security headers, metrics."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.logging import get_logger, request_id_ctx
from app.observability.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_IN_FLIGHT,
    HTTP_REQUESTS_TOTAL,
)

log = get_logger("ofme.http")

REQUEST_ID_HEADER = "X-Request-ID"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
}

CSP = (
    "default-src 'self'; "
    "img-src 'self' data: blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def _route_template(request: Request) -> str:
    """Low-cardinality route label: the matched template, never the raw path."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if template:
        return str(template)
    path = request.url.path
    if path.startswith(settings.API_V1_PREFIX):
        return f"{settings.API_V1_PREFIX}/*"
    return "/other"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request ID, emits an access log line and collects latency metrics."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming and len(incoming) <= 128 else uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id

        method = request.method
        HTTP_REQUESTS_IN_FLIGHT.inc()
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - re-raised after logging/metrics
            elapsed = time.perf_counter() - started
            route = _route_template(request)
            HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status="500").inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(elapsed)
            log.exception(
                "http.unhandled_exception",
                method=method,
                path=request.url.path,
                error=str(exc),
                duration_ms=round(elapsed * 1000, 2),
            )
            request_id_ctx.reset(token)
            HTTP_REQUESTS_IN_FLIGHT.dec()
            raise

        elapsed = time.perf_counter() - started
        route = _route_template(request)
        status_code = response.status_code
        HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status=str(status_code)).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(elapsed)
        HTTP_REQUESTS_IN_FLIGHT.dec()

        response.headers[REQUEST_ID_HEADER] = request_id
        log.info(
            "http.request",
            method=method,
            path=request.url.path,
            route=route,
            status=status_code,
            duration_ms=round(elapsed * 1000, 2),
            client=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:180],
        )
        request_id_ctx.reset(token)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds hardening headers to every response except the Prometheus scrape."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if request.url.path.startswith(settings.API_V1_PREFIX) and not request.url.path.startswith("/docs"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload"
            )
        response.headers.setdefault("Cache-Control", "no-store")
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects oversized request bodies before they reach an endpoint."""

    def __init__(self, app: ASGIApp, max_bytes: int = 32 * 1024 * 1024) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_bytes:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": f"Request body exceeds {self.max_bytes} bytes",
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )
        return await call_next(request)


__all__ = [
    "BodySizeLimitMiddleware",
    "RequestContextMiddleware",
    "SecurityHeadersMiddleware",
    "REQUEST_ID_HEADER",
]
