"""Configuration backups: signed artifacts, verification, restore and retention."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.models.enums import BackupType
from app.rbac.permissions import P
from app.schemas.common import Message, PageResponse
from app.schemas.operations import (
    BackupCreate,
    BackupOut,
    BackupRestoreRequest,
)
from app.services.backup import BackupService
from app.workers.dispatch import TASK_BACKUP_ALL, enqueue

router = APIRouter(prefix="/backups", tags=["Backups"])


class BackupVerificationOut(BaseModel):
    backup_id: uuid.UUID
    checksum_ok: bool
    signature_ok: bool
    valid: bool
    stored_checksum: str
    computed_checksum: str
    size_bytes: int


class RetentionRequest(BaseModel):
    retention_days: int | None = Field(None, ge=1, le=3650)
    keep_per_device: int = Field(30, ge=1, le=500)


class SweepRequest(BaseModel):
    type: BackupType = BackupType.SCHEDULED


@router.get(
    "",
    response_model=PageResponse[BackupOut],
    dependencies=[Depends(require_permissions(P.BACKUP_READ))],
    summary="List backups",
)
async def list_backups(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    device_id: uuid.UUID | None = None,
    backup_type: BackupType | None = Query(None, alias="type"),
) -> PageResponse[BackupOut]:
    rows, total = await BackupService(session, tenant_id).list(
        page=pagination.page,
        size=pagination.size,
        device_id=device_id,
        backup_type=backup_type.value if backup_type else None,
    )
    return paginate(rows, total, pagination, BackupOut)


@router.post(
    "",
    response_model=BackupOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.BACKUP_CREATE))],
    summary="Create a configuration backup",
)
async def create_backup(
    payload: BackupCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> BackupOut:
    backup = await BackupService(session, tenant_id, principal.user_id).create_backup(
        payload.device_id, backup_type=payload.type, notes=payload.notes
    )
    return BackupOut.model_validate(backup)


@router.get(
    "/storage-usage",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.BACKUP_READ))],
    summary="Total bytes stored for the tenant",
)
async def storage_usage(session: SessionDep, tenant_id: TenantDep) -> dict[str, int]:
    return {"storage_bytes": await BackupService(session, tenant_id).storage_usage()}


@router.post(
    "/sweep",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions(P.BACKUP_CREATE))],
    summary="Back up every device in the tenant (asynchronous)",
)
async def sweep_backups(
    payload: SweepRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> dict:
    job = await enqueue(
        session,
        tenant_id=tenant_id,
        task_name=TASK_BACKUP_ALL,
        params={"backup_type": payload.type.value},
        actor_id=principal.user_id,
    )
    return {"job_id": str(job.id), "task_name": job.task_name, "status": job.status.value}


@router.post(
    "/retention",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.BACKUP_DELETE))],
    summary="Apply the retention policy",
)
async def apply_retention(
    payload: RetentionRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> dict[str, int]:
    return await BackupService(session, tenant_id, principal.user_id).apply_retention(
        retention_days=payload.retention_days,
        keep_per_device=payload.keep_per_device,
    )


@router.get(
    "/{backup_id}",
    response_model=BackupOut,
    dependencies=[Depends(require_permissions(P.BACKUP_READ))],
    summary="Get a backup",
)
async def get_backup(backup_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> BackupOut:
    return BackupOut.model_validate(await BackupService(session, tenant_id).get(backup_id))


@router.get(
    "/{backup_id}/verify",
    response_model=BackupVerificationOut,
    dependencies=[Depends(require_permissions(P.BACKUP_READ))],
    summary="Verify checksum and signature of a stored artifact",
)
async def verify_backup(
    backup_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> BackupVerificationOut:
    result = await BackupService(session, tenant_id).verify(backup_id)
    return BackupVerificationOut(valid=result.valid, **asdict(result))


@router.get(
    "/{backup_id}/download",
    dependencies=[Depends(require_permissions(P.BACKUP_READ))],
    summary="Download the decrypted configuration snapshot",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}, "description": "Plain config.xml"}},
)
async def download_backup(
    backup_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Response:
    backup, payload = await BackupService(session, tenant_id, principal.user_id).download(backup_id)
    filename = f"{backup.device_id}-{backup.created_at:%Y%m%dT%H%M%SZ}.xml"
    return Response(
        content=payload,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/{backup_id}/restore",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.BACKUP_RESTORE))],
    summary="Restore a verified backup to its device",
)
async def restore_backup(
    backup_id: uuid.UUID,
    payload: BackupRestoreRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> dict:
    if payload.backup_id != backup_id:
        from app.core.exceptions import BadRequestError

        raise BadRequestError("Path backup_id and body backup_id do not match")
    return await BackupService(session, tenant_id, principal.user_id).restore(
        backup_id, dry_run=payload.dry_run, reboot=payload.reboot
    )


@router.delete(
    "/{backup_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.BACKUP_DELETE))],
    summary="Delete a backup and its stored artifact",
)
async def delete_backup(
    backup_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await BackupService(session, tenant_id, principal.user_id).delete(backup_id)
    return Message(message="Backup deleted", code=f"deleted_at:{datetime.now(UTC).isoformat()}")
