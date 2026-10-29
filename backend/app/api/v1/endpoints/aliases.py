"""Automatic firewall aliases (host, network, port and URL tables)."""

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
from app.models.enums import AliasType
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.config import AliasCreate, AliasOut, AliasUpdate
from app.services.configuration import AliasService

router = APIRouter(prefix="/aliases", tags=["Aliases"])


@router.get(
    "",
    response_model=PageResponse[AliasOut],
    dependencies=[Depends(require_permissions(P.ALIAS_READ))],
    summary="List aliases",
)
async def list_aliases(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    device_id: uuid.UUID | None = None,
    type_filter: AliasType | None = Query(None, alias="type"),
    search: str | None = Query(None, max_length=128),
) -> PageResponse[AliasOut]:
    filters: dict[str, object] = {"device_id": device_id}
    if type_filter is not None:
        filters["type"] = type_filter
    rows, total = await UnitOfWork(session, tenant_id).aliases.list(
        filters=filters,
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    return paginate(rows, total, pagination, AliasOut)


@router.post(
    "",
    response_model=AliasOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.ALIAS_WRITE))],
    summary="Create an alias",
)
async def create_alias(
    payload: AliasCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> AliasOut:
    alias = await AliasService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return AliasOut.model_validate(alias)


@router.get(
    "/{alias_id}",
    response_model=AliasOut,
    dependencies=[Depends(require_permissions(P.ALIAS_READ))],
    summary="Get an alias",
)
async def get_alias(alias_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> AliasOut:
    alias = await UnitOfWork(session, tenant_id).aliases.get_or_404(alias_id)
    return AliasOut.model_validate(alias)


@router.patch(
    "/{alias_id}",
    response_model=AliasOut,
    dependencies=[Depends(require_permissions(P.ALIAS_WRITE))],
    summary="Update an alias",
)
async def update_alias(
    alias_id: uuid.UUID,
    payload: AliasUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> AliasOut:
    alias = await AliasService(session, tenant_id, principal.user_id).update(alias_id, payload)
    await session.commit()
    return AliasOut.model_validate(alias)


@router.delete(
    "/{alias_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.ALIAS_WRITE))],
    summary="Delete an alias",
)
async def delete_alias(
    alias_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    uow = UnitOfWork(session, tenant_id)
    alias = await uow.aliases.get_or_404(alias_id)
    await uow.aliases.delete(alias)
    await session.commit()
    return Message(message="Alias deleted")
