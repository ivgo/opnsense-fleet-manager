"""ASGI application factory and process lifecycle for the OFME API.

Responsibilities
----------------
* Configure structured logging before anything else emits a log line.
* Bootstrap the internal CA, the object-storage buckets, the CQRS registry and the
  domain-event bridge exactly once per process.
* Start and stop the WebSocket hub (Redis fan-out listener).
* Translate every domain exception into the documented ``{"error": {...}}`` envelope.
* Expose Prometheus metrics and OpenAPI 3.1 documents.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.api.ws import hub, wire_event_forwarding
from app.api.ws import router as ws_router
from app.core.config import settings
from app.core.exceptions import OFMEError
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import RateLimitMiddleware, close_rate_limiter
from app.cqrs.commands import register_handlers
from app.db.session import dispose_engine
from app.observability import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    setup_tracing,
)
from app.observability.metrics import HTTP_EXCEPTIONS_TOTAL

configure_logging()
log = get_logger("ofme.main")

OPENAPI_TAGS = [
    {"name": "Health", "description": "Liveness, readiness and build metadata."},
    {"name": "Authentication", "description": "Login, MFA, SSO and token lifecycle."},
    {"name": "Tenants", "description": "Multi-tenant administration (SuperAdmin only)."},
    {"name": "Users", "description": "Identity, roles, permissions and API keys."},
    {"name": "Sites", "description": "Physical/logical site inventory."},
    {"name": "Groups", "description": "Device groups and policy inheritance."},
    {"name": "Devices", "description": "Firewall inventory, credentials and PKI."},
    {"name": "Configuration", "description": "Desired-state configuration for devices."},
    {"name": "Firewall rules", "description": "Rule CRUD and ordering."},
    {"name": "Aliases", "description": "Alias definitions."},
    {"name": "NAT", "description": "NAT/port-forward rules."},
    {"name": "Interfaces", "description": "Interfaces, routes and VLANs."},
    {"name": "DHCP", "description": "DHCP scopes and static reservations."},
    {"name": "DNS", "description": "Authoritative DNS records for managed resolvers."},
    {"name": "Templates", "description": "Configuration templates."},
    {"name": "Policies", "description": "Policy-as-code, deployments and drift."},
    {"name": "GitOps", "description": "Repository integrations and webhooks."},
    {"name": "SD-WAN", "description": "Topologies, tunnels, links and traffic policies."},
    {"name": "Zero-touch provisioning", "description": "Enrollment tokens and bootstrap."},
    {"name": "Backups", "description": "Signed configuration backups and restore."},
    {"name": "Jobs", "description": "Background job control."},
    {"name": "Scheduled tasks", "description": "Tenant-owned cron schedules."},
    {"name": "Alerts", "description": "Alert lifecycle and alert rules."},
    {"name": "Notifications", "description": "In-app notification inbox."},
    {"name": "Monitoring", "description": "Fleet dashboard, health and metric series."},
    {"name": "Audit", "description": "Immutable audit trail and event replay."},
    {"name": "Compliance", "description": "CIS, ISO 27001, NIS2, PCI DSS and SOC 2 reporting."},
    {"name": "Device agent", "description": "mTLS-authenticated endpoints used by os-fleet-agent."},
]


async def _bootstrap_platform() -> Any:
    """One-off startup work that must run before the first request is served."""
    from app.integrations.storage import get_storage
    from app.pki.ca import ca

    try:
        await asyncio.to_thread(ca.ensure_ca)
        log.info("startup.pki_ready", fingerprint=ca.fingerprint[:16])
    except Exception as exc:  # noqa: BLE001 - readiness reports PKI failure explicitly
        log.error("startup.pki_failed", error=str(exc))

    try:
        await asyncio.to_thread(get_storage().ensure_buckets)
        log.info("startup.storage_ready", buckets=settings.S3_BUCKET_BACKUPS)
    except Exception as exc:  # noqa: BLE001
        log.error("startup.storage_failed", error=str(exc))

    register_handlers()
    wire_event_forwarding()

    try:
        from app.seeds.bootstrap import bootstrap_if_configured

        await bootstrap_if_configured()
    except Exception as exc:  # noqa: BLE001 - seeding is best effort
        log.error("startup.seed_failed", error=str(exc))

    try:
        from app.seeds.bootstrap import sync_rbac_catalogue

        result = await sync_rbac_catalogue()
        log.info("startup.rbac_synced", **result)
    except Exception as exc:  # noqa: BLE001 - RBAC sync is best effort
        log.error("startup.rbac_sync_failed", error=str(exc))

    await hub.start()

    grpc_server = None
    try:
        from app.grpc.server import start_server

        grpc_server = await start_server()
    except Exception as exc:  # noqa: BLE001 - the REST API must start even if gRPC fails
        log.error("startup.grpc_failed", error=str(exc))
    return grpc_server


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    started = time.perf_counter()
    log.info(
        "startup.begin",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )
    grpc_server = await _bootstrap_platform()
    log.info("startup.complete", duration_ms=round((time.perf_counter() - started) * 1000, 2))
    try:
        yield
    finally:
        log.info("shutdown.begin")
        try:
            from app.grpc.server import stop_server

            await stop_server(grpc_server)
        except Exception as exc:  # noqa: BLE001 - shutdown must not mask the original error
            log.error("shutdown.grpc_failed", error=str(exc))
        await hub.stop()
        await close_rate_limiter()
        await dispose_engine()
        log.info("shutdown.complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Centralised management plane for OPNsense fleets: inventory, configuration, "
            "policy-as-code, SD-WAN, zero-touch provisioning, compliance and audit."
        ),
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json" if settings.ENABLE_DOCS else None,
        docs_url="/docs" if settings.ENABLE_DOCS else None,
        redoc_url="/redoc" if settings.ENABLE_DOCS else None,
        openapi_tags=OPENAPI_TAGS,
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        contact={"name": "OFME Platform Team", "email": "platform@ofme.io"},
        license_info={"name": "Commercial", "url": "https://ofme.local/licensing"},
    )

    # ------------------------------------------------------------------ middleware
    # Starlette executes the most recently added middleware first.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=32 * 1024 * 1024)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Tenant-Id",
            "X-Request-ID",
            "X-MFA-Challenge",
            "X-Device-Id",
            "X-Device-Serial",
            "X-Device-Cert-Fingerprint",
            "X-Client-Cert-Fingerprint",
            "X-Hub-Signature-256",
            "X-Gitlab-Token",
            "X-Gitlab-Event",
            "X-GitHub-Event",
            "X-GitHub-Delivery",
        ],
        expose_headers=["X-Request-ID", "Content-Disposition"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)

    # ------------------------------------------------------------------ routes
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    app.include_router(ws_router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, Any]:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "api": settings.API_V1_PREFIX,
            "docs": "/docs" if settings.ENABLE_DOCS else None,
            "health": f"{settings.API_V1_PREFIX}/health/ready",
            "websocket": "/ws",
        }

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    setup_tracing(app)
    _install_exception_handlers(app)
    return app


def _json_safe(value: Any) -> Any:
    """Coerce validation artefacts into JSON-serializable primitives.

    Pydantic puts the original exception object into ``ctx.error`` for custom
    validators; ``json.dumps`` cannot encode that, which used to turn a clean
    422 response into a 500.
    """
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _serializable_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        item: dict[str, Any] = {
            "type": str(error.get("type", "value_error")),
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": str(error.get("msg", "")),
        }
        if "input" in error:
            item["input"] = _json_safe(error["input"])
        if "ctx" in error:
            item["ctx"] = _json_safe(error["ctx"])
        details.append(item)
    return details


def _install_exception_handlers(app: FastAPI) -> None:
    def _request_id(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    @app.exception_handler(OFMEError)
    async def _domain_error(request: Request, exc: OFMEError) -> JSONResponse:
        HTTP_EXCEPTIONS_TOTAL.labels(exception=type(exc).__name__, status=str(exc.status_code)).inc()
        if exc.status_code >= 500:
            log.error("http.domain_error", code=exc.code, error=exc.message, path=request.url.path)
        else:
            log.info("http.domain_error", code=exc.code, error=exc.message, path=request.url.path)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {**exc.to_dict(), "request_id": _request_id(request)}},
            headers={"X-Request-ID": _request_id(request) or ""},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        HTTP_EXCEPTIONS_TOTAL.labels(exception="RequestValidationError", status="422").inc()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request payload failed validation",
                    "details": _serializable_errors(exc),
                    "request_id": _request_id(request),
                }
            },
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        HTTP_EXCEPTIONS_TOTAL.labels(exception="IntegrityError", status="409").inc()
        log.warning("http.integrity_error", error=str(exc.orig), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "conflict",
                    "message": "The request violates a database constraint",
                    "request_id": _request_id(request),
                }
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def _database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        HTTP_EXCEPTIONS_TOTAL.labels(exception=type(exc).__name__, status="500").inc()
        log.error("http.database_error", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "database_unavailable",
                    "message": "The database is temporarily unavailable",
                    "request_id": _request_id(request),
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        HTTP_EXCEPTIONS_TOTAL.labels(exception="HTTPException", status=str(exc.status_code)).inc()
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": f"http_{exc.status_code}",
                    "message": detail,
                    "request_id": _request_id(request),
                }
            },
            headers=getattr(exc, "headers", None) or {},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        HTTP_EXCEPTIONS_TOTAL.labels(exception=type(exc).__name__, status="500").inc()
        log.exception("http.unhandled", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred",
                    "request_id": _request_id(request),
                }
            },
        )


app = create_app()

__all__ = ["app", "create_app"]
