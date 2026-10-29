"""Firewall rules: CRUD, ordering, shadowing analysis and OPNsense deployment."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.core.pagination import page_meta
from app.models.config import FirewallRule
from app.models.enums import RuleAction
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.config import RuleCreate, RuleOut, RuleUpdate
from app.services.configuration import ConfigurationDeployer, RuleService

router = APIRouter(prefix="/rules", tags=["Firewall rules"])


class ReorderRequest(BaseModel):
    device_id: uuid.UUID
    rule_ids: list[uuid.UUID]


class DeployResult(BaseModel):
    device_id: uuid.UUID
    dry_run: bool
    created: int = 0
    updated: int = 0
    applied: bool = False
    result: dict


@router.get(
    "",
    response_model=PageResponse[RuleOut],
    dependencies=[Depends(require_permissions(P.RULE_READ))],
    summary="List firewall rules",
)
async def list_rules(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    device_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    action: RuleAction | None = None,
    enabled: bool | None = Query(None),
    search: str | None = Query(None, max_length=128),
) -> PageResponse[RuleOut]:
    uow = UnitOfWork(session, tenant_id)
    stmt = uow.rules.query()
    if device_id is not None:
        stmt = stmt.where(FirewallRule.device_id == device_id)
    if group_id is not None:
        stmt = stmt.where(FirewallRule.group_id == group_id)
    if action is not None:
        stmt = stmt.where(FirewallRule.action == action)
    if enabled is not None:
        stmt = stmt.where(FirewallRule.enabled.is_(enabled))
    if search:
        stmt = stmt.where(FirewallRule.name.ilike(f"%{search}%"))

    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (
        (
            await session.execute(
                stmt.order_by(FirewallRule.order_index.asc(), FirewallRule.created_at.asc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            )
        )
        .scalars()
        .all()
    )
    return PageResponse[RuleOut](
        items=[RuleOut.model_validate(row) for row in rows],
        meta=page_meta(pagination.page, pagination.size, total),
    )


@router.post(
    "",
    response_model=RuleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.RULE_WRITE))],
    summary="Create a firewall rule",
)
async def create_rule(
    payload: RuleCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> RuleOut:
    rule = await RuleService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return RuleOut.model_validate(rule)


@router.get(
    "/{rule_id}",
    response_model=RuleOut,
    dependencies=[Depends(require_permissions(P.RULE_READ))],
    summary="Get a firewall rule",
)
async def get_rule(rule_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> RuleOut:
    return RuleOut.model_validate(await UnitOfWork(session, tenant_id).rules.get_or_404(rule_id))


@router.patch(
    "/{rule_id}",
    response_model=RuleOut,
    dependencies=[Depends(require_permissions(P.RULE_WRITE))],
    summary="Update a firewall rule",
)
async def update_rule(
    rule_id: uuid.UUID,
    payload: RuleUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> RuleOut:
    rule = await RuleService(session, tenant_id, principal.user_id).update(rule_id, payload)
    await session.commit()
    return RuleOut.model_validate(rule)


@router.delete(
    "/{rule_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.RULE_DELETE))],
    summary="Delete a firewall rule",
)
async def delete_rule(
    rule_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await RuleService(session, tenant_id, principal.user_id).delete(rule_id)
    await session.commit()
    return Message(message="Firewall rule deleted")


@router.get(
    "/{rule_id}/conflicts",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.RULE_READ))],
    summary="Detect shadowed or overlapping rules",
)
async def rule_conflicts(rule_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> list[dict]:
    uow = UnitOfWork(session, tenant_id)
    rule = await uow.rules.get_or_404(rule_id)
    return await RuleService(session, tenant_id).conflicts(rule)


@router.post(
    "/reorder",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.RULE_WRITE))],
    summary="Reorder the rules of a device",
)
async def reorder_rules(
    payload: ReorderRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    count = await RuleService(session, tenant_id, principal.user_id).reorder(
        payload.device_id, payload.rule_ids
    )
    await session.commit()
    return Message(message=f"Reordered {count} rule(s)")


@router.post(
    "/deploy/{device_id}",
    response_model=DeployResult,
    dependencies=[Depends(require_permissions(P.POLICY_DEPLOY))],
    summary="Push the managed rule set to a device",
)
async def deploy_rules(
    device_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
    dry_run: bool = Query(False),
) -> DeployResult:
    outcome = await ConfigurationDeployer(session, tenant_id, principal.user_id).deploy_rules(
        device_id, dry_run=dry_run, apply=not dry_run
    )
    await session.commit()
    return DeployResult(
        device_id=device_id,
        dry_run=dry_run,
        created=int(outcome.get("created", 0)),
        updated=int(outcome.get("updated", 0)),
        applied=bool(outcome.get("applied", False)),
        result=outcome,
    )
