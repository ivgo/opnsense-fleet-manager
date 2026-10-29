"""Immutable audit trail: search, export, integrity verification and event replay."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import NotFoundError, TenantIsolationError
from app.models.audit import AuditLog
from app.rbac.permissions import P
from app.schemas.common import PageResponse
from app.schemas.compliance import AuditIntegrityResult, AuditLogOut
from app.services.audit import AuditService, EventStoreService

router = APIRouter(prefix="/audit", tags=["Audit"])

TenantHeader = Annotated[uuid.UUID | None, Header(alias="X-Tenant-Id")]


def _resolve_scope(principal: CurrentPrincipal, requested: uuid.UUID | None) -> uuid.UUID | None:
    """SuperAdmins may query the whole platform; tenants are always isolated."""
    if principal.is_superadmin:
        return requested
    if principal.tenant_id is None:
        raise TenantIsolationError("User is not bound to a tenant")
    if requested is not None and requested != principal.tenant_id:
        raise TenantIsolationError("Cross-tenant access is not permitted")
    return principal.tenant_id


@router.get(
    "",
    response_model=PageResponse[AuditLogOut],
    dependencies=[Depends(require_permissions(P.AUDIT_READ))],
    summary="Search the audit trail",
)
async def search_audit(
    session: SessionDep,
    principal: CurrentPrincipal,
    pagination: PaginationDep,
    x_tenant_id: TenantHeader = None,
    action: str | None = Query(None, max_length=128),
    resource_type: str | None = Query(None, max_length=64),
    resource_id: str | None = Query(None, max_length=128),
    user_id: uuid.UUID | None = None,
    result: str | None = Query(None, pattern="^(success|failure)$"),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> PageResponse[AuditLogOut]:
    scope = _resolve_scope(principal, x_tenant_id)
    rows, total = await AuditService(session).search(
        tenant_id=scope,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        result=result,
        from_date=from_date,
        to_date=to_date,
        page=pagination.page,
        size=pagination.size,
    )
    return paginate(rows, total, pagination, AuditLogOut)


@router.get(
    "/integrity",
    response_model=AuditIntegrityResult,
    dependencies=[Depends(require_permissions(P.AUDIT_READ))],
    summary="Verify the audit hash chain",
)
async def audit_integrity(
    session: SessionDep,
    limit: int = Query(10000, ge=1, le=100000),
) -> AuditIntegrityResult:
    valid, first_broken_id, last_hash = await AuditService(session).verify_chain(limit=limit)
    checked = int((await session.execute(select(func.count()).select_from(AuditLog))).scalar_one())
    return AuditIntegrityResult(
        checked=min(checked, limit),
        valid=valid,
        first_broken_id=first_broken_id,
        last_hash=last_hash,
    )


@router.get(
    "/actions",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.AUDIT_READ))],
    summary="Distinct audit actions with counters",
)
async def audit_actions(
    session: SessionDep,
    principal: CurrentPrincipal,
    x_tenant_id: TenantHeader = None,
) -> list[dict]:
    scope = _resolve_scope(principal, x_tenant_id)
    stmt = select(AuditLog.action, AuditLog.resource_type, func.count()).group_by(
        AuditLog.action, AuditLog.resource_type
    )
    if scope is not None:
        stmt = stmt.where(AuditLog.tenant_id == scope)
    rows = (await session.execute(stmt.order_by(func.count().desc()).limit(500))).all()
    return [
        {"action": action, "resource_type": resource_type, "count": int(count)}
        for action, resource_type, count in rows
    ]


@router.get(
    "/export",
    dependencies=[Depends(require_permissions(P.AUDIT_READ))],
    summary="Export the filtered audit trail as CSV",
)
async def export_audit(
    session: SessionDep,
    principal: CurrentPrincipal,
    x_tenant_id: TenantHeader = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    action: str | None = Query(None, max_length=128),
    limit: int = Query(10000, ge=1, le=100000),
) -> StreamingResponse:
    scope = _resolve_scope(principal, x_tenant_id)
    rows, _ = await AuditService(session).search(
        tenant_id=scope,
        action=action,
        from_date=from_date,
        to_date=to_date,
        page=1,
        size=limit,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "created_at",
            "tenant_id",
            "user_id",
            "actor",
            "action",
            "resource_type",
            "resource_id",
            "result",
            "ip_address",
            "method",
            "path",
            "status_code",
            "error",
            "prev_hash",
            "entry_hash",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.id,
                row.created_at.isoformat() if row.created_at else "",
                row.tenant_id,
                row.user_id,
                row.actor or "",
                row.action,
                row.resource_type,
                row.resource_id or "",
                row.result.value if hasattr(row.result, "value") else row.result,
                row.ip_address or "",
                row.method or "",
                row.path or "",
                row.status_code or "",
                row.error or "",
                row.prev_hash or "",
                row.entry_hash or "",
            ]
        )

    buffer.seek(0)
    filename = f"ofme-audit-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/events/{aggregate_type}/{aggregate_id}",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.AUDIT_READ))],
    summary="Replay the domain event stream of an aggregate",
)
async def aggregate_events(
    aggregate_type: str,
    aggregate_id: str,
    session: SessionDep,
    principal: CurrentPrincipal,
    x_tenant_id: TenantHeader = None,
) -> list[dict]:
    scope = _resolve_scope(principal, x_tenant_id)
    records = await EventStoreService(session).for_aggregate(aggregate_type, aggregate_id)
    return [
        {
            "id": record.id,
            "event_id": record.event_id,
            "tenant_id": record.tenant_id,
            "aggregate_type": record.aggregate_type,
            "aggregate_id": record.aggregate_id,
            "event_type": record.event_type,
            "sequence": record.sequence,
            "payload": record.payload,
            "previous_hash": record.previous_hash,
            "event_hash": record.event_hash,
            "occurred_at": record.occurred_at,
        }
        for record in records
        if scope is None or record.tenant_id == scope
    ]


@router.get(
    "/{entry_id}",
    response_model=AuditLogOut,
    dependencies=[Depends(require_permissions(P.AUDIT_READ))],
    summary="Get a single audit entry",
)
async def get_audit_entry(
    entry_id: int,
    session: SessionDep,
    principal: CurrentPrincipal,
    x_tenant_id: TenantHeader = None,
) -> AuditLogOut:
    scope = _resolve_scope(principal, x_tenant_id)
    entry = await session.get(AuditLog, entry_id)
    if entry is None or (scope is not None and entry.tenant_id != scope):
        raise NotFoundError("Audit entry not found")
    return AuditLogOut.model_validate(entry)
