"""Topology aggregate: Site, DeviceGroup, Device, DeviceCertificate."""

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
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    CertificateStatus,
    ConnectionStatus,
    DeviceStatus,
    HARole,
)


class Site(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_sites_tenant_code"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(String(512))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(2))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    contact_info: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(JSONB), default=dict)

    devices: Mapped[list[Device]] = relationship(back_populates="site", lazy="noload")


class DeviceGroup(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "device_groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_device_groups_tenant_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("device_groups.id", ondelete="SET NULL")
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("templates.id", ondelete="SET NULL")
    )
    labels: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)

    parent: Mapped[DeviceGroup | None] = relationship(remote_side="DeviceGroup.id", lazy="noload")
    devices: Mapped[list[Device]] = relationship(back_populates="group", lazy="noload")


class Device(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_devices_tenant_name"),
        Index("ix_devices_tenant_status", "tenant_id", "status", "connection_status"),
        Index("ix_devices_tenant_site", "tenant_id", "site_id"),
        Index("ix_devices_serial", "serial_number"),
    )

    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("device_groups.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    serial_number: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(100))
    firmware_version: Mapped[str | None] = mapped_column(String(64))
    agent_version: Mapped[str | None] = mapped_column(String(32))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    api_port: Mapped[int] = mapped_column(Integer, default=443, nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(String(512))
    api_secret_encrypted: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[DeviceStatus] = mapped_column(
        SAEnum(DeviceStatus, native_enum=False, length=32), default=DeviceStatus.UNREGISTERED, nullable=False
    )
    connection_status: Mapped[ConnectionStatus] = mapped_column(
        SAEnum(ConnectionStatus, native_enum=False, length=32),
        default=ConnectionStatus.UNKNOWN,
        nullable=False,
    )
    is_ha: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ha_role: Mapped[HARole | None] = mapped_column(SAEnum(HARole, native_enum=False, length=16))
    ha_group_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    tags: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(JSONB), default=dict)
    certificate_serial: Mapped[str | None] = mapped_column(String(128))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uptime_seconds: Mapped[int | None] = mapped_column(Integer)
    config_version: Mapped[str | None] = mapped_column(String(64))
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    site: Mapped[Site | None] = relationship(back_populates="devices", lazy="joined")
    group: Mapped[DeviceGroup | None] = relationship(back_populates="devices", lazy="noload")
    certificates: Mapped[list[DeviceCertificate]] = relationship(
        back_populates="device", cascade="all, delete-orphan", lazy="noload"
    )


class DeviceCertificate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "device_certificates"
    __table_args__ = (
        UniqueConstraint("serial_number", name="uq_device_certificates_serial_number"),
        Index("ix_device_certs_device_status", "device_id", "status"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    serial_number: Mapped[str] = mapped_column(String(128), nullable=False)
    certificate_pem: Mapped[str] = mapped_column(Text, nullable=False)
    private_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    subject_cn: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer_cn: Mapped[str | None] = mapped_column(String(255))
    fingerprint_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[CertificateStatus] = mapped_column(
        SAEnum(CertificateStatus, native_enum=False, length=16),
        default=CertificateStatus.ACTIVE,
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(255))

    device: Mapped[Device] = relationship(back_populates="certificates", lazy="noload")
