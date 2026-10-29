"""Firmware worker: scheduled upgrades and reboots driven by tenant-owned tasks."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.services.upgrade import FirmwareUpgradeService
from app.workers.base import execute_task, resolve_tenants
from app.workers.celery_app import celery_app
from app.workers.dispatch import TASK_FIRMWARE_REBOOT, TASK_FIRMWARE_UPGRADE

log = get_logger("ofme.workers.firmware")

RETRYABLE = (UpstreamError, OperationalError, ConnectionError, TimeoutError)


async def _upgrade(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    device_ids = params.get("device_ids") or []
    if not device_ids:
        raise ValueError("firmware upgrade requires at least one device_id")
    package = params.get("package")
    totals: dict[str, int] = {"tenants": 0, "ok": 0, "failed": 0}

    for tid in await resolve_tenants(session, tenant_id):
        service = FirmwareUpgradeService(session, tid)
        for raw in device_ids:
            try:
                await service.upgrade(uuid.UUID(str(raw)), package=package)
                totals["ok"] += 1
            except Exception as exc:  # noqa: BLE001 - one bad device must not abort the batch
                log.warning("firmware.upgrade_failed", tenant=str(tid), device=str(raw), error=str(exc))
                totals["failed"] += 1
        await session.commit()
        totals["tenants"] += 1
    return totals


async def _reboot(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    device_ids = params.get("device_ids") or []
    if not device_ids:
        raise ValueError("firmware reboot requires at least one device_id")
    totals: dict[str, int] = {"tenants": 0, "ok": 0, "failed": 0}

    for tid in await resolve_tenants(session, tenant_id):
        service = FirmwareUpgradeService(session, tid)
        for raw in device_ids:
            try:
                await service.reboot(uuid.UUID(str(raw)))
                totals["ok"] += 1
            except Exception as exc:  # noqa: BLE001 - one bad device must not abort the batch
                log.warning("firmware.reboot_failed", tenant=str(tid), device=str(raw), error=str(exc))
                totals["failed"] += 1
        await session.commit()
        totals["tenants"] += 1
    return totals


@celery_app.task(
    bind=True,
    name=TASK_FIRMWARE_UPGRADE,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=2,
)
def upgrade(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    return execute_task(TASK_FIRMWARE_UPGRADE, _upgrade, job_id=job_id, tenant_id=tenant_id, params=params)


@celery_app.task(
    bind=True,
    name=TASK_FIRMWARE_REBOOT,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=2,
)
def reboot(self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None) -> dict:  # noqa: ANN001
    return execute_task(TASK_FIRMWARE_REBOOT, _reboot, job_id=job_id, tenant_id=tenant_id, params=params)


__all__ = ["upgrade", "reboot"]
