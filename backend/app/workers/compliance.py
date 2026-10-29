"""Compliance worker: scheduled and on-demand framework evaluations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.models.enums import ComplianceFramework
from app.observability.metrics import COMPLIANCE_RUNS_TOTAL, COMPLIANCE_SCORE
from app.services.compliance import ComplianceService
from app.workers.base import as_uuid_list, execute_task, resolve_tenants
from app.workers.celery_app import celery_app
from app.workers.dispatch import TASK_COMPLIANCE_RUN

log = get_logger("ofme.workers.compliance")

RETRYABLE = (UpstreamError, OperationalError, ConnectionError, TimeoutError)


def _frameworks(params: dict[str, Any]) -> list[ComplianceFramework]:
    if params.get("all_frameworks"):
        return list(ComplianceFramework)
    raw = params.get("framework")
    if isinstance(raw, list | tuple | set):
        return [ComplianceFramework(str(item)) for item in raw]
    if raw:
        return [ComplianceFramework(str(raw))]
    return list(ComplianceFramework)


async def _run(session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]) -> dict[str, Any]:
    frameworks = _frameworks(params)
    device_ids = as_uuid_list(params.get("device_ids"))
    completed: list[dict[str, Any]] = []

    for tid in await resolve_tenants(session, tenant_id):
        for framework in frameworks:
            outcome = await ComplianceService(session, tid).run(framework, device_ids)
            report = outcome["report"]
            COMPLIANCE_SCORE.labels(framework=framework.value).set(float(report.score))
            COMPLIANCE_RUNS_TOTAL.labels(framework=framework.value, status=report.status.value).inc()
            completed.append(
                {
                    "tenant_id": str(tid),
                    "framework": framework.value,
                    "report_id": str(report.id),
                    "score": report.score,
                    "controls_total": report.controls_total,
                    "controls_failed": report.controls_failed,
                    "status": report.status.value,
                }
            )
            log.info(
                "compliance.evaluated",
                tenant=str(tid),
                framework=framework.value,
                score=report.score,
                failed=report.controls_failed,
            )

    return {
        "reports": completed,
        "count": len(completed),
        "average_score": round(sum(item["score"] for item in completed) / len(completed), 2)
        if completed
        else 0.0,
    }


@celery_app.task(
    bind=True,
    name=TASK_COMPLIANCE_RUN,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=2,
)
def run(self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None) -> dict:  # noqa: ANN001
    return execute_task(TASK_COMPLIANCE_RUN, _run, job_id=job_id, tenant_id=tenant_id, params=params)


__all__ = ["run"]
