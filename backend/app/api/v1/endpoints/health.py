"""Liveness, readiness and build metadata for orchestrators."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.storage import get_storage

router = APIRouter(prefix="/health", tags=["Health"])
log = get_logger("ofme.health")


class ComponentHealth(BaseModel):
    status: str
    latency_ms: float | None = None
    detail: str | None = None


class Readiness(BaseModel):
    status: str
    components: dict[str, ComponentHealth]
    checked_at: datetime
    version: str
    environment: str


class VersionInfo(BaseModel):
    name: str
    version: str
    environment: str
    api_version: str
    python: str
    server_time: datetime


@router.get("/live", response_model=dict, summary="Process liveness")
async def live() -> dict[str, Any]:
    return {"status": "ok", "server_time": datetime.now(UTC)}


@router.get("/startup", response_model=dict, summary="Startup probe")
async def startup() -> dict[str, str]:
    return {"status": "started"}


@router.get(
    "/ready",
    response_model=Readiness,
    responses={503: {"model": Readiness}},
    summary="Dependency readiness",
)
async def ready(session: SessionDep, response: Response) -> Readiness:
    from time import perf_counter

    components: dict[str, ComponentHealth] = {}

    started = perf_counter()
    try:
        await session.execute(text("SELECT 1"))
        components["database"] = ComponentHealth(
            status="up", latency_ms=round((perf_counter() - started) * 1000, 2)
        )
    except Exception as exc:  # noqa: BLE001 - readiness must report, never raise
        log.warning("health.database_failed", error=str(exc))
        components["database"] = ComponentHealth(status="down", detail=str(exc)[:300])

    started = perf_counter()
    client = None
    try:
        client = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        await client.ping()
        components["redis"] = ComponentHealth(
            status="up", latency_ms=round((perf_counter() - started) * 1000, 2)
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("health.redis_failed", error=str(exc))
        components["redis"] = ComponentHealth(status="down", detail=str(exc)[:300])
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.aclose()

    started = perf_counter()
    try:
        storage_ok = await asyncio.to_thread(get_storage().healthcheck)
        components["object_storage"] = ComponentHealth(
            status="up" if storage_ok else "down",
            latency_ms=round((perf_counter() - started) * 1000, 2),
            detail=None if storage_ok else "S3 endpoint did not answer list_buckets",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("health.storage_failed", error=str(exc))
        components["object_storage"] = ComponentHealth(status="down", detail=str(exc)[:300])

    try:
        from app.pki.ca import ca

        components["pki"] = ComponentHealth(status="up", detail=ca.fingerprint[:16])
    except Exception as exc:  # noqa: BLE001
        log.warning("health.pki_failed", error=str(exc))
        components["pki"] = ComponentHealth(status="down", detail=str(exc)[:300])

    healthy = all(component.status == "up" for component in components.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(
        status="ready" if healthy else "degraded",
        components=components,
        checked_at=datetime.now(UTC),
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )


@router.get("/version", response_model=VersionInfo, summary="Build metadata")
async def version() -> VersionInfo:
    import platform

    return VersionInfo(
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        api_version="v1",
        python=platform.python_version(),
        server_time=datetime.now(UTC),
    )
