"""Device groups: hierarchical grouping, inherited templates and labels."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
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
from app.models.topology import DeviceGroup
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.topology import (
    DeviceGroupCreate,
    DeviceGroupOut,
    DeviceGroupUpdate,
    DeviceOut,
)
from app.services.devices import DeviceService

router = APIRouter(prefix="/groups", tags=["Device groups"])


class GroupTreeNode(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    labels: list[str]
    device_count: int
    children: list[GroupTreeNode] = []


GroupTreeNode.model_rebuild()


async def _to_out(session: AsyncSession, group: DeviceGroup) -> DeviceGroupOut:
    out = DeviceGroupOut.model_validate(group)
    out.device_count = await UnitOfWork(session, group.tenant_id).devices.count(group_id=group.id)
    return out


@router.get(
    "",
    response_model=PageResponse[DeviceGroupOut],
    dependencies=[Depends(require_permissions(P.GROUP_READ))],
    summary="List device groups",
)
async def list_groups(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    search: str | None = None,
    parent_id: uuid.UUID | None = None,
) -> PageResponse[DeviceGroupOut]:
    uow = UnitOfWork(session, tenant_id)
    groups, total = await uow.groups.list(
        filters={"parent_id": parent_id},
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort,
        order=pagination.order,
    )
    items = [await _to_out(session, group) for group in groups]
    return paginate(items, total, pagination, DeviceGroupOut)


@router.get("/tree", response_model=list[GroupTreeNode], summary="Group hierarchy")
async def group_tree(session: SessionDep, tenant_id: TenantDep) -> list[GroupTreeNode]:
    uow = UnitOfWork(session, tenant_id)
    groups, _ = await uow.groups.list(size=1000, sort="name", order="asc")
    by_id = {group.id: group for group in groups}
    counts = {group.id: await uow.devices.count(group_id=group.id) for group in groups}

    children: dict[uuid.UUID | None, list[DeviceGroup]] = {}
    for group in groups:
        parent = group.parent_id if group.parent_id in by_id else None
        children.setdefault(parent, []).append(group)

    def build(group: DeviceGroup) -> GroupTreeNode:
        return GroupTreeNode(
            id=group.id,
            name=group.name,
            description=group.description,
            labels=list(group.labels or []),
            device_count=counts.get(group.id, 0),
            children=[build(child) for child in children.get(group.id, [])],
        )

    return [build(group) for group in children.get(None, [])]


@router.post(
    "",
    response_model=DeviceGroupOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.GROUP_WRITE))],
    summary="Create a device group",
)
async def create_group(
    payload: DeviceGroupCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DeviceGroupOut:
    uow = UnitOfWork(session, tenant_id)
    if await uow.groups.find_one(name=payload.name):
        raise BadRequestError(f"Group '{payload.name}' already exists")
    if payload.parent_id is not None and await uow.groups.get(payload.parent_id) is None:
        raise BadRequestError("Parent group does not exist")
    group = await uow.groups.create(**payload.model_dump())
    await session.commit()
    return await _to_out(session, group)


@router.get(
    "/{group_id}",
    response_model=DeviceGroupOut,
    dependencies=[Depends(require_permissions(P.GROUP_READ))],
    summary="Get a device group",
)
async def get_group(group_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> DeviceGroupOut:
    group = await UnitOfWork(session, tenant_id).groups.get_or_404(group_id)
    return await _to_out(session, group)


@router.patch(
    "/{group_id}",
    response_model=DeviceGroupOut,
    dependencies=[Depends(require_permissions(P.GROUP_WRITE))],
    summary="Update a device group",
)
async def update_group(
    group_id: uuid.UUID,
    payload: DeviceGroupUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DeviceGroupOut:
    uow = UnitOfWork(session, tenant_id)
    group = await uow.groups.get_or_404(group_id)
    data = payload.model_dump(exclude_unset=True)
    parent_id = data.get("parent_id")
    if parent_id == group.id:
        raise BadRequestError("A group cannot be its own parent")
    if parent_id is not None and await uow.groups.get(parent_id) is None:
        raise BadRequestError("Parent group does not exist")
    await uow.groups.update(group, **data)
    await session.commit()
    return await _to_out(session, group)


@router.delete(
    "/{group_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.GROUP_WRITE))],
    summary="Delete a device group",
)
async def delete_group(group_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    group = await uow.groups.get_or_404(group_id)
    if await uow.groups.children(group.id):
        raise BadRequestError("Delete or re-parent child groups first")
    await uow.groups.delete(group)
    await session.commit()
    return Message(message="Device group deleted")


@router.get(
    "/{group_id}/devices",
    response_model=PageResponse[DeviceOut],
    dependencies=[Depends(require_permissions(P.DEVICE_READ))],
    summary="Devices in a group",
)
async def group_devices(
    group_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
) -> PageResponse[DeviceOut]:
    await UnitOfWork(session, tenant_id).groups.get_or_404(group_id)
    devices, total = await DeviceService(session, tenant_id).list(
        page=pagination.page,
        size=pagination.size,
        group_id=group_id,
        sort=pagination.sort or "created_at",
        order=pagination.order,
    )
    return paginate(devices, total, pagination, DeviceOut)
