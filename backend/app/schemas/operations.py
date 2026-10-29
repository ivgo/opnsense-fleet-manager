from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    BackupType,
    JobStatus,
    MaintenanceTarget,
    MetricType,
    NotificationType,
    ReportKind,
    ReportStatus,
    TaskKind,
)
from app.schemas.common import TimestampedModel


class JobOut(TimestampedModel):
    task_name: str
    celery_task_id: str | None
    status: JobStatus
    progress: int
    params: dict
    result: dict | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class TaskCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    kind: TaskKind = TaskKind.CUSTOM
    cron: str = Field("0 2 * * *", min_length=9, max_length=64)
    payload: dict = Field(default_factory=dict)
    enabled: bool = True


class TaskUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    cron: str | None = Field(None, min_length=9, max_length=64)
    payload: dict | None = None
    enabled: bool | None = None


class TaskOut(TimestampedModel):
    name: str
    kind: TaskKind
    cron: str
    payload: dict
    enabled: bool
    last_run_at: datetime | None
    next_run_at: datetime | None


class BackupCreate(BaseModel):
    device_id: uuid.UUID
    type: BackupType = BackupType.MANUAL
    notes: str | None = None


class BackupOut(TimestampedModel):
    device_id: uuid.UUID
    type: BackupType
    storage_key: str
    checksum_sha256: str
    signature: str | None
    size_bytes: int | None
    firmware_version: str | None
    notes: str | None
    is_encrypted: bool


class BackupRestoreRequest(BaseModel):
    backup_id: uuid.UUID
    dry_run: bool = False
    reboot: bool = False


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    metric: str = Field(min_length=2, max_length=64)
    operator: str = Field(">", pattern=r"^(>|>=|<|<=|==|!=)$")
    threshold: float
    duration_seconds: int = Field(300, ge=0, le=86400)
    severity: AlertSeverity = AlertSeverity.WARNING
    enabled: bool = True
    device_selector: dict = Field(default_factory=dict)
    channels: list[str] = Field(default_factory=list)


class AlertRuleOut(TimestampedModel):
    name: str
    metric: str
    operator: str
    threshold: float
    duration_seconds: int
    severity: AlertSeverity
    enabled: bool
    device_selector: dict
    channels: list[str]


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    metric: str | None = Field(None, min_length=2, max_length=64)
    operator: str | None = Field(None, pattern=r"^(>|>=|<|<=|==|!=)$")
    threshold: float | None = None
    duration_seconds: int | None = Field(None, ge=0, le=86400)
    severity: AlertSeverity | None = None
    enabled: bool | None = None
    device_selector: dict | None = None
    channels: list[str] | None = None


class AlertOut(TimestampedModel):
    device_id: uuid.UUID | None
    fingerprint: str
    title: str
    message: str | None
    severity: AlertSeverity
    status: AlertStatus
    labels: dict
    starts_at: datetime
    ends_at: datetime | None
    acknowledged_at: datetime | None


class AlertAcknowledge(BaseModel):
    comment: str | None = None


class NotificationOut(TimestampedModel):
    type: NotificationType
    title: str
    message: str
    severity: AlertSeverity
    read: bool
    action_url: str | None
    delivery: dict
    delivered_at: datetime | None


class NotificationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1)
    type: NotificationType = NotificationType.INFO
    severity: AlertSeverity = AlertSeverity.INFO
    user_id: uuid.UUID | None = None
    action_url: str | None = Field(None, max_length=512)
    channels: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class MetricPoint(BaseModel):
    recorded_at: datetime
    value: float


class MetricSeries(BaseModel):
    device_id: uuid.UUID
    metric_type: MetricType
    unit: str | None
    points: list[MetricPoint]


class MetricQuery(BaseModel):
    metric_type: MetricType
    hours: int = Field(24, ge=1, le=2160)
    limit: int = Field(1440, ge=1, le=10000)


class TrafficInterface(BaseModel):
    key: str
    name: str


class TrafficPoint(BaseModel):
    recorded_at: datetime
    in_bps: float
    out_bps: float


class TrafficSeries(BaseModel):
    device_id: uuid.UUID
    interface: str
    unit: str = "bps"
    hours: int
    bucket_seconds: int
    interfaces: list[TrafficInterface]
    points: list[TrafficPoint]
    generated_at: datetime


class FleetTrafficDevice(BaseModel):
    device_id: uuid.UUID
    name: str
    interface: str
    interface_name: str
    in_bps: float
    out_bps: float
    recorded_at: datetime


class FleetTraffic(BaseModel):
    interface: str
    unit: str = "bps"
    hours: int
    bucket_seconds: int
    points: list[TrafficPoint]
    devices: list[FleetTrafficDevice]
    generated_at: datetime


class DeviceHealth(BaseModel):
    device_id: uuid.UUID
    name: str
    status: str
    cpu_pct: float | None = None
    memory_pct: float | None = None
    disk_pct: float | None = None
    sessions: int | None = None
    uptime_seconds: int | None = None
    vpn_up: int | None = None
    vpn_total: int | None = None
    gateways_up: int | None = None
    gateways_total: int | None = None
    carp_status: str | None = None
    recorded_at: datetime | None = None
    in_bps: float | None = None
    out_bps: float | None = None


class FleetSummary(BaseModel):
    devices_total: int
    devices_online: int
    devices_offline: int
    devices_error: int
    devices_unregistered: int
    sites_total: int
    policies_total: int
    policies_drifted: int
    tunnels_total: int
    tunnels_up: int
    open_alerts: int
    critical_alerts: int
    jobs_running: int
    compliance_score: float | None = None


class DashboardTrend(BaseModel):
    timestamp: datetime
    online: int
    offline: int
    alerts: int


class DashboardOverview(BaseModel):
    summary: FleetSummary
    health: list[DeviceHealth]
    alerts: list[AlertOut]
    trends: list[DashboardTrend]
    top_alerts_by_severity: dict[str, int]
    generated_at: datetime


class ClientDeviceOut(BaseModel):
    id: str
    mac_address: str
    ip_address: str | None
    hostname: str | None
    vendor: str | None
    first_seen: datetime
    last_seen: datetime
    source: str
    status: str
    paused_until: datetime | None


class ClientDeviceBlock(BaseModel):
    mac_address: str
    reason: str | None = None


# ------------------------------------------------------------ maintenance windows
class MaintenanceWindowCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    enabled: bool = True
    target_type: MaintenanceTarget = MaintenanceTarget.FLEET
    target_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    silence_alerts: bool = True
    silence_notifications: bool = True

    @model_validator(mode="after")
    def _validate(self) -> MaintenanceWindowCreate:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.target_type != MaintenanceTarget.FLEET and not self.target_ids:
            raise ValueError("target_ids is required for a device, site or group window")
        return self


class MaintenanceWindowUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    enabled: bool | None = None
    target_type: MaintenanceTarget | None = None
    target_ids: list[uuid.UUID] | None = Field(None, max_length=500)
    silence_alerts: bool | None = None
    silence_notifications: bool | None = None


class MaintenanceWindowOut(TimestampedModel):
    name: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    enabled: bool
    target_type: MaintenanceTarget
    target_ids: list[uuid.UUID]
    silence_alerts: bool
    silence_notifications: bool
    created_by: uuid.UUID | None
    active: bool = False


# ------------------------------------------------------------------------ reports
class ReportCreate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    kind: ReportKind = ReportKind.FLEET
    period_days: int = Field(7, ge=1, le=365)
    params: dict = Field(default_factory=dict)


class ReportOut(TimestampedModel):
    name: str
    kind: ReportKind
    status: ReportStatus
    period_start: datetime
    period_end: datetime
    params: dict
    size_bytes: int | None
    checksum_sha256: str | None
    error: str | None
    generated_at: datetime | None
    created_by: uuid.UUID | None
    download_url: str | None = None


# -------------------------------------------------------------------- bulk actions
class BulkDeviceAction(BaseModel):
    action: Literal[
        "maintenance_on",
        "maintenance_off",
        "command",
        "backup",
        "firmware_upgrade",
        "reboot",
    ]
    device_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    params: dict = Field(default_factory=dict)


class BulkDeviceResult(BaseModel):
    device_id: uuid.UUID
    name: str
    status: Literal["ok", "failed", "skipped"]
    message: str | None = None


class BulkDeviceResponse(BaseModel):
    action: str
    total: int
    succeeded: int
    failed: int
    results: list[BulkDeviceResult]


class CsvImportError(BaseModel):
    row: int
    error: str


class CsvImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[CsvImportError]
    devices: list[dict]


class ClientDevicePause(BaseModel):
    mac_address: str
    minutes: int = Field(ge=1, le=1440)
    reason: str | None = None


class VendorInfo(BaseModel):
    mac_prefix: str
    vendor_name: str
    vendor_address: str | None = None
