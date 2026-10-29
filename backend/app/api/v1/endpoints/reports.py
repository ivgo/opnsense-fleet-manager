"""PDF reports: on-demand generation, listing, download and scheduling."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import CurrentPrincipal, SessionDep, TenantDep, require_permissions
from app.models.enums import ReportStatus
from app.models.operations import Report
from app.rbac.permissions import P
from app.schemas.common import Message
from app.schemas.operations import ReportCreate, ReportOut
from app.services.report import ReportService
from app.workers.dispatch import TASK_REPORT, enqueue

router = APIRouter(prefix="/reports", tags=["Reports"])


def _out(report: Report) -> ReportOut:
    data = ReportOut.model_validate(report)
    if report.status == ReportStatus.READY:
        return data.model_copy(update={"download_url": f"/api/v1/reports/{report.id}/download"})
    return data


@router.get(
    "",
    response_model=list[ReportOut],
    dependencies=[Depends(require_permissions(P.REPORT_READ))],
    summary="List generated reports",
)
async def list_reports(session: SessionDep, tenant_id: TenantDep) -> list[ReportOut]:
    service = ReportService(session, tenant_id)
    return [_out(report) for report in await service.list()]


@router.get(
    "/{report_id}",
    response_model=ReportOut,
    dependencies=[Depends(require_permissions(P.REPORT_READ))],
    summary="Get one report",
)
async def get_report(report_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> ReportOut:
    return _out(await ReportService(session, tenant_id).get(report_id))


@router.post(
    "",
    response_model=ReportOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions(P.REPORT_WRITE))],
    summary="Queue a PDF report",
)
async def create_report(
    payload: ReportCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> ReportOut:
    service = ReportService(session, tenant_id, principal.user_id)
    report = await service.create(payload)
    await enqueue(
        session,
        tenant_id=tenant_id,
        task_name=TASK_REPORT,
        params={"report_id": str(report.id)},
        actor_id=principal.user_id,
    )
    return _out(report)


@router.get(
    "/{report_id}/download",
    dependencies=[Depends(require_permissions(P.REPORT_READ))],
    summary="Download a generated PDF",
    response_class=Response,
)
async def download_report(report_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Response:
    report, data = await ReportService(session, tenant_id).download(report_id)
    filename = f"{report.kind.value}-report-{report.id}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/{report_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.REPORT_WRITE))],
    summary="Delete a report and its PDF",
)
async def delete_report(
    report_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await ReportService(session, tenant_id, principal.user_id).delete(report_id)
    return Message(message="Report deleted")
