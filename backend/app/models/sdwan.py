"""SD-WAN aggregates: topology, tunnel, link telemetry, traffic policy, route table."""

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
    HealthStatus,
    SteeringStrategy,
    TopologyType,
    TunnelStatus,
    VpnProtocol,
)


class SdwanTopology(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "sdwan_topologies"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_sdwan_topologies_tenant_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    topology_type: Mapped[TopologyType] = mapped_column(
        SAEnum(TopologyType, native_enum=False, length=32), default=TopologyType.HUB_SPOKE, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    configuration: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    routing_config: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    hub_device_ids: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    spoke_device_ids: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))

    tunnels: Mapped[list[VpnTunnel]] = relationship(back_populates="topology", lazy="noload")


class VpnTunnel(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "vpn_tunnels"
    __table_args__ = (
        UniqueConstraint("topology_id", "name", name="uq_vpn_tunnels_topology_name"),
        Index("ix_vpn_tunnels_tenant_status", "tenant_id", "status"),
    )

    topology_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sdwan_topologies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    protocol: Mapped[VpnProtocol] = mapped_column(
        SAEnum(VpnProtocol, native_enum=False, length=16), default=VpnProtocol.WIREGUARD, nullable=False
    )
    local_device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    remote_device_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL")
    )
    interface_name: Mapped[str | None] = mapped_column(String(32))
    #: Public key of the local WireGuard instance.
    public_key: Mapped[str | None] = mapped_column(String(128))
    #: Encrypted private key of the local WireGuard instance (legacy column name).
    preshared_key_encrypted: Mapped[str | None] = mapped_column(Text)
    #: Public key of the remote WireGuard instance - a different keypair.
    peer_public_key: Mapped[str | None] = mapped_column(String(128))
    tunnel_address_local: Mapped[str | None] = mapped_column(String(64))
    tunnel_address_remote: Mapped[str | None] = mapped_column(String(64))
    endpoint_local: Mapped[str | None] = mapped_column(String(255))
    endpoint_remote: Mapped[str | None] = mapped_column(String(255))
    allowed_ips: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    keepalive: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    mtu: Mapped[int] = mapped_column(Integer, default=1420, nullable=False)
    status: Mapped[TunnelStatus] = mapped_column(
        SAEnum(TunnelStatus, native_enum=False, length=32), default=TunnelStatus.PENDING, nullable=False
    )
    health_status: Mapped[HealthStatus] = mapped_column(
        SAEnum(HealthStatus, native_enum=False, length=16), default=HealthStatus.UNKNOWN, nullable=False
    )
    last_handshake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    config: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)

    topology: Mapped[SdwanTopology] = relationship(back_populates="tunnels", lazy="noload")
    links: Mapped[list[SdwanLink]] = relationship(back_populates="tunnel", lazy="noload")


class SdwanLink(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "sdwan_links"
    __table_args__ = (Index("ix_sdwan_links_tenant_topology", "tenant_id", "topology_id"),)

    topology_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sdwan_topologies.id", ondelete="CASCADE"), index=True
    )
    tunnel_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vpn_tunnels.id", ondelete="CASCADE"), index=True
    )
    local_device_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("devices.id"))
    remote_device_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("devices.id"))
    wan_interface: Mapped[str] = mapped_column(String(32), default="wan", nullable=False)
    cost: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    status: Mapped[TunnelStatus] = mapped_column(
        SAEnum(TunnelStatus, native_enum=False, length=32), default=TunnelStatus.PENDING, nullable=False
    )
    latency_ms: Mapped[float | None] = mapped_column(Float)
    jitter_ms: Mapped[float | None] = mapped_column(Float)
    loss_pct: Mapped[float | None] = mapped_column(Float)
    bandwidth_mbps: Mapped[float | None] = mapped_column(Float)
    sla_latency_ms: Mapped[float] = mapped_column(Float, default=150.0, nullable=False)
    sla_loss_pct: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column("metadata", MutableDict.as_mutable(JSONB), default=dict)

    tunnel: Mapped[VpnTunnel | None] = relationship(back_populates="links", lazy="noload")


class TrafficPolicy(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "traffic_policies"

    topology_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sdwan_topologies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    strategy: Mapped[SteeringStrategy] = mapped_column(
        SAEnum(SteeringStrategy, native_enum=False, length=32),
        default=SteeringStrategy.LOWEST_LATENCY,
        nullable=False,
    )
    match: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    preferred_link_ids: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SdwanRoute(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "sdwan_routes"
    __table_args__ = (Index("ix_sdwan_routes_tenant_topology", "tenant_id", "topology_id"),)

    topology_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sdwan_topologies.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    destination: Mapped[str] = mapped_column(String(64), nullable=False)
    next_hop: Mapped[str | None] = mapped_column(String(64))
    tunnel_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("vpn_tunnels.id"))
    metric: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), default="static", nullable=False)
    installed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at_dynamic: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WireGuardKey(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Per-device WireGuard identity used to build real peer pairs.

    Every managed device owns exactly one keypair and one point-to-point
    address inside the topology's tunnel network. Edges reference the peer's
    public key, so both ends of a tunnel use distinct keys.
    """

    __tablename__ = "wireguard_keys"
    __table_args__ = (UniqueConstraint("topology_id", "device_id", name="uq_wireguard_keys_topology_device"),)

    topology_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sdwan_topologies.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    public_key: Mapped[str] = mapped_column(String(128), nullable=False)
    private_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    listen_port: Mapped[int] = mapped_column(Integer, default=51820, nullable=False)
    tunnel_address: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class OpenVpnCa(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Certificate authority generated for an OpenVPN topology."""

    __tablename__ = "openvpn_cas"
    __table_args__ = (UniqueConstraint("topology_id", name="uq_openvpn_cas_topology"),)

    topology_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sdwan_topologies.id", ondelete="CASCADE"), index=True
    )
    common_name: Mapped[str] = mapped_column(String(128), nullable=False)
    cert_pem: Mapped[str] = mapped_column(Text, nullable=False)
    key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    ca_ref: Mapped[str | None] = mapped_column(String(64))


class OpenVpnCertificate(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    """Client certificate issued to one device by the topology CA."""

    __tablename__ = "openvpn_certificates"
    __table_args__ = (
        UniqueConstraint("topology_id", "device_id", name="uq_openvpn_certificates_topology_device"),
    )

    topology_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sdwan_topologies.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    common_name: Mapped[str] = mapped_column(String(128), nullable=False)
    cert_pem: Mapped[str] = mapped_column(Text, nullable=False)
    key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    ca_ref: Mapped[str | None] = mapped_column(String(64))
    cert_ref: Mapped[str | None] = mapped_column(String(64))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
