"""Backup workers: nightly fleet snapshots and on-demand device backups."""

from __future__ import annotations

import uuid
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.models.enums import BackupType
from app.observability.metrics import BACKUPS_TOTAL
from app.services.backup import BackupScheduler, BackupService
from app.workers.base import execute_task, merge_counts, resolve_tenants
from app.workers.celery_app import celery_app
from app.workers.dispatch import TASK_BACKUP_ALL, TASK_BACKUP_DEVICE

log = get_logger("ofme.workers.backups")

RETRYABLE = (UpstreamError, OperationalError, ConnectionError, TimeoutError)


async def _run_scheduled(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    backup_type = BackupType(params.get("backup_type", BackupType.SCHEDULED.value))
    apply_retention = bool(params.get("apply_retention", True))
    totals: dict[str, int] = {"tenants": 0, "ok": 0, "failed": 0, "deleted": 0, "kept": 0}

    for tid in await resolve_tenants(session, tenant_id):
        outcome = await BackupScheduler(session, tid).run_scheduled()
        merge_counts(totals, outcome)
        totals["tenants"] += 1
        BACKUPS_TOTAL.labels(result="ok").inc(outcome.get("ok", 0))
        BACKUPS_TOTAL.labels(result="failed").inc(outcome.get("failed", 0))
        if apply_retention:
            retention = await BackupService(session, tid).apply_retention()
            merge_counts(totals, retention)
        log.info(
            "backup.scheduled_tenant",
            tenant=str(tid),
            backup_type=backup_type.value,
            **outcome,
        )
    return totals


@celery_app.task(
    bind=True,
    name=TASK_BACKUP_ALL,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=3,
)
def run_scheduled(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    try:
        return execute_task(
            TASK_BACKUP_ALL, _run_scheduled, job_id=job_id, tenant_id=tenant_id, params=params
        )
    except SoftTimeLimitExceeded as exc:
        log.error("backup.sweep_timeout", job=job_id)
        raise UpstreamError("Backup sweep exceeded its time limit") from exc


async def _create(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    if tenant_id is None:
        raise ValueError("tenant_id is required for a single-device backup")
    device_id = params.get("device_id")
    if not device_id:
        raise ValueError("device_id is required")
    backup = await BackupService(session, tenant_id).create_backup(
        uuid.UUID(str(device_id)),
        backup_type=BackupType(params.get("backup_type", BackupType.MANUAL.value)),
        notes=params.get("notes"),
    )
    BACKUPS_TOTAL.labels(result="ok").inc()
    return {
        "backup_id": str(backup.id),
        "device_id": str(backup.device_id),
        "size_bytes": backup.size_bytes or 0,
        "checksum": backup.checksum_sha256,
        "storage_key": backup.storage_key,
    }


@celery_app.task(
    bind=True,
    name=TASK_BACKUP_DEVICE,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def create(self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None) -> dict:  # noqa: ANN001
    try:
        return execute_task(TASK_BACKUP_DEVICE, _create, job_id=job_id, tenant_id=tenant_id, params=params)
    except Exception:
        BACKUPS_TOTAL.labels(result="failed").inc()
        raise


__all__ = ["create", "run_scheduled"]
