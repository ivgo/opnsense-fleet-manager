"""Monitoring workers: pull-based telemetry, liveness sweeps and metric retention."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import DeviceStatusChanged, event_bus
from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.models.enums import DeviceStatus
from app.services.devices import DeviceMonitorService
from app.services.monitoring import MetricQueryService
from app.workers.base import execute_task, merge_counts, resolve_tenants
from app.workers.celery_app import celery_app
from app.workers.dispatch import TASK_HEARTBEAT_TIMEOUT, TASK_METRIC_COLLECT, TASK_METRIC_PURGE

log = get_logger("ofme.workers.monitoring")

RETRYABLE = (UpstreamError, OperationalError, ConnectionError, TimeoutError)


async def _collect(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    limit = int(params.get("limit", 500))
    totals: dict[str, int] = {"tenants": 0, "ok": 0, "failed": 0}
    for tid in await resolve_tenants(session, tenant_id):
        outcome = await DeviceMonitorService(session, tid).poll_all(limit=limit)
        merge_counts(totals, outcome)
        totals["tenants"] += 1
        log.info("monitoring.collected", tenant=str(tid), **outcome)
    return totals


@celery_app.task(bind=True, name=TASK_METRIC_COLLECT, autoretry_for=RETRYABLE, max_retries=1)
def collect(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    return execute_task(TASK_METRIC_COLLECT, _collect, job_id=job_id, tenant_id=tenant_id, params=params)


async def _heartbeat_timeout(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    threshold = int(params.get("offline_after_seconds", settings.DEVICE_OFFLINE_AFTER_SECONDS))
    totals: dict[str, int] = {"tenants": 0, "offline": 0, "notified": 0}

    for tid in await resolve_tenants(session, tenant_id):
        from app.repositories import UnitOfWork

        uow = UnitOfWork(session, tid)
        stale = await uow.devices.stale(threshold)
        if not stale:
            continue
        marked = await uow.devices.mark_offline(threshold)
        await session.commit()
        totals["offline"] += marked
        totals["tenants"] += 1
        for device in stale:
            previous = device.status
            device.status = DeviceStatus.OFFLINE
            await event_bus.publish(
                DeviceStatusChanged(
                    device_id=str(device.id),
                    tenant_id=str(tid),
                    status=DeviceStatus.OFFLINE.value,
                    previous=previous.value if hasattr(previous, "value") else str(previous),
                )
            )
            totals["notified"] += 1
        log.info("monitoring.devices_offline", tenant=str(tid), count=marked)

    return totals


@celery_app.task(
    bind=True,
    name=TASK_HEARTBEAT_TIMEOUT,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    max_retries=2,
)
def heartbeat_timeout(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    return execute_task(
        TASK_HEARTBEAT_TIMEOUT, _heartbeat_timeout, job_id=job_id, tenant_id=tenant_id, params=params
    )


async def _purge_metrics(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    totals: dict[str, int] = {"tenants": 0, "purged": 0}
    for tid in await resolve_tenants(session, tenant_id):
        purged = await MetricQueryService(session, tid).purge()
        totals["purged"] += purged
        totals["tenants"] += 1
        log.info("monitoring.metrics_purged", tenant=str(tid), purged=purged)
    return totals


@celery_app.task(bind=True, name=TASK_METRIC_PURGE, autoretry_for=RETRYABLE, max_retries=1)
def purge_metrics(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    return execute_task(TASK_METRIC_PURGE, _purge_metrics, job_id=job_id, tenant_id=tenant_id, params=params)


__all__ = ["collect", "heartbeat_timeout", "purge_metrics"]
