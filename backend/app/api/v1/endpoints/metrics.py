"""Monitoring reads: fleet dashboard, device health and metric series."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import SessionDep, TenantDep, require_permissions
from app.models.enums import AlertSeverity, AlertStatus, MetricType
from app.models.operations import Alert
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.operations import (
    AlertOut,
    DashboardOverview,
    DashboardTrend,
    DeviceHealth,
    FleetSummary,
    FleetTraffic,
    MetricPoint,
    MetricSeries,
    TrafficSeries,
)
from app.services.monitoring import DashboardService, MetricQueryService

router = APIRouter(prefix="/metrics", tags=["Monitoring"])

_UNITS = {
    MetricType.CPU: "%",
    MetricType.MEMORY: "%",
    MetricType.DISK: "%",
    MetricType.LOAD: None,
    MetricType.INTERFACE: None,
    MetricType.TRAFFIC: "bps",
    MetricType.GATEWAY: "gateways",
    MetricType.VPN: "tunnels",
    MetricType.CARP: None,
    MetricType.UPTIME: "s",
    MetricType.SESSIONS: "count",
}


def _fleet_summary(raw: dict) -> FleetSummary:
    """Project the dashboard aggregate onto the public contract.

    ``DashboardService.summary`` also returns convenience keys (for example
    ``avg_cpu_1h``) that are intentionally not part of ``FleetSummary``.
    """
    return FleetSummary.model_validate(
        {key: value for key, value in raw.items() if key in FleetSummary.model_fields}
    )


@router.get(
    "/summary",
    response_model=FleetSummary,
    dependencies=[Depends(require_permissions(P.METRIC_READ))],
    summary="Fleet counters",
)
async def fleet_summary(session: SessionDep, tenant_id: TenantDep) -> FleetSummary:
    return _fleet_summary(await DashboardService(session, tenant_id).summary())


@router.get(
    "/health",
    response_model=list[DeviceHealth],
    dependencies=[Depends(require_permissions(P.METRIC_READ))],
    summary="Latest telemetry snapshot per device",
)
async def fleet_health(
    session: SessionDep,
    tenant_id: TenantDep,
    limit: int = Query(200, ge=1, le=1000),
) -> list[DeviceHealth]:
    rows = await DashboardService(session, tenant_id).health(limit=limit)
    return [DeviceHealth.model_validate(row) for row in rows]


@router.get(
    "/trends",
    response_model=list[DashboardTrend],
    dependencies=[Depends(require_permissions(P.METRIC_READ))],
    summary="Hourly fleet trends",
)
async def fleet_trends(
    session: SessionDep,
    tenant_id: TenantDep,
    hours: int = Query(24, ge=1, le=720),
) -> list[DashboardTrend]:
    rows = await DashboardService(session, tenant_id).trends(hours=hours)
    return [DashboardTrend.model_validate(row) for row in rows]


@router.get(
    "/dashboard",
    response_model=DashboardOverview,
    dependencies=[Depends(require_permissions(P.METRIC_READ))],
    summary="Composite dashboard payload",
)
async def dashboard(
    session: SessionDep,
    tenant_id: TenantDep,
    health_limit: int = Query(50, ge=1, le=500),
    trend_hours: int = Query(24, ge=1, le=720),
) -> DashboardOverview:
    service = DashboardService(session, tenant_id)
    summary = _fleet_summary(await service.summary())
    health = [DeviceHealth.model_validate(row) for row in await service.health(limit=health_limit)]
    trends = [DashboardTrend.model_validate(row) for row in await service.trends(hours=trend_hours)]

    uow = UnitOfWork(session, tenant_id)
    alerts = await uow.alerts.open_alerts(limit=20)

    severity_rows = (
        await session.execute(
            select(Alert.severity, func.count())
            .where(
                Alert.tenant_id == tenant_id,
                Alert.status.in_([AlertStatus.FIRING, AlertStatus.ACKNOWLEDGED]),
            )
            .group_by(Alert.severity)
        )
    ).all()
    by_severity = {severity.value: 0 for severity in AlertSeverity}
    for value, count in severity_rows:
        key = value.value if hasattr(value, "value") else str(value)
        by_severity[key] = int(count)

    return DashboardOverview(
        summary=summary,
        health=health,
        alerts=[AlertOut.model_validate(alert) for alert in alerts],
        trends=trends,
        top_alerts_by_severity=by_severity,
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/devices/{device_id}/series",
    response_model=MetricSeries,
    dependencies=[Depends(require_permissions(P.METRIC_READ))],
    summary="Time series for a single device metric",
)
async def device_series(
    device_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    metric_type: MetricType = Query(MetricType.CPU),
    hours: int = Query(24, ge=1, le=2160),
    limit: int = Query(1440, ge=1, le=10000),
) -> MetricSeries:
    await UnitOfWork(session, tenant_id).devices.get_or_404(device_id)
    points = await MetricQueryService(session, tenant_id).series(
        device_id, metric_type.value, hours=hours, limit=limit
    )
    return MetricSeries(
        device_id=device_id,
        metric_type=metric_type,
        unit=_UNITS.get(metric_type),
        points=[MetricPoint.model_validate(point) for point in points],
    )


@router.get(
    "/traffic",
    response_model=FleetTraffic,
    dependencies=[Depends(require_permissions(P.METRIC_READ))],
    summary="Fleet WAN throughput and the latest rate per device",
)
async def fleet_traffic(
    session: SessionDep,
    tenant_id: TenantDep,
    interface: str = Query("wan", pattern=r"^[A-Za-z0-9_.-]{1,32}$"),
    hours: int = Query(24, ge=1, le=720),
) -> FleetTraffic:
    rows = await MetricQueryService(session, tenant_id).fleet_traffic(interface, hours=hours)
    return FleetTraffic.model_validate(rows)


@router.get(
    "/devices/{device_id}/traffic",
    response_model=TrafficSeries,
    dependencies=[Depends(require_permissions(P.METRIC_READ))],
    summary="In/out throughput for one device interface",
)
async def device_traffic(
    device_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    interface: str = Query("wan", pattern=r"^[A-Za-z0-9_.-]{1,32}$"),
    hours: int = Query(24, ge=1, le=2160),
) -> TrafficSeries:
    await UnitOfWork(session, tenant_id).devices.get_or_404(device_id)
    rows = await MetricQueryService(session, tenant_id).traffic_series(device_id, interface, hours=hours)
    return TrafficSeries.model_validate(rows)


@router.get(
    "/aggregate",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.METRIC_READ))],
    summary="Average of every metric over a window",
)
async def aggregate_metrics(
    session: SessionDep,
    tenant_id: TenantDep,
    hours: int = Query(24, ge=1, le=720),
) -> dict:
    from datetime import timedelta

    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = await UnitOfWork(session, tenant_id).metrics.aggregate_since(since)
    return {
        "since": since.isoformat(),
        "hours": hours,
        "averages": {name: round(value, 3) for name, value in rows},
    }
