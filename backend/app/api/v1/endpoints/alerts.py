"""Alerting: alert lifecycle, alert rules and in-app notifications."""

from __future__ import annotations

import operator
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select, update

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import BadRequestError
from app.models.enums import AlertSeverity, AlertStatus
from app.models.metrics import DeviceTelemetrySnapshot
from app.models.operations import Alert, Notification
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.operations import (
    AlertAcknowledge,
    AlertOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    NotificationCreate,
    NotificationOut,
)
from app.services.notifications import NotificationService

alerts_router = APIRouter(prefix="/alerts", tags=["Alerts"])
alert_rules_router = APIRouter(prefix="/alert-rules", tags=["Alert rules"])
notifications_router = APIRouter(prefix="/notifications", tags=["Notifications"])

_OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

_METRIC_FIELDS = {
    "cpu_pct": "cpu_pct",
    "cpu": "cpu_pct",
    "memory_pct": "memory_pct",
    "memory": "memory_pct",
    "disk_pct": "disk_pct",
    "disk": "disk_pct",
    "load_1m": "load_1m",
    "sessions": "sessions",
    "vpn_up": "vpn_up",
    "gateways_up": "gateways_up",
}


# --------------------------------------------------------------------------- alerts
@alerts_router.get(
    "",
    response_model=PageResponse[AlertOut],
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="List alerts",
)
async def list_alerts(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    status_filter: AlertStatus | None = Query(None, alias="status"),
    severity: AlertSeverity | None = None,
    device_id: uuid.UUID | None = None,
) -> PageResponse[AlertOut]:
    filters: dict[str, object] = {"device_id": device_id}
    if status_filter is not None:
        filters["status"] = status_filter
    if severity is not None:
        filters["severity"] = severity
    rows, total = await UnitOfWork(session, tenant_id).alerts.list(
        filters=filters,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "starts_at",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, AlertOut)


@alerts_router.get(
    "/counts",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="Alert counters by severity",
)
async def alert_counts(session: SessionDep, tenant_id: TenantDep) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Alert.severity, func.count())
            .where(
                Alert.tenant_id == tenant_id, Alert.status.in_([AlertStatus.FIRING, AlertStatus.ACKNOWLEDGED])
            )
            .group_by(Alert.severity)
        )
    ).all()
    counts = {severity.value: 0 for severity in AlertSeverity}
    for value, count in rows:
        key = value.value if hasattr(value, "value") else str(value)
        counts[key] = int(count)
    counts["total"] = sum(counts.values())
    return counts


@alerts_router.get(
    "/{alert_id}",
    response_model=AlertOut,
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="Get an alert",
)
async def get_alert(alert_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> AlertOut:
    return AlertOut.model_validate(await UnitOfWork(session, tenant_id).alerts.get_or_404(alert_id))


@alerts_router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertOut,
    dependencies=[Depends(require_permissions(P.ALERT_ACK))],
    summary="Acknowledge an alert",
)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    payload: AlertAcknowledge,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> AlertOut:
    alert = await UnitOfWork(session, tenant_id).alerts.get_or_404(alert_id)
    if alert.status == AlertStatus.RESOLVED:
        raise BadRequestError("A resolved alert cannot be acknowledged")
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = datetime.now(UTC)
    alert.acknowledged_by = principal.user_id
    if payload.comment:
        alert.labels = {**(alert.labels or {}), "acknowledge_comment": payload.comment[:500]}
    await session.commit()
    return AlertOut.model_validate(alert)


@alerts_router.post(
    "/{alert_id}/resolve",
    response_model=AlertOut,
    dependencies=[Depends(require_permissions(P.ALERT_ACK))],
    summary="Resolve an alert",
)
async def resolve_alert(
    alert_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> AlertOut:
    alert = await UnitOfWork(session, tenant_id).alerts.get_or_404(alert_id)
    alert.status = AlertStatus.RESOLVED
    alert.ends_at = datetime.now(UTC)
    alert.acknowledged_by = alert.acknowledged_by or principal.user_id
    alert.acknowledged_at = alert.acknowledged_at or datetime.now(UTC)
    await session.commit()
    return AlertOut.model_validate(alert)


# --------------------------------------------------------------------------- rules
@alert_rules_router.get(
    "",
    response_model=PageResponse[AlertRuleOut],
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="List alert rules",
)
async def list_alert_rules(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    enabled: bool | None = Query(None),
) -> PageResponse[AlertRuleOut]:
    filters: dict[str, object] = {}
    if enabled is not None:
        filters["enabled"] = enabled
    rows, total = await UnitOfWork(session, tenant_id).alert_rules.list(
        filters=filters,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "name",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, AlertRuleOut)


@alert_rules_router.post(
    "",
    response_model=AlertRuleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.ALERT_WRITE))],
    summary="Create an alert rule",
)
async def create_alert_rule(
    payload: AlertRuleCreate,
    session: SessionDep,
    tenant_id: TenantDep,
) -> AlertRuleOut:
    uow = UnitOfWork(session, tenant_id)
    if await uow.alert_rules.find_one(name=payload.name):
        raise BadRequestError(f"Alert rule '{payload.name}' already exists")
    rule = await uow.alert_rules.create(**payload.model_dump())
    await session.commit()
    return AlertRuleOut.model_validate(rule)


@alert_rules_router.patch(
    "/{rule_id}",
    response_model=AlertRuleOut,
    dependencies=[Depends(require_permissions(P.ALERT_WRITE))],
    summary="Update an alert rule",
)
async def update_alert_rule(
    rule_id: uuid.UUID,
    payload: AlertRuleUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
) -> AlertRuleOut:
    uow = UnitOfWork(session, tenant_id)
    rule = await uow.alert_rules.get_or_404(rule_id)
    await uow.alert_rules.update(rule, **payload.model_dump(exclude_unset=True))
    await session.commit()
    return AlertRuleOut.model_validate(rule)


@alert_rules_router.delete(
    "/{rule_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.ALERT_WRITE))],
    summary="Delete an alert rule",
)
async def delete_alert_rule(rule_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    await uow.alert_rules.delete(await uow.alert_rules.get_or_404(rule_id))
    await session.commit()
    return Message(message="Alert rule deleted")


@alert_rules_router.post(
    "/{rule_id}/test",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="Evaluate a rule against current device telemetry",
)
async def test_alert_rule(rule_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> dict:
    rule = await UnitOfWork(session, tenant_id).alert_rules.get_or_404(rule_id)
    field = _METRIC_FIELDS.get(rule.metric)
    compare = _OPERATORS.get(rule.operator)
    if field is None or compare is None:
        raise BadRequestError(f"Unsupported metric '{rule.metric}' or operator '{rule.operator}'")

    stmt = select(DeviceTelemetrySnapshot).where(DeviceTelemetrySnapshot.tenant_id == tenant_id).limit(5000)
    selector = rule.device_selector or {}
    raw_device_ids = selector.get("device_ids")
    device_ids: list[uuid.UUID] = []
    if isinstance(raw_device_ids, list | tuple | set):
        for raw_device_id in raw_device_ids:
            try:
                device_ids.append(uuid.UUID(str(raw_device_id)))
            except (AttributeError, TypeError, ValueError):
                continue
    if device_ids:
        stmt = stmt.where(DeviceTelemetrySnapshot.device_id.in_(device_ids))
    snapshots = (await session.execute(stmt)).scalars().all()

    matched: list[dict] = []
    for snapshot in snapshots:
        value = getattr(snapshot, field, None)
        if value is None:
            continue
        if compare(float(value), float(rule.threshold)):
            matched.append(
                {
                    "device_id": str(snapshot.device_id),
                    "metric": rule.metric,
                    "value": float(value),
                    "threshold": rule.threshold,
                }
            )
    return {"rule": rule.name, "evaluated": len(snapshots), "matched": len(matched), "results": matched}


# --------------------------------------------------------------------------- notifications
@notifications_router.get(
    "",
    response_model=PageResponse[NotificationOut],
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="List notifications for the current user",
)
async def list_notifications(
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
    pagination: PaginationDep,
    unread_only: bool = Query(False),
) -> PageResponse[NotificationOut]:
    if principal.user_id is None:
        raise BadRequestError("Notifications require a user principal")
    stmt = (
        UnitOfWork(session, tenant_id)
        .notifications.query()
        .where(or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None)))
    )
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (
        (
            await session.execute(
                stmt.order_by(Notification.created_at.desc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            )
        )
        .scalars()
        .all()
    )
    return paginate(rows, total, pagination, NotificationOut)


@notifications_router.post(
    "",
    response_model=NotificationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.ALERT_WRITE))],
    summary="Create a notification and dispatch it to external channels",
    description=(
        "Channels are `email`, `slack:<webhook-url>` and `webhook:<url>`. "
        "Each channel outcome is stored in `delivery`."
    ),
)
async def create_notification(
    payload: NotificationCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> NotificationOut:
    notification = await NotificationService(session, tenant_id, principal.user_id).create(
        title=payload.title,
        message=payload.message,
        type_=payload.type,
        severity=payload.severity,
        user_id=payload.user_id,
        action_url=payload.action_url,
        channels=payload.channels,
        metadata=payload.metadata,
    )
    await session.commit()
    return NotificationOut.model_validate(notification)


@notifications_router.post(
    "/{notification_id}/read",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="Mark a notification as read",
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    if principal.user_id is None:
        raise BadRequestError("Notifications require a user principal")
    await NotificationService(session, tenant_id).mark_read(notification_id, principal.user_id)
    await session.commit()
    return Message(message="Notification marked as read")


@notifications_router.post(
    "/read-all",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="Mark every notification of the current user as read",
)
async def mark_all_read(
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> dict[str, int]:
    if principal.user_id is None:
        raise BadRequestError("Notifications require a user principal")
    result = await session.execute(
        update(Notification)
        .where(
            Notification.tenant_id == tenant_id,
            Notification.read.is_(False),
            or_(Notification.user_id == principal.user_id, Notification.user_id.is_(None)),
        )
        .values(read=True, read_at=datetime.now(UTC))
    )
    await session.commit()
    return {"updated": int(result.rowcount or 0)}


@notifications_router.delete(
    "/{notification_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.ALERT_READ))],
    summary="Delete a notification",
)
async def delete_notification(
    notification_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    if principal.user_id is None:
        raise BadRequestError("Notifications require a user principal")
    await NotificationService(session, tenant_id, principal.user_id).delete(
        notification_id, principal.user_id
    )
    await session.commit()
    return Message(message="Notification deleted")
