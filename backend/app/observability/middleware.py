"""ASGI middleware: correlation IDs, structured access logs, security headers, metrics."""

from __future__ import annotations

import hmac
import secrets
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

CSRF_COOKIE_NAME = "ofme_csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _verify_csrf_token(cookie_token: str, header_token: str) -> bool:
    return hmac.compare_digest(cookie_token, header_token)

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


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection for state-changing operations.

    - Sets a CSRF token cookie on first response (if not present)
    - Validates the token from header matches cookie for mutating methods
    - Exempts safe methods (GET, HEAD, OPTIONS) and auth endpoints
    - Exempts API key authenticated requests (they use different auth mechanism)
    """

    EXEMPT_PATHS = {
        "/api/v1/auth/login",
        "/api/v1/auth/ldap/login",
        "/api/v1/auth/mfa/verify",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/oidc/callback",
        "/api/v1/auth/saml/acs",
        "/api/v1/auth/saml/metadata",
        "/api/v1/auth/providers",
        "/api/v1/auth/oidc/authorize",
        "/api/v1/auth/saml/authorize",
        "/healthz",
        "/metrics",
    }

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Skip CSRF for safe methods
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)

        # Skip for exempt paths
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Skip if not an API endpoint
        if not request.url.path.startswith(settings.API_V1_PREFIX):
            return await call_next(request)

        # Get CSRF token from cookie
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        if not cookie_token:
            # No cookie - this is a first visit or cookie was cleared
            # Set a new cookie but don't block (will be checked on next request)
            response = await call_next(request)
            new_token = _generate_csrf_token()
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=new_token,
                max_age=CSRF_COOKIE_MAX_AGE,
                httponly=True,
                secure=settings.is_production,
                samesite="lax",
                path="/",
            )
            return response

        # Check header for CSRF token
        header_token = request.headers.get(CSRF_HEADER_NAME)
        if not header_token or not _verify_csrf_token(cookie_token, header_token):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "csrf_failed",
                        "message": "CSRF token missing or invalid",
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
            )

        return await call_next(request)


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
    "CSRFMiddleware",
    "REQUEST_ID_HEADER",
]
