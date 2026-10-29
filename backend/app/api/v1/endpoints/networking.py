"""DHCP scope/reservation and DNS record desired-state management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentPrincipal, PaginationDep, SessionDep, TenantDep, require_permissions
from app.api.v1.endpoints._common import paginate
from app.models.enums import DnsRecordType
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.config import (
    DeployRequest,
    DhcpReservationCreate,
    DhcpReservationOut,
    DhcpReservationUpdate,
    DhcpScopeCreate,
    DhcpScopeOut,
    DhcpScopeUpdate,
    DnsRecordCreate,
    DnsRecordOut,
    DnsRecordUpdate,
)
from app.services.configuration import ConfigurationDeployer
from app.services.networking import DhcpReservationService, DhcpScopeService, DnsRecordService

dhcp_router = APIRouter(prefix="/dhcp", tags=["DHCP"])
dns_router = APIRouter(prefix="/dns", tags=["DNS"])


# --------------------------------------------------------------------------- DHCP
@dhcp_router.post(
    "/apply",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.DHCP_WRITE))],
    summary="Apply the stored DHCP scopes and reservations of a device",
    description=(
        "Creates, updates and prunes OFME-managed Kea DHCPv4 subnets and reservations "
        "and reconfigures the service when something changed. Use `dry_run` to inspect "
        "the payload."
    ),
)
async def apply_dhcp(
    payload: DeployRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> dict:
    return await ConfigurationDeployer(session, tenant_id, principal.user_id).deploy_dhcp(
        payload.device_id, dry_run=payload.dry_run, apply=payload.apply
    )


# --------------------------------------------------------------------------- scopes
@dhcp_router.get(
    "/scopes",
    response_model=PageResponse[DhcpScopeOut],
    dependencies=[Depends(require_permissions(P.DHCP_READ))],
    summary="List DHCP scopes",
)
async def list_dhcp_scopes(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    device_id: uuid.UUID | None = None,
    enabled: bool | None = None,
    search: str | None = Query(None, max_length=128),
) -> PageResponse[DhcpScopeOut]:
    rows, total = await UnitOfWork(session, tenant_id).dhcp_scopes.list(
        filters={"device_id": device_id, "enabled": enabled},
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    return paginate(rows, total, pagination, DhcpScopeOut)


@dhcp_router.post(
    "/scopes",
    response_model=DhcpScopeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.DHCP_WRITE))],
    summary="Create a DHCP scope",
)
async def create_dhcp_scope(
    payload: DhcpScopeCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DhcpScopeOut:
    scope = await DhcpScopeService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return DhcpScopeOut.model_validate(scope)


@dhcp_router.get(
    "/scopes/{scope_id}",
    response_model=DhcpScopeOut,
    dependencies=[Depends(require_permissions(P.DHCP_READ))],
    summary="Get a DHCP scope",
)
async def get_dhcp_scope(scope_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> DhcpScopeOut:
    scope = await UnitOfWork(session, tenant_id).dhcp_scopes.get_or_404(scope_id)
    return DhcpScopeOut.model_validate(scope)


@dhcp_router.patch(
    "/scopes/{scope_id}",
    response_model=DhcpScopeOut,
    dependencies=[Depends(require_permissions(P.DHCP_WRITE))],
    summary="Update a DHCP scope",
)
async def update_dhcp_scope(
    scope_id: uuid.UUID,
    payload: DhcpScopeUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DhcpScopeOut:
    scope = await DhcpScopeService(session, tenant_id, principal.user_id).update(scope_id, payload)
    await session.commit()
    return DhcpScopeOut.model_validate(scope)


@dhcp_router.delete(
    "/scopes/{scope_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.DHCP_WRITE))],
    summary="Delete a DHCP scope and its reservations",
)
async def delete_dhcp_scope(scope_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    reservations = await DhcpScopeService(session, tenant_id).delete(scope_id)
    await session.commit()
    return Message(message=f"DHCP scope deleted ({reservations} reservation(s))")


# --------------------------------------------------------------------------- reservations
@dhcp_router.get(
    "/reservations",
    response_model=PageResponse[DhcpReservationOut],
    dependencies=[Depends(require_permissions(P.DHCP_READ))],
    summary="List DHCP reservations",
)
async def list_dhcp_reservations(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    scope_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    enabled: bool | None = None,
    search: str | None = Query(None, max_length=128),
) -> PageResponse[DhcpReservationOut]:
    rows, total = await UnitOfWork(session, tenant_id).dhcp_reservations.list(
        filters={"scope_id": scope_id, "device_id": device_id, "enabled": enabled},
        search=search,
        search_fields=("hostname", "mac_address", "ip_address"),
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    return paginate(rows, total, pagination, DhcpReservationOut)


@dhcp_router.post(
    "/reservations",
    response_model=DhcpReservationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.DHCP_WRITE))],
    summary="Create a DHCP reservation",
)
async def create_dhcp_reservation(
    payload: DhcpReservationCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DhcpReservationOut:
    reservation = await DhcpReservationService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return DhcpReservationOut.model_validate(reservation)


@dhcp_router.get(
    "/reservations/{reservation_id}",
    response_model=DhcpReservationOut,
    dependencies=[Depends(require_permissions(P.DHCP_READ))],
    summary="Get a DHCP reservation",
)
async def get_dhcp_reservation(
    reservation_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> DhcpReservationOut:
    reservation = await UnitOfWork(session, tenant_id).dhcp_reservations.get_or_404(reservation_id)
    return DhcpReservationOut.model_validate(reservation)


@dhcp_router.patch(
    "/reservations/{reservation_id}",
    response_model=DhcpReservationOut,
    dependencies=[Depends(require_permissions(P.DHCP_WRITE))],
    summary="Update a DHCP reservation",
)
async def update_dhcp_reservation(
    reservation_id: uuid.UUID,
    payload: DhcpReservationUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DhcpReservationOut:
    reservation = await DhcpReservationService(session, tenant_id, principal.user_id).update(
        reservation_id, payload
    )
    await session.commit()
    return DhcpReservationOut.model_validate(reservation)


@dhcp_router.delete(
    "/reservations/{reservation_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.DHCP_WRITE))],
    summary="Delete a DHCP reservation",
)
async def delete_dhcp_reservation(
    reservation_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> Message:
    await DhcpReservationService(session, tenant_id).delete(reservation_id)
    await session.commit()
    return Message(message="DHCP reservation deleted")


# --------------------------------------------------------------------------- DNS
@dns_router.get(
    "/records",
    response_model=PageResponse[DnsRecordOut],
    dependencies=[Depends(require_permissions(P.DNS_READ))],
    summary="List DNS records",
)
async def list_dns_records(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    device_id: uuid.UUID | None = None,
    record_type: DnsRecordType | None = None,
    enabled: bool | None = None,
    search: str | None = Query(None, max_length=255),
) -> PageResponse[DnsRecordOut]:
    rows, total = await UnitOfWork(session, tenant_id).dns_records.list(
        filters={"device_id": device_id, "record_type": record_type, "enabled": enabled},
        search=search,
        search_fields=("name", "value"),
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    return paginate(rows, total, pagination, DnsRecordOut)


@dns_router.post(
    "/records",
    response_model=DnsRecordOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.DNS_WRITE))],
    summary="Create a DNS record",
)
async def create_dns_record(
    payload: DnsRecordCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DnsRecordOut:
    record = await DnsRecordService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return DnsRecordOut.model_validate(record)


@dns_router.get(
    "/records/{record_id}",
    response_model=DnsRecordOut,
    dependencies=[Depends(require_permissions(P.DNS_READ))],
    summary="Get a DNS record",
)
async def get_dns_record(record_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> DnsRecordOut:
    record = await UnitOfWork(session, tenant_id).dns_records.get_or_404(record_id)
    return DnsRecordOut.model_validate(record)


@dns_router.patch(
    "/records/{record_id}",
    response_model=DnsRecordOut,
    dependencies=[Depends(require_permissions(P.DNS_WRITE))],
    summary="Update a DNS record",
)
async def update_dns_record(
    record_id: uuid.UUID,
    payload: DnsRecordUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DnsRecordOut:
    record = await DnsRecordService(session, tenant_id, principal.user_id).update(record_id, payload)
    await session.commit()
    return DnsRecordOut.model_validate(record)


@dns_router.delete(
    "/records/{record_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.DNS_WRITE))],
    summary="Delete a DNS record",
)
async def delete_dns_record(record_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    await DnsRecordService(session, tenant_id).delete(record_id)
    await session.commit()
    return Message(message="DNS record deleted")


@dns_router.post(
    "/apply",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.DNS_WRITE))],
    summary="Apply the stored DNS records of a device",
    description=(
        "Creates, updates and prunes OFME-managed Unbound host overrides and reconfigures "
        "the resolver when something changed. Record types Unbound cannot express "
        "(CNAME, PTR, SRV, NS) and names that are not fully qualified are returned in "
        "`skipped`. Use `dry_run` to inspect the payload."
    ),
)
async def apply_dns(
    payload: DeployRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> dict:
    return await ConfigurationDeployer(session, tenant_id, principal.user_id).deploy_dns(
        payload.device_id, dry_run=payload.dry_run, apply=payload.apply
    )
