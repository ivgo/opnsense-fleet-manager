"""Compliance aggregatets: framework reports and findings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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
from app.models.enums import ComplianceFramework


class ComplianceReport(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "compliance_reports"
    __table_args__ = (Index("ix_compliance_reports_tenant_fw", "tenant_id", "framework", "generated_at"),)

    framework: Mapped[ComplianceFramework] = mapped_column(
        SAEnum(ComplianceFramework, native_enum=False, length=32), nullable=False
    )
    scope: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    controls_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    controls_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    controls_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    findings: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    controls: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    artifact_key: Mapped[str | None] = mapped_column(String(512))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
