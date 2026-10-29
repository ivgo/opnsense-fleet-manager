"""Tenant administration: platform-level tenant lifecycle and statistics."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    require_superadmin,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import NotFoundError
from app.models.identity import Tenant
from app.models.topology import Device
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.identity import (
    TenantCreate,
    TenantOut,
    TenantStats,
    TenantUpdate,
)
from app.services.audit import AuditService
from app.services.identity import TenantService

router = APIRouter(prefix="/tenants", tags=["Tenants"], dependencies=[Depends(require_superadmin())])


async def _to_out(session: AsyncSession, tenant: Tenant) -> TenantOut:
    out = TenantOut.model_validate(tenant)
    out.device_count = await UnitOfWork(session, tenant.id).devices.count()
    return out


@router.get("", response_model=PageResponse[TenantOut], summary="List tenants")
async def list_tenants(
    session: SessionDep,
    pagination: PaginationDep,
    search: str | None = None,
) -> PageResponse[TenantOut]:
    tenants, total = await TenantService(session).list(
        page=pagination.page, size=pagination.size, search=search
    )
    items = [await _to_out(session, tenant) for tenant in tenants]
    return paginate(items, total, pagination, TenantOut)


@router.post(
    "",
    response_model=TenantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant",
)
async def create_tenant(
    payload: TenantCreate,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> TenantOut:
    service = TenantService(session, actor_id=principal.user_id)
    tenant = await service.create(payload)
    await session.commit()
    return await _to_out(session, tenant)


@router.get("/current", response_model=TenantOut, summary="Current tenant")
async def current_tenant(session: SessionDep, principal: CurrentPrincipal) -> TenantOut:
    if principal.tenant_id is None:
        raise NotFoundError("No tenant is bound to this principal")
    tenant = await session.get(Tenant, principal.tenant_id)
    if tenant is None:
        raise NotFoundError("Tenant not found")
    return await _to_out(session, tenant)


@router.get("/{tenant_id}", response_model=TenantOut, summary="Get a tenant")
async def get_tenant(tenant_id: uuid.UUID, session: SessionDep) -> TenantOut:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise NotFoundError("Tenant not found")
    return await _to_out(session, tenant)


@router.patch("/{tenant_id}", response_model=TenantOut, summary="Update a tenant")
async def update_tenant(
    tenant_id: uuid.UUID,
    payload: TenantUpdate,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> TenantOut:
    tenant = await TenantService(session, actor_id=principal.user_id).update(tenant_id, payload)
    await session.commit()
    return await _to_out(session, tenant)


@router.delete("/{tenant_id}", response_model=Message, summary="Soft-delete a tenant")
async def delete_tenant(
    tenant_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> Message:
    uow = UnitOfWork(session, None)
    tenant = await uow.tenants.get(tenant_id)
    if tenant is None:
        raise NotFoundError("Tenant not found")
    await uow.tenants.delete(tenant)
    await AuditService(session).record(
        action="tenant.deleted",
        resource_type="Tenant",
        resource_id=tenant.id,
        tenant_id=tenant.id,
        user_id=principal.user_id,
        before={"slug": tenant.slug, "name": tenant.name},
    )
    await session.commit()
    return Message(message=f"Tenant '{tenant.slug}' scheduled for deletion")


@router.get("/{tenant_id}/stats", response_model=TenantStats, summary="Tenant usage statistics")
async def tenant_stats(tenant_id: uuid.UUID, session: SessionDep) -> TenantStats:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError("Tenant not found")

    uow = UnitOfWork(session, tenant_id)
    counts = await uow.devices.by_status_counts()
    offline = counts.get("offline", 0) + counts.get("error", 0)
    return TenantStats(
        tenant_id=tenant.id,
        devices_total=sum(counts.values()),
        devices_online=counts.get("online", 0),
        devices_offline=offline,
        active_alerts=await uow.alerts.active_count(),
        storage_bytes=await uow.backups.storage_usage(),
        users=await uow.users.count(),
    )


@router.get("/{tenant_id}/devices", response_model=dict, summary="Device counters per tenant")
async def tenant_device_counters(tenant_id: uuid.UUID, session: SessionDep) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Device.status, func.count())
            .where(Device.tenant_id == tenant_id, Device.deleted_at.is_(None))
            .group_by(Device.status)
        )
    ).all()
    return {str(row[0].value if hasattr(row[0], "value") else row[0]): int(row[1]) for row in rows}
