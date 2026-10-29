"""Policy workers: drift detection and asynchronous deployments."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.models.enums import DriftStatus
from app.observability.metrics import POLICY_DRIFT_FINDINGS
from app.services.gitops import DeploymentService, DriftService
from app.workers.base import as_uuid_list, execute_task, resolve_tenants
from app.workers.celery_app import celery_app
from app.workers.dispatch import TASK_DRIFT_SCAN, TASK_POLICY_DEPLOY

log = get_logger("ofme.workers.policies")

RETRYABLE = (UpstreamError, OperationalError, ConnectionError, TimeoutError)


async def _drift_scan(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    device_ids = as_uuid_list(params.get("device_ids"))
    reports: list[dict[str, Any]] = []
    open_total = 0

    for tid in await resolve_tenants(session, tenant_id):
        tenant_reports = await DriftService(session, tid).scan(device_ids or None)
        open_count = sum(1 for report in tenant_reports if report.status == DriftStatus.OPEN)
        open_total += open_count
        reports.extend(
            {
                "tenant_id": str(tid),
                "report_id": str(report.id),
                "device_id": str(report.device_id),
                "status": report.status.value,
                "severity": report.severity.value
                if hasattr(report.severity, "value")
                else str(report.severity),
                "findings": len(report.findings or []),
            }
            for report in tenant_reports
        )
        log.info("policy.drift_scanned", tenant=str(tid), reports=len(tenant_reports), open=open_count)

    POLICY_DRIFT_FINDINGS.set(open_total)
    return {"reports": reports, "count": len(reports), "open": open_total}


@celery_app.task(
    bind=True,
    name=TASK_DRIFT_SCAN,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=2,
)
def drift_scan(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    return execute_task(TASK_DRIFT_SCAN, _drift_scan, job_id=job_id, tenant_id=tenant_id, params=params)


async def _deploy(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    if tenant_id is None:
        raise ValueError("tenant_id is required for a policy deployment")
    policy_id = params.get("policy_id")
    if not policy_id:
        raise ValueError("policy_id is required")

    service = DeploymentService(
        session,
        tenant_id,
        uuid.UUID(str(params["actor_id"])) if params.get("actor_id") else None,
    )
    deployment = await service.deploy(
        uuid.UUID(str(policy_id)),
        device_ids=as_uuid_list(params.get("device_ids")),
        dry_run=bool(params.get("dry_run", False)),
        change_request_id=uuid.UUID(str(params["change_request_id"]))
        if params.get("change_request_id")
        else None,
    )
    failures = [result for result in (deployment.results or []) if not result.get("success")]
    return {
        "deployment_id": str(deployment.id),
        "policy_id": str(deployment.policy_id),
        "status": deployment.status.value,
        "targets": len(deployment.target_device_ids or []),
        "failures": len(failures),
    }


@celery_app.task(
    bind=True,
    name=TASK_POLICY_DEPLOY,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=1,
)
def deploy(self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None) -> dict:  # noqa: ANN001
    return execute_task(TASK_POLICY_DEPLOY, _deploy, job_id=job_id, tenant_id=tenant_id, params=params)


__all__ = ["deploy", "drift_scan"]
