"""High-availability aggregates: CARP clusters and their member nodes."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import HaNodeRole


class HaCluster(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A CARP virtual IP shared by two or more firewalls."""

    __tablename__ = "ha_clusters"
    __table_args__ = (
        # Partial index: a soft-deleted cluster must not block reusing its name.
        Index(
            "uq_ha_clusters_tenant_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_ha_clusters_tenant_site", "tenant_id", "site_id"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    virtual_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    interface: Mapped[str] = mapped_column(String(32), default="lan", nullable=False)
    vhid: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    advbase: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sync_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))

    nodes: Mapped[list[HaNode]] = relationship(
        back_populates="cluster", lazy="selectin", cascade="all, delete-orphan"
    )


class HaNode(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """One firewall in a CARP cluster, with its advertised skew."""

    __tablename__ = "ha_nodes"
    __table_args__ = (
        UniqueConstraint("cluster_id", "device_id", name="uq_ha_nodes_cluster_device"),
        Index("ix_ha_nodes_tenant_cluster", "tenant_id", "cluster_id"),
    )

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ha_clusters.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[HaNodeRole] = mapped_column(
        SAEnum(HaNodeRole, native_enum=False, length=16), default=HaNodeRole.SECONDARY, nullable=False
    )
    advskew: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    vip_uuid: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)

    cluster: Mapped[HaCluster] = relationship(back_populates="nodes", lazy="noload")
