"""Compliance engine: framework reports, scoring, remediation and evidence."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.compliance import ComplianceReport
from app.models.enums import ComplianceFramework
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.compliance import (
    ComplianceReportOut,
    ComplianceRunRequest,
    ComplianceSummary,
    RemediationRequest,
    RemediationResult,
)
from app.services.compliance import ComplianceService, RemediationService

router = APIRouter(prefix="/compliance", tags=["Compliance"])

FRAMEWORKS: dict[ComplianceFramework, dict] = {
    ComplianceFramework.CIS: {
        "name": "CIS OPNsense Benchmark",
        "description": "Center for Internet Security hardening baseline for OPNsense firewalls.",
        "controls": 10,
    },
    ComplianceFramework.ISO27001: {
        "name": "ISO/IEC 27001:2022",
        "description": "Information security management controls A.9, A.12 and A.13.",
        "controls": 11,
    },
    ComplianceFramework.NIS2: {
        "name": "NIS2 Directive (EU 2022/2555)",
        "description": "Article 21 cyber risk management measures for essential entities.",
        "controls": 11,
    },
    ComplianceFramework.PCI_DSS: {
        "name": "PCI DSS v4.0",
        "description": "Network segmentation, audit trails and secure configuration requirements.",
        "controls": 11,
    },
    ComplianceFramework.SOC2: {
        "name": "SOC 2 Type II",
        "description": "Trust services criteria CC6.1 and CC7.2 evidence collection.",
        "controls": 10,
    },
}


@router.get(
    "/frameworks",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.COMPLIANCE_READ))],
    summary="Supported compliance frameworks",
)
async def list_frameworks() -> list[dict]:
    return [{"framework": framework.value, **metadata} for framework, metadata in FRAMEWORKS.items()]


@router.post(
    "/run",
    response_model=ComplianceReportOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.COMPLIANCE_RUN))],
    summary="Evaluate a framework and persist the report",
)
async def run_compliance(
    payload: ComplianceRunRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> ComplianceReportOut:
    outcome = await ComplianceService(session, tenant_id, principal.user_id).run(
        payload.framework, payload.device_ids
    )
    report: ComplianceReport = outcome["report"]
    return ComplianceReportOut.model_validate(report)


@router.get(
    "/summary",
    response_model=list[ComplianceSummary],
    dependencies=[Depends(require_permissions(P.COMPLIANCE_READ))],
    summary="Latest score and trend per framework",
)
async def compliance_summary(session: SessionDep, tenant_id: TenantDep) -> list[ComplianceSummary]:
    repository = UnitOfWork(session, tenant_id).compliance
    summaries: list[ComplianceSummary] = []
    for framework in ComplianceFramework:
        history = await repository.latest(framework, limit=12)
        if not history:
            summaries.append(
                ComplianceSummary(
                    framework=framework,
                    latest_score=None,
                    controls_total=0,
                    controls_failed=0,
                    last_run=None,
                    trend=[],
                )
            )
            continue
        latest = history[0]
        summaries.append(
            ComplianceSummary(
                framework=framework,
                latest_score=latest.score,
                controls_total=latest.controls_total,
                controls_failed=latest.controls_failed,
                last_run=latest.generated_at,
                trend=[
                    {"generated_at": report.generated_at, "score": report.score}
                    for report in reversed(history)
                ],
            )
        )
    return summaries


@router.get(
    "/reports",
    response_model=PageResponse[ComplianceReportOut],
    dependencies=[Depends(require_permissions(P.COMPLIANCE_READ))],
    summary="List compliance reports",
)
async def list_reports(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    framework: ComplianceFramework | None = None,
) -> PageResponse[ComplianceReportOut]:
    filters: dict[str, object] = {}
    if framework is not None:
        filters["framework"] = framework
    rows, total = await UnitOfWork(session, tenant_id).compliance.list(
        filters=filters,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "created_at",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, ComplianceReportOut)


@router.get(
    "/reports/{report_id}",
    response_model=ComplianceReportOut,
    dependencies=[Depends(require_permissions(P.COMPLIANCE_READ))],
    summary="Get a compliance report",
)
async def get_report(report_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> ComplianceReportOut:
    return ComplianceReportOut.model_validate(
        await UnitOfWork(session, tenant_id).compliance.get_or_404(report_id)
    )


@router.get(
    "/reports/{report_id}/evidence",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.COMPLIANCE_READ))],
    summary="Machine-readable evidence bundle",
)
async def report_evidence(report_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> dict:
    report = await UnitOfWork(session, tenant_id).compliance.get_or_404(report_id)
    return {
        "report_id": str(report.id),
        "framework": report.framework.value,
        "generated_at": report.generated_at,
        "score": report.score,
        "scope": report.scope,
        "controls": report.controls,
        "findings": report.findings,
        "hash_chain_anchor": report.artifact_key,
    }


@router.delete(
    "/reports/{report_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.COMPLIANCE_RUN))],
    summary="Delete a compliance report",
)
async def delete_report(report_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    report: ComplianceReport | None = await session.get(ComplianceReport, report_id)
    if report is None or report.tenant_id != tenant_id:
        raise NotFoundError("Compliance report not found")
    await session.delete(report)
    await session.commit()
    return Message(message="Compliance report deleted")


@router.post(
    "/remediate",
    response_model=RemediationResult,
    dependencies=[Depends(require_permissions(P.COMPLIANCE_REMEDIATE))],
    summary="Apply safe automated remediations",
)
async def remediate(
    payload: RemediationRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> RemediationResult:
    if not payload.finding_ids:
        raise BadRequestError("At least one finding id is required")
    outcome = await RemediationService(session, tenant_id, principal.user_id).remediate(
        payload.finding_ids, payload.device_ids, dry_run=payload.dry_run
    )
    return RemediationResult(**outcome)
