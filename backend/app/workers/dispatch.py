"""Job enqueueing helpers shared by the API and the worker layer."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.models.enums import JobStatus, TaskKind
from app.models.operations import Job

log = get_logger("ofme.workers.dispatch")

# Canonical Celery task names. The worker modules register exactly these names.
TASK_BACKUP_ALL = "ofme.backups.run_scheduled"
TASK_BACKUP_DEVICE = "ofme.backups.create"
TASK_BACKUP_POSTGRES = "ofme.backup.pgbackrest_backup"
TASK_COMPLIANCE_RUN = "ofme.compliance.run"
TASK_DRIFT_SCAN = "ofme.policies.drift_scan"
TASK_POLICY_DEPLOY = "ofme.policies.deploy"
TASK_METRIC_COLLECT = "ofme.monitoring.collect"
TASK_HEARTBEAT_TIMEOUT = "ofme.monitoring.heartbeat_timeout"
TASK_CERT_ROTATE = "ofme.devices.rotate_certificates"
TASK_METRIC_PURGE = "ofme.monitoring.purge_metrics"
TASK_GIT_SYNC = "ofme.gitops.sync_repository"
TASK_SDWAN_HEALTH = "ofme.sdwan.health_sweep"
TASK_FIRMWARE_UPGRADE = "ofme.firmware.upgrade"
TASK_FIRMWARE_REBOOT = "ofme.firmware.reboot"
TASK_REPORT = "ofme.reports.generate"
TASK_CUSTOM = "ofme.tasks.custom"

# Canonical task executed for each tenant-owned schedule kind.
TASK_FOR_KIND: dict[TaskKind, str] = {
    TaskKind.BACKUP: TASK_BACKUP_ALL,
    TaskKind.COMPLIANCE_SCAN: TASK_COMPLIANCE_RUN,
    TaskKind.FIRMWARE_UPGRADE: TASK_FIRMWARE_UPGRADE,
    TaskKind.POLICY_DEPLOY: TASK_POLICY_DEPLOY,
    TaskKind.DRIFT_SCAN: TASK_DRIFT_SCAN,
    TaskKind.METRIC_COLLECT: TASK_METRIC_COLLECT,
    TaskKind.REPORT: TASK_REPORT,
    TaskKind.CUSTOM: TASK_CUSTOM,
}

ALL_TASK_NAMES: frozenset[str] = frozenset(
    {
        TASK_BACKUP_ALL,
        TASK_BACKUP_DEVICE,
        TASK_BACKUP_POSTGRES,
        TASK_COMPLIANCE_RUN,
        TASK_DRIFT_SCAN,
        TASK_POLICY_DEPLOY,
        TASK_METRIC_COLLECT,
        TASK_HEARTBEAT_TIMEOUT,
        TASK_CERT_ROTATE,
        TASK_METRIC_PURGE,
        TASK_GIT_SYNC,
        TASK_SDWAN_HEALTH,
        TASK_FIRMWARE_UPGRADE,
        TASK_FIRMWARE_REBOOT,
        TASK_REPORT,
        TASK_CUSTOM,
    }
)


async def enqueue(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    task_name: str,
    params: dict[str, Any] | None = None,
    actor_id: uuid.UUID | None = None,
) -> Job:
    """Persist a Job row, then hand the work to Celery.

    The Job row is committed before the broker call so that the worker can always
    resolve it, even when the enqueue happens on a different replica.
    """
    payload = params or {}
    job = Job(
        tenant_id=tenant_id,
        task_name=task_name,
        status=JobStatus.PENDING,
        params=payload,
        created_by=actor_id,
    )
    session.add(job)
    await session.commit()

    try:
        from app.workers.celery_app import celery_app

        result = await asyncio.to_thread(
            celery_app.send_task,
            task_name,
            kwargs={"job_id": str(job.id), "tenant_id": str(tenant_id), "params": payload},
            queue="ofme",
        )
    except Exception as exc:  # noqa: BLE001 - broker outages must leave an auditable failure
        log.error("job.enqueue_failed", task=task_name, job=str(job.id), error=str(exc))
        job.status = JobStatus.FAILED
        job.error = f"Unable to enqueue task: {exc}"
        await session.commit()
        raise UpstreamError("Task broker is unavailable") from exc

    job.celery_task_id = result.id
    await session.commit()
    return job
