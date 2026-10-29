"""Zero-touch provisioning: enrollment tokens, assignments, PKI-linked state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import DiscoveryMethod, ZtpStatus


class ZtpEnrollment(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "ztp_enrollments"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_ztp_enrollments_token_hash"),
        Index("ix_ztp_enrollments_tenant_status", "tenant_id", "status"),
    )

    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL")
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hint: Mapped[str] = mapped_column(String(16), nullable=False)
    device_serial: Mapped[str | None] = mapped_column(String(128), index=True)
    device_mac: Mapped[str | None] = mapped_column(String(17))
    hostname: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[ZtpStatus] = mapped_column(
        SAEnum(ZtpStatus, native_enum=False, length=32), default=ZtpStatus.PENDING, nullable=False
    )
    discovery_method: Mapped[DiscoveryMethod] = mapped_column(
        SAEnum(DiscoveryMethod, native_enum=False, length=16), default=DiscoveryMethod.TOKEN, nullable=False
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("templates.id", ondelete="SET NULL")
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("device_groups.id", ondelete="SET NULL")
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    certificate_serial: Mapped[str | None] = mapped_column(String(128))
    hardware_profile: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(JSONB), default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
