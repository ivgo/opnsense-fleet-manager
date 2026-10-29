"""Operational aggregates: scheduled tasks, jobs, backups, alerts, notifications."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    BackupType,
    JobStatus,
    MaintenanceTarget,
    NotificationType,
    ReportKind,
    ReportStatus,
    TaskKind,
)


class Task(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Cron-like schedule owned by a tenant (materialised by Celery beat)."""

    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_tenant_enabled", "tenant_id", "enabled"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[TaskKind] = mapped_column(
        SAEnum(TaskKind, native_enum=False, length=32), default=TaskKind.CUSTOM, nullable=False
    )
    cron: Mapped[str] = mapped_column(String(64), default="0 2 * * *", nullable=False)
    payload: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class Job(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_tenant_status", "tenant_id", "status", "created_at"),
        Index("ix_jobs_celery", "celery_task_id"),
    )

    task_name: Mapped[str] = mapped_column(String(128), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, native_enum=False, length=16), default=JobStatus.PENDING, nullable=False
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    params: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class Backup(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "backups"
    __table_args__ = (Index("ix_backups_tenant_device", "tenant_id", "device_id", "created_at"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[BackupType] = mapped_column(
        SAEnum(BackupType, native_enum=False, length=16), default=BackupType.MANUAL, nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    config_version: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class AlertRule(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "alert_rules"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(8), default=">", nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        SAEnum(AlertSeverity, native_enum=False, length=16), default=AlertSeverity.WARNING, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    device_selector: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    channels: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)


class Alert(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_tenant_status", "tenant_id", "status", "severity"),
        Index("ix_alerts_device_started", "device_id", "starts_at"),
    )

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("alert_rules.id"))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[AlertSeverity] = mapped_column(
        SAEnum(AlertSeverity, native_enum=False, length=16), default=AlertSeverity.INFO, nullable=False
    )
    status: Mapped[AlertStatus] = mapped_column(
        SAEnum(AlertStatus, native_enum=False, length=16), default=AlertStatus.FIRING, nullable=False
    )
    labels: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "read", "created_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType, native_enum=False, length=16), default=NotificationType.INFO, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        SAEnum(AlertSeverity, native_enum=False, length=16), default=AlertSeverity.INFO, nullable=False
    )
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action_url: Mapped[str | None] = mapped_column(String(512))
    #: Per-channel delivery outcome, e.g. ``{"slack:...": {"status": "sent"}}``.
    delivery: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(JSONB), default=dict)


class MaintenanceWindow(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Quiet hours: suppress alerting for a fleet, device, site or group."""

    __tablename__ = "maintenance_windows"
    __table_args__ = (Index("ix_maintenance_windows_tenant_window", "tenant_id", "starts_at", "ends_at"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    target_type: Mapped[MaintenanceTarget] = mapped_column(
        SAEnum(MaintenanceTarget, native_enum=False, length=16),
        default=MaintenanceTarget.FLEET,
        nullable=False,
    )
    #: Device, site or group UUIDs as strings; empty for a fleet-wide window.
    target_ids: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    silence_alerts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    silence_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class Report(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """A generated PDF report and the parameters it was produced with."""

    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_tenant_created", "tenant_id", "created_at"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[ReportKind] = mapped_column(
        SAEnum(ReportKind, native_enum=False, length=16), default=ReportKind.FLEET, nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(
        SAEnum(ReportStatus, native_enum=False, length=16), default=ReportStatus.PENDING, nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    params: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    storage_key: Mapped[str | None] = mapped_column(String(512))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
