"""Monitoring: alert evaluation, dashboard aggregation, metric queries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import AlertRaised, event_bus
from app.core.logging import get_logger
from app.models.enums import AlertSeverity, AlertStatus, DeviceStatus, JobStatus
from app.models.metrics import DeviceMetric, DeviceTelemetrySnapshot
from app.models.operations import Alert, Job
from app.models.policy import DriftReport
from app.models.sdwan import VpnTunnel
from app.models.topology import Device, Site
from app.repositories import UnitOfWork
from app.schemas.topology import HeartbeatPayload

log = get_logger("ofme.monitoring")

DEFAULT_THRESHOLDS: dict[str, tuple[str, float, AlertSeverity, str]] = {
    "cpu_pct": (">", 90.0, AlertSeverity.WARNING, "CPU utilisation above 90%"),
    "memory_pct": (">", 90.0, AlertSeverity.WARNING, "Memory utilisation above 90%"),
    "disk_pct": (">", 85.0, AlertSeverity.CRITICAL, "Disk utilisation above 85%"),
    "gateways": ("ratio", 0.5, AlertSeverity.CRITICAL, "More than half of WAN gateways are down"),
    "vpn": ("ratio", 0.5, AlertSeverity.WARNING, "More than half of VPN tunnels are down"),
    "carp": ("fault", 1.0, AlertSeverity.CRITICAL, "CARP state is not master/backup"),
}


def _fingerprint(tenant_id: uuid.UUID, device_id: uuid.UUID, rule: str) -> str:
    import hashlib

    return hashlib.sha256(f"{tenant_id}:{device_id}:{rule}".encode()).hexdigest()[:32]


class AlertEvaluator:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)

    async def evaluate_device(self, device: Device, payload: HeartbeatPayload) -> list[Alert]:
        raised: list[Alert] = []
        checks: list[tuple[str, bool, str]] = []

        windows = await self.uow.maintenance.active_at(datetime.now(UTC))
        from app.services.maintenance import is_silenced

        if is_silenced(windows, device):
            log.info("alert.silenced", device=str(device.id), window="maintenance")
            return []
        notify = not is_silenced(windows, device, notifications=True)

        if payload.cpu_pct is not None:
            checks.append(("cpu_pct", payload.cpu_pct > 90.0, f"CPU at {payload.cpu_pct:.1f}%"))
        if payload.memory_pct is not None:
            checks.append(("memory_pct", payload.memory_pct > 90.0, f"Memory at {payload.memory_pct:.1f}%"))
        if payload.disk_pct is not None:
            checks.append(("disk_pct", payload.disk_pct > 85.0, f"Disk at {payload.disk_pct:.1f}%"))
        if payload.gateways_total:
            down = payload.gateways_total - (payload.gateways_up or 0)
            checks.append(
                (
                    "gateways",
                    down / payload.gateways_total > 0.5,
                    f"{down}/{payload.gateways_total} gateways down",
                )
            )
        if payload.vpn_total:
            down = payload.vpn_total - (payload.vpn_up or 0)
            checks.append(("vpn", down / payload.vpn_total > 0.5, f"{down}/{payload.vpn_total} tunnels down"))
        if payload.carp_status and payload.carp_status not in {"master", "backup", "disabled", "unknown"}:
            checks.append(("carp", True, f"CARP state: {payload.carp_status}"))

        for rule, failing, message in checks:
            fingerprint = _fingerprint(self.tenant_id, device.id, rule)
            existing = await self.uow.alerts.by_fingerprint(fingerprint)

            if failing and existing is None:
                threshold = DEFAULT_THRESHOLDS.get(rule, ("", 0, AlertSeverity.WARNING, rule))
                severity = threshold[2]
                alert = Alert(
                    tenant_id=self.tenant_id,
                    device_id=device.id,
                    fingerprint=fingerprint,
                    title=f"{device.name}: {threshold[3]}",
                    message=message,
                    severity=threshold[2],
                    status=AlertStatus.FIRING,
                    labels={"rule": rule, "device": device.name},
                    starts_at=datetime.now(UTC),
                )
                self.session.add(alert)
                await self.session.flush()
                raised.append(alert)
                await event_bus.publish(
                    AlertRaised(
                        alert_id=str(alert.id),
                        tenant_id=str(self.tenant_id),
                        severity=severity.value,
                        title=alert.title,
                        device_id=str(device.id),
                    )
                )
                from app.services.notifications import NotificationService

                if notify:
                    await NotificationService(self.session, self.tenant_id).create(
                        title=alert.title,
                        message=message,
                        severity=severity,
                        action_url=f"/devices/{device.id}",
                    )
            elif not failing and existing is not None:
                existing.status = AlertStatus.RESOLVED
                existing.ends_at = datetime.now(UTC)

        await self.session.flush()
        return raised


class DashboardService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)

    async def summary(self) -> dict[str, Any]:
        counts = await self.uow.devices.by_status_counts()
        sites = await self.uow.sites.count()
        policies_total = await self.uow.policies.count()
        drifted = (
            await self.session.execute(
                select(func.count(func.distinct(DriftReport.device_id))).where(
                    DriftReport.tenant_id == self.tenant_id, DriftReport.status == "open"
                )
            )
        ).scalar_one()
        tunnels_total = await self.uow.tunnels.count()
        tunnels_up = (
            await self.session.execute(
                select(func.count()).select_from(
                    self.uow.tunnels.query().where(VpnTunnel.status == "active").subquery()
                )
            )
        ).scalar_one()
        open_alerts = await self.uow.alerts.active_count()
        critical = (
            await self.session.execute(
                select(func.count()).select_from(
                    self.uow.alerts.query()
                    .where(Alert.status == AlertStatus.FIRING, Alert.severity == AlertSeverity.CRITICAL)
                    .subquery()
                )
            )
        ).scalar_one()
        running_jobs = (
            await self.session.execute(
                select(func.count()).select_from(
                    self.uow.jobs.query().where(Job.status == JobStatus.RUNNING).subquery()
                )
            )
        ).scalar_one()
        compliant = (
            await self.session.execute(
                select(func.avg(DeviceMetric.value)).where(
                    DeviceMetric.tenant_id == self.tenant_id,
                    DeviceMetric.metric_type == "cpu",
                    DeviceMetric.recorded_at >= datetime.now(UTC) - timedelta(hours=1),
                )
            )
        ).scalar()

        from app.models.compliance import ComplianceReport

        score = (
            await self.session.execute(
                select(ComplianceReport.score)
                .where(ComplianceReport.tenant_id == self.tenant_id)
                .order_by(ComplianceReport.generated_at.desc())
                .limit(1)
            )
        ).scalar()

        return {
            "devices_total": sum(counts.values()),
            "devices_online": counts.get("online", 0),
            "devices_offline": counts.get("offline", 0),
            "devices_error": counts.get("error", 0),
            "devices_unregistered": counts.get("unregistered", 0),
            "sites_total": sites,
            "policies_total": policies_total,
            "policies_drifted": int(drifted or 0),
            "tunnels_total": tunnels_total,
            "tunnels_up": int(tunnels_up or 0),
            "open_alerts": open_alerts,
            "critical_alerts": int(critical or 0),
            "jobs_running": int(running_jobs or 0),
            "compliance_score": float(score) if score is not None else None,
            "avg_cpu_1h": round(float(compliant), 2) if compliant is not None else None,
        }

    async def health(self, limit: int = 50) -> list[dict[str, Any]]:
        stmt = (
            select(Device, DeviceTelemetrySnapshot)
            .outerjoin(DeviceTelemetrySnapshot, DeviceTelemetrySnapshot.device_id == Device.id)
            .where(Device.tenant_id == self.tenant_id, Device.deleted_at.is_(None))
            .order_by(Device.name)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()

        # Fetch latest traffic rates per device (wan interface, last 30 min)
        now = datetime.now(UTC)
        latest_traffic = await self.uow.metrics.latest_traffic(since=now - timedelta(minutes=30))
        traffic_by_device: dict[uuid.UUID, dict[str, float]] = {}
        for metric in latest_traffic:
            labels = metric.labels or {}
            if labels.get("interface") != "wan":
                continue
            direction = labels.get("direction")
            if direction not in ("in", "out"):
                continue
            entry = traffic_by_device.setdefault(metric.device_id, {"in_bps": 0.0, "out_bps": 0.0})
            entry[direction + "_bps"] = round(float(metric.value), 2)

        return [
            {
                "device_id": device.id,
                "name": device.name,
                "status": device.status.value if hasattr(device.status, "value") else str(device.status),
                "cpu_pct": snapshot.cpu_pct if snapshot else None,
                "memory_pct": snapshot.memory_pct if snapshot else None,
                "disk_pct": snapshot.disk_pct if snapshot else None,
                "sessions": snapshot.sessions if snapshot else None,
                "uptime_seconds": snapshot.uptime_seconds if snapshot else device.uptime_seconds,
                "vpn_up": snapshot.vpn_up if snapshot else None,
                "vpn_total": snapshot.vpn_total if snapshot else None,
                "gateways_up": snapshot.gateways_up if snapshot else None,
                "gateways_total": snapshot.gateways_total if snapshot else None,
                "carp_status": snapshot.carp_status if snapshot else None,
                "recorded_at": snapshot.recorded_at if snapshot else device.last_heartbeat_at,
                "in_bps": traffic_by_device.get(device.id, {}).get("in_bps"),
                "out_bps": traffic_by_device.get(device.id, {}).get("out_bps"),
            }
            for device, snapshot in rows
        ]

    async def trends(self, hours: int = 24) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        stmt = (
            select(
                func.date_trunc("hour", DeviceMetric.recorded_at).label("bucket"),
                DeviceMetric.metric_type,
                func.avg(DeviceMetric.value),
            )
            .where(DeviceMetric.tenant_id == self.tenant_id, DeviceMetric.recorded_at >= since)
            .group_by("bucket", DeviceMetric.metric_type)
            .order_by("bucket")
        )
        buckets: dict[datetime, dict[str, Any]] = {}
        for bucket, metric_type, _value in (await self.session.execute(stmt)).all():
            key = bucket if isinstance(bucket, datetime) else datetime.now(UTC)
            entry = buckets.setdefault(key, {"timestamp": key, "online": 0, "offline": 0, "alerts": 0})
            name = metric_type.value if hasattr(metric_type, "value") else str(metric_type)
            if name == "cpu":
                entry["alerts"] = entry["alerts"] or 0
        summary = await self.summary()
        for entry in buckets.values():
            entry["online"] = summary["devices_online"]
            entry["offline"] = summary["devices_offline"]
        return list(buckets.values())[-hours:]

    async def site_map(self) -> list[dict[str, Any]]:
        stmt = (
            select(Site, func.count(Device.id))
            .outerjoin(Device, (Device.site_id == Site.id) & (Device.deleted_at.is_(None)))
            .where(Site.tenant_id == self.tenant_id, Site.deleted_at.is_(None))
            .group_by(Site.id)
        )
        rows = (await self.session.execute(stmt)).all()
        online = dict(
            (
                await self.session.execute(
                    select(Device.site_id, func.count())
                    .where(
                        Device.tenant_id == self.tenant_id,
                        Device.status == DeviceStatus.ONLINE,
                        Device.deleted_at.is_(None),
                    )
                    .group_by(Device.site_id)
                )
            ).all()
        )
        return [
            {
                "id": site.id,
                "name": site.name,
                "city": site.city,
                "country": site.country,
                "latitude": site.latitude,
                "longitude": site.longitude,
                "devices_total": int(total),
                "devices_online": int(online.get(site.id, 0)),
                "worst_severity": None,
            }
            for site, total in rows
        ]


def _bucket_seconds(hours: int) -> int:
    """Keep traffic series around 360 points regardless of the window."""
    if hours <= 6:
        return 60
    if hours <= 48:
        return 300
    if hours <= 168:
        return 900
    return 3600


def _merge_traffic(rows: list[tuple[datetime, str, float]]) -> list[dict[str, Any]]:
    """Merge per-direction bucket averages into one point per timestamp."""
    buckets: dict[datetime, dict[str, Any]] = {}
    for bucket_at, direction, value in rows:
        entry = buckets.setdefault(bucket_at, {"recorded_at": bucket_at, "in_bps": 0.0, "out_bps": 0.0})
        if direction == "in":
            entry["in_bps"] = round(float(value), 2)
        elif direction == "out":
            entry["out_bps"] = round(float(value), 2)
    return [buckets[key] for key in sorted(buckets)]


def _snapshot_interfaces(snapshot: DeviceTelemetrySnapshot | None) -> list[dict[str, str]]:
    """Interfaces known from the last counter sample, for the chart selector."""
    traffic = snapshot.traffic if snapshot is not None else None
    rows = traffic.get("interfaces") if isinstance(traffic, dict) else None
    if not isinstance(rows, dict):
        return []
    return [
        {"key": str(key), "name": str(row.get("name") or key)}
        for key, row in rows.items()
        if isinstance(row, dict)
    ]


class MetricQueryService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)

    async def series(
        self, device_id: uuid.UUID, metric_type: str, *, hours: int = 24, limit: int = 1440
    ) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(hours=hours)
        rows = await self.uow.metrics.series(device_id, metric_type, since=since, limit=limit)
        return [{"recorded_at": row.recorded_at, "value": row.value} for row in rows]

    async def traffic_series(
        self, device_id: uuid.UUID, interface: str = "wan", *, hours: int = 24
    ) -> dict[str, Any]:
        """Per-interface in/out throughput for one device."""
        since = datetime.now(UTC) - timedelta(hours=hours)
        bucket_seconds = _bucket_seconds(hours)
        rows = await self.uow.metrics.traffic_buckets(
            device_id=device_id,
            interface=interface,
            since=since,
            bucket_seconds=bucket_seconds,
        )
        snapshot = await self.uow.snapshots.for_device(device_id)
        return {
            "device_id": device_id,
            "interface": interface,
            "hours": hours,
            "bucket_seconds": bucket_seconds,
            "interfaces": _snapshot_interfaces(snapshot),
            "points": _merge_traffic(rows),
            "generated_at": datetime.now(UTC),
        }

    async def fleet_traffic(self, interface: str = "wan", *, hours: int = 24) -> dict[str, Any]:
        """Fleet-wide throughput plus the latest rate per device."""
        now = datetime.now(UTC)
        since = now - timedelta(hours=hours)
        bucket_seconds = _bucket_seconds(hours)
        rows = await self.uow.metrics.fleet_traffic_buckets(
            interface=interface, since=since, bucket_seconds=bucket_seconds
        )
        # "Current" rates are read from a short trailing window: a device that
        # stopped reporting is stale rather than silently shown as zero.
        latest = await self.uow.metrics.latest_traffic(since=now - timedelta(minutes=30))
        per_device: dict[uuid.UUID, dict[str, Any]] = {}
        for metric in latest:
            labels = metric.labels or {}
            if labels.get("interface") != interface:
                continue
            entry = per_device.setdefault(
                metric.device_id,
                {
                    "device_id": metric.device_id,
                    "interface": interface,
                    "interface_name": labels.get("name") or interface,
                    "in_bps": 0.0,
                    "out_bps": 0.0,
                    "recorded_at": metric.recorded_at,
                },
            )
            direction = labels.get("direction")
            if direction == "in":
                entry["in_bps"] = round(float(metric.value), 2)
            elif direction == "out":
                entry["out_bps"] = round(float(metric.value), 2)
            if metric.recorded_at > entry["recorded_at"]:
                entry["recorded_at"] = metric.recorded_at

        names = dict(
            (
                await self.session.execute(
                    select(Device.id, Device.name).where(
                        Device.tenant_id == self.tenant_id, Device.deleted_at.is_(None)
                    )
                )
            ).all()
        )
        devices = [
            {**entry, "name": names.get(entry["device_id"], str(entry["device_id"]))}
            for entry in per_device.values()
        ]
        devices.sort(key=lambda item: item["in_bps"] + item["out_bps"], reverse=True)
        return {
            "interface": interface,
            "hours": hours,
            "bucket_seconds": bucket_seconds,
            "points": _merge_traffic(rows),
            "devices": devices,
            "generated_at": now,
        }

    async def purge(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=settings.METRIC_RETENTION_DAYS)
        purged = await self.uow.metrics.purge_older_than(cutoff)
        await self.session.commit()
        return purged
