"""GitOps policies: validation, simulation, deployment, drift and change control."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import BadRequestError
from app.models.enums import (
    ChangeStatus,
    ChangeType,
    DeploymentStatus,
    DriftStatus,
    Environment,
    PolicyKind,
    PolicyStatus,
    Priority,
)
from app.models.policy import DriftReport
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.policy import (
    ApprovalDecision,
    ChangeRequestCreate,
    ChangeRequestOut,
    DeploymentOut,
    DriftOut,
    DriftScanRequest,
    PolicyCreate,
    PolicyDiff,
    PolicyOut,
    PolicySimulationResult,
    PolicyUpdate,
    PolicyValidationResult,
)
from app.services.gitops import (
    ChangeRequestService,
    DeploymentService,
    DriftService,
    PolicyService,
    PromotionService,
)

policies_router = APIRouter(prefix="/policies", tags=["Policies"])
deployments_router = APIRouter(prefix="/deployments", tags=["Deployments"])
drift_router = APIRouter(prefix="/drift", tags=["Drift"])
changes_router = APIRouter(prefix="/changes", tags=["Change control"])


class DeployBody(BaseModel):
    device_ids: list[uuid.UUID] = Field(default_factory=list)
    dry_run: bool = False
    change_request_id: uuid.UUID | None = None


class SimulateBody(BaseModel):
    source_ip: str
    destination_ip: str
    protocol: str = "tcp"
    destination_port: int | None = Field(None, ge=1, le=65535)
    interface: str | None = None


class PromoteBody(BaseModel):
    source_environment: Environment
    target_environment: Environment
    create_change_request: bool = True


class ResolveDriftBody(BaseModel):
    notes: str | None = None


# --------------------------------------------------------------------------- policies
@policies_router.get(
    "",
    response_model=PageResponse[PolicyOut],
    dependencies=[Depends(require_permissions(P.POLICY_READ))],
    summary="List policies",
)
async def list_policies(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    kind: PolicyKind | None = None,
    environment: Environment | None = None,
    status_filter: PolicyStatus | None = Query(None, alias="status"),
    search: str | None = Query(None, max_length=128),
) -> PageResponse[PolicyOut]:
    filters: dict[str, object] = {"kind": kind, "environment": environment}
    if status_filter is not None:
        filters["status"] = status_filter
    rows, total = await UnitOfWork(session, tenant_id).policies.list(
        filters=filters,
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "name",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, PolicyOut)


@policies_router.post(
    "",
    response_model=PolicyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.POLICY_WRITE))],
    summary="Create a policy",
)
async def create_policy(
    payload: PolicyCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> PolicyOut:
    policy = await PolicyService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return PolicyOut.model_validate(policy)


@policies_router.get(
    "/{policy_id}",
    response_model=PolicyOut,
    dependencies=[Depends(require_permissions(P.POLICY_READ))],
    summary="Get a policy",
)
async def get_policy(policy_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> PolicyOut:
    return PolicyOut.model_validate(await UnitOfWork(session, tenant_id).policies.get_or_404(policy_id))


@policies_router.patch(
    "/{policy_id}",
    response_model=PolicyOut,
    dependencies=[Depends(require_permissions(P.POLICY_WRITE))],
    summary="Update a policy",
)
async def update_policy(
    policy_id: uuid.UUID,
    payload: PolicyUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> PolicyOut:
    policy = await PolicyService(session, tenant_id, principal.user_id).update(policy_id, payload)
    await session.commit()
    return PolicyOut.model_validate(policy)


@policies_router.delete(
    "/{policy_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.POLICY_WRITE))],
    summary="Delete a policy",
)
async def delete_policy(policy_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    policy = await uow.policies.get_or_404(policy_id)
    if policy.status == PolicyStatus.DEPLOYED:
        raise BadRequestError("Archive or roll back a deployed policy before deleting it")
    await uow.policies.delete(policy)
    await session.commit()
    return Message(message="Policy deleted")


@policies_router.post(
    "/{policy_id}/validate",
    response_model=PolicyValidationResult,
    dependencies=[Depends(require_permissions(P.POLICY_VALIDATE))],
    summary="Validate policy syntax and semantics",
)
async def validate_policy(
    policy_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> PolicyValidationResult:
    result = await PolicyService(session, tenant_id, principal.user_id).validate(policy_id)
    await session.commit()
    return result


@policies_router.get(
    "/{policy_id}/diff",
    response_model=PolicyDiff,
    dependencies=[Depends(require_permissions(P.POLICY_READ))],
    summary="Diff a policy against arbitrary YAML",
)
async def diff_policy(
    policy_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    against: str | None = Query(None, description="YAML to compare against"),
) -> PolicyDiff:
    return await PolicyService(session, tenant_id).diff(policy_id, against)


@policies_router.post(
    "/{policy_id}/simulate",
    response_model=PolicySimulationResult,
    dependencies=[Depends(require_permissions(P.POLICY_READ))],
    summary="Evaluate a synthetic packet against a policy",
)
async def simulate_policy(
    policy_id: uuid.UUID,
    payload: SimulateBody,
    session: SessionDep,
    tenant_id: TenantDep,
) -> PolicySimulationResult:
    return await PolicyService(session, tenant_id).simulate(
        policy_id,
        source_ip=payload.source_ip,
        destination_ip=payload.destination_ip,
        protocol=payload.protocol,
        destination_port=payload.destination_port,
        interface=payload.interface,
    )


@policies_router.post(
    "/{policy_id}/deploy",
    response_model=DeploymentOut,
    dependencies=[Depends(require_permissions(P.POLICY_DEPLOY))],
    summary="Deploy a policy to devices",
)
async def deploy_policy(
    policy_id: uuid.UUID,
    payload: DeployBody,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DeploymentOut:
    deployment = await DeploymentService(session, tenant_id, principal.user_id).deploy(
        policy_id,
        device_ids=payload.device_ids,
        dry_run=payload.dry_run,
        change_request_id=payload.change_request_id,
    )
    return DeploymentOut.model_validate(deployment)


@policies_router.post(
    "/{policy_id}/promote",
    response_model=PolicyOut,
    dependencies=[Depends(require_permissions(P.POLICY_APPROVE))],
    summary="Promote a policy to another environment",
)
async def promote_policy(
    policy_id: uuid.UUID,
    payload: PromoteBody,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> PolicyOut:
    if principal.user_id is None:
        raise BadRequestError("Promotion requires a user principal")
    promoted = await PromotionService(session, tenant_id, principal.user_id).promote(
        policy_id=policy_id,
        source_environment=payload.source_environment,
        target_environment=payload.target_environment,
        create_change_request=payload.create_change_request,
    )
    return PolicyOut.model_validate(promoted)


# --------------------------------------------------------------------------- deployments
@deployments_router.get(
    "",
    response_model=PageResponse[DeploymentOut],
    dependencies=[Depends(require_permissions(P.POLICY_READ))],
    summary="List deployments",
)
async def list_deployments(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    policy_id: uuid.UUID | None = None,
    environment: Environment | None = None,
    status_filter: DeploymentStatus | None = Query(None, alias="status"),
) -> PageResponse[DeploymentOut]:
    filters: dict[str, object] = {"policy_id": policy_id, "environment": environment}
    if status_filter is not None:
        filters["status"] = status_filter
    rows, total = await UnitOfWork(session, tenant_id).deployments.list(
        filters=filters,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "created_at",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, DeploymentOut)


@deployments_router.get(
    "/{deployment_id}",
    response_model=DeploymentOut,
    dependencies=[Depends(require_permissions(P.POLICY_READ))],
    summary="Get a deployment",
)
async def get_deployment(
    deployment_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> DeploymentOut:
    return DeploymentOut.model_validate(
        await UnitOfWork(session, tenant_id).deployments.get_or_404(deployment_id)
    )


@deployments_router.post(
    "/{deployment_id}/rollback",
    response_model=DeploymentOut,
    dependencies=[Depends(require_permissions(P.POLICY_ROLLBACK))],
    summary="Roll back a deployment to its pre-deployment state",
    description=(
        "Replays `snapshot.before` to the policy and to every deployment target, "
        "then marks the deployment `ROLLED_BACK` (or `FAILED` when a device push "
        "fails) and writes an audit entry. Deployments created before snapshots "
        "existed fall back to the previous deployment's `snapshot.after`; when "
        "neither is available the request is rejected with `400`."
    ),
)
async def rollback_deployment(
    deployment_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DeploymentOut:
    deployment = await DeploymentService(session, tenant_id, principal.user_id).rollback(deployment_id)
    return DeploymentOut.model_validate(deployment)


# --------------------------------------------------------------------------- drift
@drift_router.get(
    "",
    response_model=PageResponse[DriftOut],
    dependencies=[Depends(require_permissions(P.POLICY_READ))],
    summary="List drift reports",
)
async def list_drift(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    device_id: uuid.UUID | None = None,
    status_filter: DriftStatus | None = Query(None, alias="status"),
) -> PageResponse[DriftOut]:
    filters: dict[str, object] = {"device_id": device_id}
    if status_filter is not None:
        filters["status"] = status_filter
    rows, total = await UnitOfWork(session, tenant_id).drift.list(
        filters=filters,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "detected_at",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, DriftOut)


@drift_router.post(
    "/scan",
    response_model=list[DriftOut],
    dependencies=[Depends(require_permissions(P.POLICY_READ))],
    summary="Scan devices for configuration drift",
)
async def scan_drift(
    payload: DriftScanRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> list[DriftOut]:
    reports = await DriftService(session, tenant_id, principal.user_id).scan(payload.device_ids or None)
    return [DriftOut.model_validate(report) for report in reports]


@drift_router.post(
    "/{drift_id}/resolve",
    response_model=DriftOut,
    dependencies=[Depends(require_permissions(P.POLICY_DEPLOY))],
    summary="Mark a drift report as resolved",
)
async def resolve_drift(
    drift_id: uuid.UUID,
    payload: ResolveDriftBody,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DriftOut:
    uow = UnitOfWork(session, tenant_id)
    report: DriftReport = await uow.drift.get_or_404(drift_id)
    if report.status == DriftStatus.OPEN:
        report.status = DriftStatus.REMEDIATED
        report.resolved_at = datetime.now(UTC)
        report.resolved_by = principal.user_id
        report.notes = payload.notes
        await session.commit()
    return DriftOut.model_validate(report)


# --------------------------------------------------------------------------- change requests
@changes_router.get(
    "",
    response_model=PageResponse[ChangeRequestOut],
    dependencies=[Depends(require_permissions(P.CHANGE_READ))],
    summary="List change requests",
)
async def list_changes(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    status_filter: ChangeStatus | None = Query(None, alias="status"),
    type_filter: ChangeType | None = Query(None, alias="type"),
    environment: Environment | None = None,
    search: str | None = Query(None, max_length=128),
) -> PageResponse[ChangeRequestOut]:
    filters: dict[str, object] = {"environment": environment}
    if status_filter is not None:
        filters["status"] = status_filter
    if type_filter is not None:
        filters["type"] = type_filter
    rows, total = await UnitOfWork(session, tenant_id).changes.list(
        filters=filters,
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "created_at",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, ChangeRequestOut)


@changes_router.post(
    "",
    response_model=ChangeRequestOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.CHANGE_WRITE))],
    summary="Open a change request",
)
async def create_change(
    payload: ChangeRequestCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> ChangeRequestOut:
    if principal.user_id is None:
        raise BadRequestError("Change requests require a user principal")
    change = await ChangeRequestService(session, tenant_id, principal.user_id).create(
        title=payload.title,
        type_=payload.type.value,
        payload=payload.payload,
        description=payload.description,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        required_approvals=payload.required_approvals,
        environment=payload.environment,
        expires_in_hours=payload.expires_in_hours,
        priority=payload.priority.value if isinstance(payload.priority, Priority) else str(payload.priority),
    )
    await session.commit()
    return ChangeRequestOut.model_validate(change)


@changes_router.get(
    "/{change_id}",
    response_model=ChangeRequestOut,
    dependencies=[Depends(require_permissions(P.CHANGE_READ))],
    summary="Get a change request",
)
async def get_change(change_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> ChangeRequestOut:
    return ChangeRequestOut.model_validate(await UnitOfWork(session, tenant_id).changes.get_or_404(change_id))


@changes_router.post(
    "/{change_id}/approve",
    response_model=ChangeRequestOut,
    dependencies=[Depends(require_permissions(P.CHANGE_APPROVE))],
    summary="Approve a change request",
)
async def approve_change(
    change_id: uuid.UUID,
    payload: ApprovalDecision,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> ChangeRequestOut:
    if principal.user_id is None:
        raise BadRequestError("Approvals require a user principal")
    change = await ChangeRequestService(session, tenant_id, principal.user_id).approve(
        change_id, comment=payload.comment
    )
    await session.commit()
    return ChangeRequestOut.model_validate(change)


@changes_router.post(
    "/{change_id}/reject",
    response_model=ChangeRequestOut,
    dependencies=[Depends(require_permissions(P.CHANGE_APPROVE))],
    summary="Reject a change request",
)
async def reject_change(
    change_id: uuid.UUID,
    payload: ApprovalDecision,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> ChangeRequestOut:
    if principal.user_id is None:
        raise BadRequestError("Rejections require a user principal")
    change = await ChangeRequestService(session, tenant_id, principal.user_id).reject(
        change_id, comment=payload.comment
    )
    await session.commit()
    return ChangeRequestOut.model_validate(change)


@changes_router.post(
    "/{change_id}/cancel",
    response_model=ChangeRequestOut,
    dependencies=[Depends(require_permissions(P.CHANGE_WRITE))],
    summary="Cancel a change request",
)
async def cancel_change(
    change_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> ChangeRequestOut:
    if principal.user_id is None:
        raise BadRequestError("Cancellations require a user principal")
    change = await ChangeRequestService(session, tenant_id, principal.user_id).cancel(change_id)
    await session.commit()
    return ChangeRequestOut.model_validate(change)
