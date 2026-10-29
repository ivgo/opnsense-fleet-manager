"""Time-series device telemetry and metric catalogue."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import MetricType


class DeviceMetric(Base):
    """Append-only telemetry. Partition by month at scale (see docs/DATABASE.md)."""

    __tablename__ = "device_metrics"
    __table_args__ = (
        Index("ix_device_metrics_lookup", "device_id", "metric_type", "recorded_at"),
        Index("ix_device_metrics_tenant_time", "tenant_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    metric_type: Mapped[MetricType] = mapped_column(
        SAEnum(MetricType, native_enum=False, length=32), nullable=False
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(16))
    labels: Mapped[dict] = mapped_column(JSONB, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DeviceTelemetrySnapshot(Base):
    """Latest full status payload per device (cheap dashboard reads)."""

    __tablename__ = "device_telemetry_snapshots"
    __table_args__ = (UniqueConstraint("device_id", name="uq_device_telemetry_device"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    cpu_pct: Mapped[float | None] = mapped_column(Float)
    memory_pct: Mapped[float | None] = mapped_column(Float)
    disk_pct: Mapped[float | None] = mapped_column(Float)
    load_1m: Mapped[float | None] = mapped_column(Float)
    sessions: Mapped[int | None] = mapped_column()
    uptime_seconds: Mapped[int | None] = mapped_column()
    vpn_up: Mapped[int | None] = mapped_column()
    vpn_total: Mapped[int | None] = mapped_column()
    gateways_up: Mapped[int | None] = mapped_column()
    gateways_total: Mapped[int | None] = mapped_column()
    carp_status: Mapped[str | None] = mapped_column(String(32))
    interfaces: Mapped[list | None] = mapped_column(JSONB)
    traffic: Mapped[dict | None] = mapped_column(JSONB)
    traffic_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
