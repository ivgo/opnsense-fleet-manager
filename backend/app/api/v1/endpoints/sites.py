"""Sites: physical locations, geographic map data and site-scoped inventory."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import BadRequestError
from app.models.topology import Site
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.topology import (
    DeviceOut,
    SiteCreate,
    SiteMapPoint,
    SiteOut,
    SiteUpdate,
)
from app.services.devices import DeviceService
from app.services.monitoring import DashboardService

router = APIRouter(prefix="/sites", tags=["Sites"])


async def _to_out(session: AsyncSession, site: Site) -> SiteOut:
    out = SiteOut.model_validate(site)
    out.device_count = await UnitOfWork(session, site.tenant_id).devices.count(site_id=site.id)
    return out


@router.get(
    "",
    response_model=PageResponse[SiteOut],
    dependencies=[Depends(require_permissions(P.SITE_READ))],
    summary="List sites",
)
async def list_sites(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    search: str | None = None,
    country: str | None = None,
) -> PageResponse[SiteOut]:
    uow = UnitOfWork(session, tenant_id)
    sites, total = await uow.sites.list(
        filters={"country": country},
        search=search,
        search_fields=("name", "code", "city"),
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    items = [await _to_out(session, site) for site in sites]
    return paginate(items, total, pagination, SiteOut)


@router.get("/map", response_model=list[SiteMapPoint], summary="Site map with device counters")
async def site_map(session: SessionDep, tenant_id: TenantDep) -> list[SiteMapPoint]:
    points = await DashboardService(session, tenant_id).site_map()
    return [SiteMapPoint.model_validate(point) for point in points]


@router.post(
    "",
    response_model=SiteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.SITE_WRITE))],
    summary="Create a site",
)
async def create_site(
    payload: SiteCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> SiteOut:
    uow = UnitOfWork(session, tenant_id)
    if await uow.sites.find_one(code=payload.code):
        raise BadRequestError(f"Site code '{payload.code}' already exists")
    site = await uow.sites.create(**payload.model_dump())
    await session.commit()
    return await _to_out(session, site)


@router.get(
    "/{site_id}",
    response_model=SiteOut,
    dependencies=[Depends(require_permissions(P.SITE_READ))],
    summary="Get a site",
)
async def get_site(site_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> SiteOut:
    site = await UnitOfWork(session, tenant_id).sites.get_or_404(site_id)
    return await _to_out(session, site)


@router.patch(
    "/{site_id}",
    response_model=SiteOut,
    dependencies=[Depends(require_permissions(P.SITE_WRITE))],
    summary="Update a site",
)
async def update_site(
    site_id: uuid.UUID,
    payload: SiteUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> SiteOut:
    uow = UnitOfWork(session, tenant_id)
    site = await uow.sites.get_or_404(site_id)
    await uow.sites.update(site, **payload.model_dump(exclude_unset=True))
    await session.commit()
    return await _to_out(session, site)


@router.delete(
    "/{site_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.SITE_WRITE))],
    summary="Delete a site",
)
async def delete_site(site_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    site = await uow.sites.get_or_404(site_id)
    if await uow.devices.count(site_id=site.id):
        raise BadRequestError("Reassign or remove the site's devices before deleting it")
    await uow.sites.delete(site)
    await session.commit()
    return Message(message="Site deleted")


@router.get(
    "/{site_id}/devices",
    response_model=PageResponse[DeviceOut],
    dependencies=[Depends(require_permissions(P.DEVICE_READ))],
    summary="Devices at a site",
)
async def site_devices(
    site_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
) -> PageResponse[DeviceOut]:
    await UnitOfWork(session, tenant_id).sites.get_or_404(site_id)
    devices, total = await DeviceService(session, tenant_id).list(
        page=pagination.page,
        size=pagination.size,
        site_id=site_id,
        sort=pagination.sort or "created_at",
        order=pagination.order,
    )
    return paginate(devices, total, pagination, DeviceOut)
