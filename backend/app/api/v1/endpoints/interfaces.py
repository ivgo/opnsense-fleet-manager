"""Interface, static route and VLAN desired-state management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import BadRequestError
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.config import (
    DeployRequest,
    InterfaceCreate,
    InterfaceOut,
    RouteCreate,
    RouteOut,
    VlanCreate,
    VlanOut,
)
from app.services.configuration import ConfigurationDeployer, InterfaceService, RouteService, VlanService

interfaces_router = APIRouter(prefix="/interfaces", tags=["Interfaces"])
routes_router = APIRouter(prefix="/routes", tags=["Routing"])
vlans_router = APIRouter(prefix="/vlans", tags=["VLANs"])


# --------------------------------------------------------------------------- interfaces
@interfaces_router.get(
    "",
    response_model=PageResponse[InterfaceOut],
    dependencies=[Depends(require_permissions(P.INTERFACE_READ))],
    summary="List interfaces",
)
async def list_interfaces(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    device_id: uuid.UUID | None = None,
    search: str | None = Query(None, max_length=128),
) -> PageResponse[InterfaceOut]:
    rows, total = await UnitOfWork(session, tenant_id).interfaces.list(
        filters={"device_id": device_id},
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    return paginate(rows, total, pagination, InterfaceOut)


@interfaces_router.post(
    "",
    response_model=InterfaceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.INTERFACE_WRITE))],
    summary="Create an interface",
)
async def create_interface(
    payload: InterfaceCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> InterfaceOut:
    interface = await InterfaceService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return InterfaceOut.model_validate(interface)


@interfaces_router.get(
    "/{interface_id}",
    response_model=InterfaceOut,
    dependencies=[Depends(require_permissions(P.INTERFACE_READ))],
    summary="Get an interface",
)
async def get_interface(interface_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> InterfaceOut:
    row = await UnitOfWork(session, tenant_id).interfaces.get_or_404(interface_id)
    return InterfaceOut.model_validate(row)


@interfaces_router.patch(
    "/{interface_id}",
    response_model=InterfaceOut,
    dependencies=[Depends(require_permissions(P.INTERFACE_WRITE))],
    summary="Update an interface",
)
async def update_interface(
    interface_id: uuid.UUID,
    payload: dict,
    session: SessionDep,
    tenant_id: TenantDep,
) -> InterfaceOut:
    uow = UnitOfWork(session, tenant_id)
    row = await uow.interfaces.get_or_404(interface_id)
    allowed = {"description", "physical_if", "ip_address", "subnet_bits", "gateway", "dhcp", "enabled"}
    unknown = set(payload) - allowed
    if unknown:
        raise BadRequestError(f"Unsupported fields: {', '.join(sorted(unknown))}")
    await uow.interfaces.update(row, **payload)
    await session.commit()
    return InterfaceOut.model_validate(row)


@interfaces_router.delete(
    "/{interface_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.INTERFACE_WRITE))],
    summary="Delete an interface",
)
async def delete_interface(interface_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    await uow.interfaces.delete(await uow.interfaces.get_or_404(interface_id))
    await session.commit()
    return Message(message="Interface deleted")


# --------------------------------------------------------------------------- routes
@routes_router.get(
    "",
    response_model=PageResponse[RouteOut],
    dependencies=[Depends(require_permissions(P.ROUTE_READ))],
    summary="List static routes",
)
async def list_routes(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    device_id: uuid.UUID | None = None,
    search: str | None = Query(None, max_length=128),
) -> PageResponse[RouteOut]:
    rows, total = await UnitOfWork(session, tenant_id).routes.list(
        filters={"device_id": device_id},
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    return paginate(rows, total, pagination, RouteOut)


@routes_router.post(
    "",
    response_model=RouteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.ROUTE_WRITE))],
    summary="Create a static route",
)
async def create_route(
    payload: RouteCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> RouteOut:
    route = await RouteService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return RouteOut.model_validate(route)


@routes_router.delete(
    "/{route_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.ROUTE_WRITE))],
    summary="Delete a static route",
)
async def delete_route(route_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    row = await uow.routes.get_or_404(route_id)
    if row.managed_by_sdwan:
        raise BadRequestError(
            "Route is managed by the SD-WAN controller; withdraw it from the topology instead"
        )
    await uow.routes.delete(row)
    await session.commit()
    return Message(message="Route deleted")


# --------------------------------------------------------------------------- vlans
@vlans_router.get(
    "",
    response_model=PageResponse[VlanOut],
    dependencies=[Depends(require_permissions(P.VLAN_READ))],
    summary="List VLANs",
)
async def list_vlans(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    device_id: uuid.UUID | None = None,
    search: str | None = Query(None, max_length=128),
) -> PageResponse[VlanOut]:
    rows, total = await UnitOfWork(session, tenant_id).vlans.list(
        filters={"device_id": device_id},
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    return paginate(rows, total, pagination, VlanOut)


@vlans_router.post(
    "/apply",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.VLAN_WRITE))],
    summary="Apply the stored VLANs of a device",
    description=(
        "Creates, updates and prunes OFME-managed VLAN interfaces on the appliance "
        "and reconfigures the interface stack. Use `dry_run` to inspect the payload."
    ),
)
async def apply_vlans(
    payload: DeployRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> dict:
    return await ConfigurationDeployer(session, tenant_id, principal.user_id).deploy_vlans(
        payload.device_id, dry_run=payload.dry_run, apply=payload.apply
    )


@vlans_router.post(
    "",
    response_model=VlanOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.VLAN_WRITE))],
    summary="Create a VLAN",
)
async def create_vlan(
    payload: VlanCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> VlanOut:
    vlan = await VlanService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return VlanOut.model_validate(vlan)


@vlans_router.delete(
    "/{vlan_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.VLAN_WRITE))],
    summary="Delete a VLAN",
)
async def delete_vlan(vlan_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    await uow.vlans.delete(await uow.vlans.get_or_404(vlan_id))
    await session.commit()
    return Message(message="VLAN deleted")
