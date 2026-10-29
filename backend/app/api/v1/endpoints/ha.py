"""CARP high-availability clusters: CRUD, status polling and controlled failover."""

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
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.ha import HaClusterCreate, HaClusterOut, HaClusterUpdate, HaFailoverResult
from app.services.ha import HaService

router = APIRouter(prefix="/ha", tags=["High availability"])


@router.get(
    "/clusters",
    response_model=PageResponse[HaClusterOut],
    dependencies=[Depends(require_permissions(P.HA_READ))],
    summary="List CARP clusters",
)
async def list_clusters(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    site_id: uuid.UUID | None = None,
    search: str | None = Query(None, max_length=128),
) -> PageResponse[HaClusterOut]:
    rows, total = await UnitOfWork(session, tenant_id).ha_clusters.list(
        filters={"site_id": site_id},
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    return paginate(rows, total, pagination, HaClusterOut)


@router.post(
    "/clusters",
    response_model=HaClusterOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.HA_WRITE))],
    summary="Create a CARP cluster",
)
async def create_cluster(
    payload: HaClusterCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> HaClusterOut:
    cluster = await HaService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return HaClusterOut.model_validate(cluster)


@router.get(
    "/clusters/{cluster_id}",
    response_model=HaClusterOut,
    dependencies=[Depends(require_permissions(P.HA_READ))],
    summary="Get a CARP cluster",
)
async def get_cluster(cluster_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> HaClusterOut:
    return HaClusterOut.model_validate(
        await UnitOfWork(session, tenant_id).ha_clusters.get_or_404(cluster_id)
    )


@router.patch(
    "/clusters/{cluster_id}",
    response_model=HaClusterOut,
    dependencies=[Depends(require_permissions(P.HA_WRITE))],
    summary="Update a CARP cluster",
)
async def update_cluster(
    cluster_id: uuid.UUID,
    payload: HaClusterUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> HaClusterOut:
    cluster = await HaService(session, tenant_id, principal.user_id).update(cluster_id, payload)
    await session.commit()
    return HaClusterOut.model_validate(cluster)


@router.delete(
    "/clusters/{cluster_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.HA_WRITE))],
    summary="Delete a CARP cluster",
)
async def delete_cluster(
    cluster_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await HaService(session, tenant_id, principal.user_id).delete(cluster_id)
    await session.commit()
    return Message(message="CARP cluster deleted")


@router.post(
    "/clusters/{cluster_id}/refresh",
    response_model=HaClusterOut,
    dependencies=[Depends(require_permissions(P.HA_READ))],
    summary="Poll CARP state from every cluster node",
)
async def refresh_cluster(
    cluster_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> HaClusterOut:
    cluster = await HaService(session, tenant_id, principal.user_id).refresh(cluster_id)
    return HaClusterOut.model_validate(cluster)


@router.post(
    "/clusters/{cluster_id}/failover",
    response_model=HaFailoverResult,
    dependencies=[Depends(require_permissions(P.HA_WRITE))],
    summary="Fail a CARP cluster over to the secondary node",
    description=(
        "Promotes the secondary node (advskew 0) and demotes the primary "
        "(advskew 100) through the OPNsense VIP API, then applies the VIP "
        "configuration. Both actions are audited."
    ),
)
async def failover_cluster(
    cluster_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> HaFailoverResult:
    return await HaService(session, tenant_id, principal.user_id).failover(cluster_id)
