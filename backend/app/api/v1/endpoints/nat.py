"""NAT: port forwards, outbound NAT and one-to-one mappings."""

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
from app.models.enums import NatType
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.config import DeployRequest, NatCreate, NatOut, NatUpdate
from app.services.configuration import ConfigurationDeployer, NatService

router = APIRouter(prefix="/nat", tags=["NAT"])


@router.get(
    "",
    response_model=PageResponse[NatOut],
    dependencies=[Depends(require_permissions(P.NAT_READ))],
    summary="List NAT rules",
)
async def list_nat(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    device_id: uuid.UUID | None = None,
    type_filter: NatType | None = Query(None, alias="type"),
    search: str | None = Query(None, max_length=128),
) -> PageResponse[NatOut]:
    filters: dict[str, object] = {"device_id": device_id}
    if type_filter is not None:
        filters["type"] = type_filter
    rows, total = await UnitOfWork(session, tenant_id).nat.list(
        filters=filters,
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    return paginate(rows, total, pagination, NatOut)


@router.post(
    "",
    response_model=NatOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.NAT_WRITE))],
    summary="Create a NAT rule",
)
async def create_nat(
    payload: NatCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> NatOut:
    rule = await NatService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return NatOut.model_validate(rule)


@router.post(
    "/apply",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.NAT_WRITE))],
    summary="Apply the stored NAT rules of a device",
    description=(
        "Creates, updates and prunes OFME-managed NAT rules on the appliance "
        "and applies the NAT configuration. Use `dry_run` to inspect the payload."
    ),
)
async def apply_nat(
    payload: DeployRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> dict:
    return await ConfigurationDeployer(session, tenant_id, principal.user_id).deploy_nat(
        payload.device_id, dry_run=payload.dry_run, apply=payload.apply
    )


@router.get(
    "/{nat_id}",
    response_model=NatOut,
    dependencies=[Depends(require_permissions(P.NAT_READ))],
    summary="Get a NAT rule",
)
async def get_nat(nat_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> NatOut:
    return NatOut.model_validate(await UnitOfWork(session, tenant_id).nat.get_or_404(nat_id))


@router.patch(
    "/{nat_id}",
    response_model=NatOut,
    dependencies=[Depends(require_permissions(P.NAT_WRITE))],
    summary="Update a NAT rule",
)
async def update_nat(
    nat_id: uuid.UUID,
    payload: NatUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> NatOut:
    rule = await NatService(session, tenant_id, principal.user_id).update(nat_id, payload)
    await session.commit()
    return NatOut.model_validate(rule)


@router.delete(
    "/{nat_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.NAT_WRITE))],
    summary="Delete a NAT rule",
)
async def delete_nat(
    nat_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await NatService(session, tenant_id, principal.user_id).delete(nat_id)
    await session.commit()
    return Message(message="NAT rule deleted")
