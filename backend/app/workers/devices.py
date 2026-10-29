"""Device PKI worker: proactive certificate rotation inside the renewal window."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.models.enums import CertificateStatus
from app.models.topology import DeviceCertificate
from app.services.devices import CertificateService
from app.workers.base import execute_task, resolve_tenants
from app.workers.celery_app import celery_app
from app.workers.dispatch import TASK_CERT_ROTATE

log = get_logger("ofme.workers.devices")

RETRYABLE = (UpstreamError, OperationalError, ConnectionError, TimeoutError)


async def _rotate(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    totals: dict[str, int] = {"tenants": 0, "rotated": 0, "expired": 0}

    for tid in await resolve_tenants(session, tenant_id):
        service = CertificateService(session, tid)
        rotated = await service.rotate_expiring()
        await session.commit()
        totals["rotated"] += rotated
        totals["tenants"] += 1

        expired = await session.execute(
            update(DeviceCertificate)
            .where(
                DeviceCertificate.tenant_id == tid,
                DeviceCertificate.status == CertificateStatus.ACTIVE,
                DeviceCertificate.valid_to < datetime.now(UTC),
            )
            .values(status=CertificateStatus.EXPIRED)
        )
        totals["expired"] += int(expired.rowcount or 0)
        await session.commit()
        log.info(
            "devices.certificates_rotated",
            tenant=str(tid),
            rotated=rotated,
            expired=int(expired.rowcount or 0),
            renew_before_days=settings.PKI_RENEW_BEFORE_DAYS,
        )

    return totals


@celery_app.task(
    bind=True,
    name=TASK_CERT_ROTATE,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=2,
)
def rotate_certificates(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    return execute_task(TASK_CERT_ROTATE, _rotate, job_id=job_id, tenant_id=tenant_id, params=params)


__all__ = ["rotate_certificates"]
