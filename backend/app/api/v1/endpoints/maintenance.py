"""Maintenance windows (quiet hours): CRUD and the currently active set."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentPrincipal, SessionDep, TenantDep, require_permissions
from app.rbac.permissions import P
from app.schemas.common import Message
from app.schemas.operations import (
    MaintenanceWindowCreate,
    MaintenanceWindowOut,
    MaintenanceWindowUpdate,
)
from app.services.maintenance import MaintenanceWindowService

router = APIRouter(prefix="/maintenance-windows", tags=["Maintenance windows"])


@router.get(
    "",
    response_model=list[MaintenanceWindowOut],
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="List maintenance windows",
)
async def list_windows(session: SessionDep, tenant_id: TenantDep) -> list[MaintenanceWindowOut]:
    return await MaintenanceWindowService(session, tenant_id).list()


@router.get(
    "/active",
    response_model=list[MaintenanceWindowOut],
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="Maintenance windows active right now",
)
async def active_windows(session: SessionDep, tenant_id: TenantDep) -> list[MaintenanceWindowOut]:
    return await MaintenanceWindowService(session, tenant_id).active()


@router.post(
    "",
    response_model=MaintenanceWindowOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.ALERT_WRITE))],
    summary="Create a maintenance window",
)
async def create_window(
    payload: MaintenanceWindowCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> MaintenanceWindowOut:
    return await MaintenanceWindowService(session, tenant_id, principal.user_id).create(payload)


@router.patch(
    "/{window_id}",
    response_model=MaintenanceWindowOut,
    dependencies=[Depends(require_permissions(P.ALERT_WRITE))],
    summary="Update a maintenance window",
)
async def update_window(
    window_id: uuid.UUID,
    payload: MaintenanceWindowUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> MaintenanceWindowOut:
    return await MaintenanceWindowService(session, tenant_id, principal.user_id).update(
        window_id, payload
    )


@router.delete(
    "/{window_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.ALERT_WRITE))],
    summary="Delete a maintenance window",
)
async def delete_window(
    window_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await MaintenanceWindowService(session, tenant_id, principal.user_id).delete(window_id)
    return Message(message="Maintenance window deleted")
