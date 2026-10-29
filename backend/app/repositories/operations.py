from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.models.compliance import ComplianceReport
from app.models.enums import AlertStatus, JobStatus, MetricType
from app.models.metrics import DeviceMetric, DeviceTelemetrySnapshot
from app.models.operations import (
    Alert,
    AlertRule,
    Backup,
    Job,
    MaintenanceWindow,
    Notification,
    Report,
    Task,
)
from app.models.ztp import ZtpEnrollment
from app.repositories.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    model = Job
    soft_delete = False

    async def by_celery_id(self, celery_task_id: str) -> Job | None:
        stmt = self.query().where(Job.celery_task_id == celery_task_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def by_status(self, status: JobStatus, limit: int = 100) -> list[Job]:
        stmt = self.query().where(Job.status == status).order_by(Job.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())


class TaskRepository(BaseRepository[Task]):
    model = Task
    soft_delete = False

    async def due(self, at: datetime) -> list[Task]:
        stmt = self.query().where(Task.enabled.is_(True), Task.next_run_at <= at)
        return list((await self.session.execute(stmt)).scalars().all())


class BackupRepository(BaseRepository[Backup]):
    model = Backup
    soft_delete = False

    async def for_device(self, device_id: uuid.UUID, limit: int = 20) -> list[Backup]:
        stmt = (
            self.query().where(Backup.device_id == device_id).order_by(Backup.created_at.desc()).limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def storage_usage(self) -> int:
        stmt = select(func.coalesce(func.sum(Backup.size_bytes), 0)).where(Backup.tenant_id == self.tenant_id)
        return int((await self.session.execute(stmt)).scalar_one())


class AlertRuleRepository(BaseRepository[AlertRule]):
    model = AlertRule
    soft_delete = False

    async def enabled_rules(self) -> list[AlertRule]:
        stmt = self.query().where(AlertRule.enabled.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())


class AlertRepository(BaseRepository[Alert]):
    model = Alert
    soft_delete = False

    async def active_count(self) -> int:
        stmt = select(func.count()).select_from(
            self.query().where(Alert.status == AlertStatus.FIRING).subquery()
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def by_fingerprint(self, fingerprint: str) -> Alert | None:
        stmt = self.query().where(Alert.fingerprint == fingerprint, Alert.status == AlertStatus.FIRING)
        return (await self.session.execute(stmt)).scalars().first()

    async def open_alerts(self, limit: int = 10) -> list[Alert]:
        stmt = (
            self.query()
            .where(Alert.status.in_([AlertStatus.FIRING, AlertStatus.ACKNOWLEDGED]))
            .order_by(Alert.starts_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class NotificationRepository(BaseRepository[Notification]):
    model = Notification
    soft_delete = False

    async def unread_for_user(self, user_id: uuid.UUID, limit: int = 50) -> list[Notification]:
        stmt = (
            self.query()
            .where(Notification.user_id == user_id, Notification.read.is_(False))
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class MetricRepository(BaseRepository[DeviceMetric]):
    model = DeviceMetric
    soft_delete = False

    async def series(
        self,
        device_id: uuid.UUID,
        metric_type: str,
        *,
        since: datetime,
        limit: int = 1440,
    ) -> list[DeviceMetric]:
        stmt = (
            self.query()
            .where(
                DeviceMetric.device_id == device_id,
                DeviceMetric.metric_type == metric_type,
                DeviceMetric.recorded_at >= since,
            )
            .order_by(DeviceMetric.recorded_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def aggregate_since(self, since: datetime) -> list[tuple[str, float]]:
        stmt = (
            select(DeviceMetric.metric_type, func.avg(DeviceMetric.value))
            .where(DeviceMetric.tenant_id == self.tenant_id, DeviceMetric.recorded_at >= since)
            .group_by(DeviceMetric.metric_type)
        )
        return [
            (str(row[0].value if hasattr(row[0], "value") else row[0]), float(row[1]))
            for row in (await self.session.execute(stmt)).all()
        ]

    # ------------------------------------------------------------------ traffic
    @staticmethod
    def _traffic_bucket(bucket_seconds: int):  # noqa: ANN205 - SQLAlchemy expression
        return func.to_timestamp(
            func.floor(func.extract("epoch", DeviceMetric.recorded_at) / bucket_seconds) * bucket_seconds
        )

    async def traffic_buckets(
        self,
        *,
        since: datetime,
        bucket_seconds: int,
        device_id: uuid.UUID | None = None,
        interface: str | None = None,
    ) -> list[tuple[datetime, str, float]]:
        """Average traffic rate per time bucket and direction.

        Rates are written per sample; averaging inside a bucket keeps the
        response bounded for long windows without inventing values.
        """
        bucket = self._traffic_bucket(bucket_seconds)
        direction = DeviceMetric.labels["direction"].astext
        stmt = select(bucket.label("bucket"), direction, func.avg(DeviceMetric.value)).where(
            DeviceMetric.tenant_id == self.tenant_id,
            DeviceMetric.metric_type == MetricType.TRAFFIC,
            DeviceMetric.recorded_at >= since,
        )
        if device_id is not None:
            stmt = stmt.where(DeviceMetric.device_id == device_id)
        if interface is not None:
            stmt = stmt.where(DeviceMetric.labels.contains({"interface": interface}))
        stmt = stmt.group_by(bucket, direction).order_by(bucket)
        return [
            (bucket_at, str(direction_value), float(value))
            for bucket_at, direction_value, value in (await self.session.execute(stmt)).all()
        ]

    async def fleet_traffic_buckets(
        self, *, since: datetime, bucket_seconds: int, interface: str | None = None
    ) -> list[tuple[datetime, str, float]]:
        """Fleet throughput: the sum of per-device averages inside each bucket.

        Averaging straight across every sample would report the mean device
        rate instead of the aggregate link load, so the average is taken per
        device first and summed afterwards.
        """
        bucket = self._traffic_bucket(bucket_seconds)
        direction = DeviceMetric.labels["direction"].astext
        per_device = select(
            bucket.label("bucket"),
            DeviceMetric.device_id.label("device_id"),
            direction.label("direction"),
            func.avg(DeviceMetric.value).label("value"),
        ).where(
            DeviceMetric.tenant_id == self.tenant_id,
            DeviceMetric.metric_type == MetricType.TRAFFIC,
            DeviceMetric.recorded_at >= since,
        )
        if interface is not None:
            per_device = per_device.where(DeviceMetric.labels.contains({"interface": interface}))
        inner = per_device.group_by(bucket, DeviceMetric.device_id, direction).subquery()
        stmt = (
            select(inner.c.bucket, inner.c.direction, func.sum(inner.c.value))
            .group_by(inner.c.bucket, inner.c.direction)
            .order_by(inner.c.bucket)
        )
        return [
            (bucket_at, str(direction_value), float(value))
            for bucket_at, direction_value, value in (await self.session.execute(stmt)).all()
        ]

    async def latest_traffic(self, *, since: datetime) -> list[DeviceMetric]:
        """Most recent rate per device, interface and direction."""
        interface = DeviceMetric.labels["interface"].astext
        direction = DeviceMetric.labels["direction"].astext
        stmt = (
            self.query()
            .where(
                DeviceMetric.metric_type == MetricType.TRAFFIC,
                DeviceMetric.recorded_at >= since,
            )
            .order_by(
                DeviceMetric.device_id,
                interface,
                direction,
                DeviceMetric.recorded_at.desc(),
            )
            .distinct(DeviceMetric.device_id, interface, direction)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def purge_older_than(self, cutoff: datetime) -> int:
        from sqlalchemy import delete

        stmt = delete(DeviceMetric).where(DeviceMetric.recorded_at < cutoff)
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)


class SnapshotRepository(BaseRepository[DeviceTelemetrySnapshot]):
    model = DeviceTelemetrySnapshot
    soft_delete = False

    async def for_device(self, device_id: uuid.UUID) -> DeviceTelemetrySnapshot | None:
        stmt = select(DeviceTelemetrySnapshot).where(DeviceTelemetrySnapshot.device_id == device_id)
        return (await self.session.execute(stmt)).scalars().first()


class MaintenanceWindowRepository(BaseRepository[MaintenanceWindow]):
    model = MaintenanceWindow
    soft_delete = False

    async def active_at(self, now: datetime) -> list[MaintenanceWindow]:
        stmt = (
            self.query()
            .where(
                MaintenanceWindow.enabled.is_(True),
                MaintenanceWindow.starts_at <= now,
                MaintenanceWindow.ends_at > now,
            )
            .order_by(MaintenanceWindow.ends_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def upcoming(self, now: datetime, limit: int = 20) -> list[MaintenanceWindow]:
        stmt = (
            self.query()
            .where(MaintenanceWindow.enabled.is_(True), MaintenanceWindow.ends_at > now)
            .order_by(MaintenanceWindow.starts_at)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class ReportRepository(BaseRepository[Report]):
    model = Report
    soft_delete = False

    async def recent(self, limit: int = 50) -> list[Report]:
        stmt = self.query().order_by(Report.created_at.desc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())


class ComplianceReportRepository(BaseRepository[ComplianceReport]):
    model = ComplianceReport
    soft_delete = False

    async def latest(self, framework: str, limit: int = 10) -> list[ComplianceReport]:
        stmt = (
            self.query()
            .where(ComplianceReport.framework == framework)
            .order_by(ComplianceReport.generated_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class ZtpEnrollmentRepository(BaseRepository[ZtpEnrollment]):
    model = ZtpEnrollment
    soft_delete = False

    async def by_token_hash(self, token_hash: str) -> ZtpEnrollment | None:
        stmt = select(ZtpEnrollment).where(ZtpEnrollment.token_hash == token_hash)
        return (await self.session.execute(stmt)).scalars().first()

    async def pending(self) -> list[ZtpEnrollment]:
        stmt = self.query().where(ZtpEnrollment.status == "pending")
        return list((await self.session.execute(stmt)).scalars().all())

    async def expiring(self, within_minutes: int = 10) -> list[ZtpEnrollment]:
        cutoff = datetime.utcnow() + timedelta(minutes=within_minutes)
        stmt = self.query().where(
            ZtpEnrollment.status == "pending",
            ZtpEnrollment.expires_at <= cutoff,
        )
        return list((await self.session.execute(stmt)).scalars().all())
