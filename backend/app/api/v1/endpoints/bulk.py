"""Bulk device actions and CSV import/export."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentPrincipal, SessionDep, TenantDep, require_permissions
from app.rbac.permissions import P
from app.schemas.operations import BulkDeviceAction, BulkDeviceResponse, CsvImportResult
from app.services.bulk import BulkDeviceService

router = APIRouter(prefix="/bulk", tags=["Bulk operations"])


@router.post(
    "/devices",
    response_model=BulkDeviceResponse,
    dependencies=[Depends(require_permissions(P.DEVICE_EXEC))],
    summary="Run one action across many devices",
)
async def bulk_devices(
    payload: BulkDeviceAction,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> BulkDeviceResponse:
    return await BulkDeviceService(session, tenant_id, principal.user_id).run(payload)


@router.get(
    "/devices/export.csv",
    dependencies=[Depends(require_permissions(P.DEVICE_READ))],
    summary="Export the device inventory as CSV",
    response_class=StreamingResponse,
)
async def export_devices(session: SessionDep, tenant_id: TenantDep) -> StreamingResponse:
    data = await BulkDeviceService(session, tenant_id).export_csv()
    return StreamingResponse(
        iter([data.encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="devices.csv"'},
    )


@router.post(
    "/devices/import",
    response_model=CsvImportResult,
    dependencies=[Depends(require_permissions(P.DEVICE_WRITE))],
    summary="Import devices from a CSV file",
)
async def import_devices(
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
    file: UploadFile = File(...),
) -> CsvImportResult:
    data = await file.read()
    return await BulkDeviceService(session, tenant_id, principal.user_id).import_csv(data)
