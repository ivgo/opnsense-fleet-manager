"""Report worker: render queued PDF reports and scheduled report runs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UpstreamError
from app.core.logging import get_logger
from app.models.enums import ReportKind
from app.models.operations import Report
from app.schemas.operations import ReportCreate
from app.services.report import ReportService
from app.workers.base import execute_task, resolve_tenants
from app.workers.celery_app import celery_app
from app.workers.dispatch import TASK_REPORT

log = get_logger("ofme.workers.reports")

RETRYABLE = (UpstreamError, OperationalError, ConnectionError, TimeoutError)


def _kind(params: dict[str, Any]) -> ReportKind:
    raw = params.get("kind") or ReportKind.FLEET.value
    try:
        return ReportKind(str(raw))
    except ValueError:
        return ReportKind.FLEET


async def _generate_existing(session: AsyncSession, report_id: str) -> dict[str, Any]:
    report = await session.get(Report, uuid.UUID(str(report_id)))
    if report is None:
        raise NotFoundError(f"Report {report_id} not found")
    service = ReportService(session, report.tenant_id)
    await service.generate(report)
    return {
        "report_id": str(report.id),
        "tenant_id": str(report.tenant_id),
        "kind": report.kind.value,
        "status": report.status.value,
        "size_bytes": report.size_bytes,
        "checksum_sha256": report.checksum_sha256,
    }


async def _run(session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]) -> dict[str, Any]:
    if params.get("report_id"):
        generated = [await _generate_existing(session, str(params["report_id"]))]
        return {"reports": generated, "count": len(generated)}

    kind = _kind(params)
    period_days = int(params.get("period_days") or 7)
    extra = params.get("report_params")
    payload_params = dict(extra) if isinstance(extra, dict) else {}
    generated: list[dict[str, Any]] = []

    for tid in await resolve_tenants(session, tenant_id):
        service = ReportService(session, tid)
        report = await service.create(
            ReportCreate(kind=kind, period_days=period_days, params=payload_params),
            generate_now=True,
        )
        generated.append(
            {
                "report_id": str(report.id),
                "tenant_id": str(tid),
                "kind": report.kind.value,
                "status": report.status.value,
                "size_bytes": report.size_bytes,
                "checksum_sha256": report.checksum_sha256,
            }
        )
        log.info(
            "report.generated",
            tenant=str(tid),
            report=str(report.id),
            kind=report.kind.value,
            size=report.size_bytes,
        )

    return {"reports": generated, "count": len(generated)}


@celery_app.task(
    bind=True,
    name=TASK_REPORT,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=2,
)
def run(self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None) -> dict:  # noqa: ANN001
    return execute_task(TASK_REPORT, _run, job_id=job_id, tenant_id=tenant_id, params=params)


__all__ = ["run"]
