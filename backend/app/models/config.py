"""Desired-configuration aggregates: rules, aliases, NAT, interfaces, routes, VLANs, DHCP, DNS, templates."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    AliasType,
    DnsRecordType,
    NatType,
    RuleAction,
    RuleDirection,
    TemplateKind,
    VpnProtocol,
)


class Template(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_templates_tenant_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[TemplateKind] = mapped_column(
        SAEnum(TemplateKind, native_enum=False, length=16), default=TemplateKind.CONFIG, nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("templates.id", ondelete="SET NULL")
    )
    body: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    variables: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)

    parent: Mapped[Template | None] = relationship(remote_side="Template.id", lazy="noload")


class FirewallRule(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "firewall_rules"
    __table_args__ = (
        Index("ix_firewall_rules_tenant_device", "tenant_id", "device_id", "order_index"),
        UniqueConstraint("device_id", "name", name="uq_firewall_rules_device_name"),
    )

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("device_groups.id"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    action: Mapped[RuleAction] = mapped_column(
        SAEnum(RuleAction, native_enum=False, length=16), nullable=False
    )
    direction: Mapped[RuleDirection] = mapped_column(
        SAEnum(RuleDirection, native_enum=False, length=16), default=RuleDirection.IN, nullable=False
    )
    interface: Mapped[str | None] = mapped_column(String(64))
    protocol: Mapped[str] = mapped_column(String(16), default="any", nullable=False)
    source: Mapped[str] = mapped_column(String(512), default="any", nullable=False)
    destination: Mapped[str] = mapped_column(String(512), default="any", nullable=False)
    destination_port: Mapped[str | None] = mapped_column(String(128))
    source_port: Mapped[str | None] = mapped_column(String(128))
    gateway: Mapped[str | None] = mapped_column(String(64))
    log: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tags: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    source_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("policies.id")
    )


class Alias(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "aliases"
    __table_args__ = (
        UniqueConstraint("device_id", "name", name="uq_aliases_device_name"),
        Index("ix_aliases_tenant_type", "tenant_id", "type"),
    )

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[AliasType] = mapped_column(SAEnum(AliasType, native_enum=False, length=16), nullable=False)
    content: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class NatRule(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "nat_rules"
    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_nat_rules_device_name"),)

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[NatType] = mapped_column(SAEnum(NatType, native_enum=False, length=32), nullable=False)
    interface: Mapped[str] = mapped_column(String(64), default="wan", nullable=False)
    protocol: Mapped[str] = mapped_column(String(16), default="tcp", nullable=False)
    source: Mapped[str] = mapped_column(String(512), default="any", nullable=False)
    destination: Mapped[str] = mapped_column(String(512), default="any", nullable=False)
    destination_port: Mapped[str | None] = mapped_column(String(128))
    target: Mapped[str] = mapped_column(String(512), nullable=False)
    target_port: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class InterfaceConfig(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "interface_configs"
    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_interface_configs_device_name"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    physical_if: Mapped[str | None] = mapped_column(String(32))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    subnet_bits: Mapped[int | None] = mapped_column(Integer)
    gateway: Mapped[str | None] = mapped_column(String(64))
    dhcp: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RouteConfig(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "route_configs"

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    network: Mapped[str] = mapped_column(String(64), nullable=False)
    gateway: Mapped[str] = mapped_column(String(64), nullable=False)
    interface: Mapped[str | None] = mapped_column(String(32))
    metric: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    managed_by_sdwan: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class VlanConfig(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "vlan_configs"
    __table_args__ = (UniqueConstraint("device_id", "vlan_id", name="uq_vlan_configs_device_vlan"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    vlan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_interface: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DhcpScope(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A DHCP pool (Kea/ISC) owned by one managed firewall interface."""

    __tablename__ = "dhcp_scopes"
    __table_args__ = (
        Index(
            "uq_dhcp_scopes_device_name",
            "device_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_dhcp_scopes_device_subnet",
            "device_id",
            "subnet",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_dhcp_scopes_tenant_subnet", "tenant_id", "subnet"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    subnet: Mapped[str] = mapped_column(String(64), nullable=False)
    pool_start: Mapped[str] = mapped_column(String(64), nullable=False)
    pool_end: Mapped[str] = mapped_column(String(64), nullable=False)
    gateway: Mapped[str | None] = mapped_column(String(64))
    dns_servers: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    domain_name: Mapped[str | None] = mapped_column(String(255))
    lease_time_seconds: Mapped[int] = mapped_column(Integer, default=86400, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    options: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class DhcpReservation(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Static MAC-to-IP binding inside a :class:`DhcpScope`."""

    __tablename__ = "dhcp_reservations"
    __table_args__ = (
        Index(
            "uq_dhcp_reservations_scope_mac",
            "scope_id",
            "mac_address",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_dhcp_reservations_scope_ip",
            "scope_id",
            "ip_address",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_dhcp_reservations_tenant_scope", "tenant_id", "scope_id"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("dhcp_scopes.id", ondelete="CASCADE"), index=True
    )
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    mac_address: Mapped[str] = mapped_column(String(17), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class DnsRecord(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Authoritative record managed on a device's Unbound resolver."""

    __tablename__ = "dns_records"
    __table_args__ = (
        Index(
            "uq_dns_records_device_name_type_value",
            "device_id",
            "name",
            "record_type",
            "value",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_dns_records_tenant_type", "tenant_id", "record_type"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    record_type: Mapped[DnsRecordType] = mapped_column(
        SAEnum(DnsRecordType, native_enum=False, length=8), nullable=False
    )
    value: Mapped[str] = mapped_column(Text, nullable=False)
    ttl: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    priority: Mapped[int | None] = mapped_column(Integer)
    weight: Mapped[int | None] = mapped_column(Integer)
    port: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class IpsecPhase1(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    """IPsec Phase 1 (IKE) configuration for a device."""

    __tablename__ = "ipsec_phase1"
    __table_args__ = (
        UniqueConstraint("device_id", "name", name="uq_ipsec_phase1_device_name"),
        Index("ix_ipsec_phase1_tenant_device", "tenant_id", "device_id"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    iketype: Mapped[str] = mapped_column(String(16), default="ikev2", nullable=False)  # ikev1, ikev2
    interface: Mapped[str] = mapped_column(String(32), default="wan", nullable=False)
    remote_gateway: Mapped[str] = mapped_column(String(255), nullable=False)
    local_gateway: Mapped[str | None] = mapped_column(String(255))
    authentication_method: Mapped[str] = mapped_column(
        String(32), default="pre_shared_key", nullable=False
    )  # pre_shared_key, rsa, ecdsa, x509
    pre_shared_key: Mapped[str | None] = mapped_column(Text)
    my_identifier: Mapped[str | None] = mapped_column(String(255))
    peer_identifier: Mapped[str | None] = mapped_column(String(255))
    encryption: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)  # e.g., ["aes256gcm16"]
    hash: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)  # e.g., ["sha256"]
    dh_group: Mapped[str] = mapped_column(String(16), default="14", nullable=False)  # 14, 15, 16, 17, 18, 19, 20, 21
    lifetime: Mapped[int] = mapped_column(Integer, default=28800, nullable=False)  # seconds
    dpd_delay: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    dpd_maxfail: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    nat_traversal: Mapped[str] = mapped_column(String(8), default="force", nullable=False)  # force, disable, auto
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class IpsecPhase2(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    """IPsec Phase 2 (ESP/AH) configuration for a device."""

    __tablename__ = "ipsec_phase2"
    __table_args__ = (
        UniqueConstraint("device_id", "phase1_id", "name", name="uq_ipsec_phase2_device_phase1_name"),
        Index("ix_ipsec_phase2_tenant_device", "tenant_id", "device_id"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    phase1_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ipsec_phase1.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="tunnel", nullable=False)  # tunnel, transport
    protocol: Mapped[str] = mapped_column(String(8), default="esp", nullable=False)  # esp, ah, esp-ah
    local_net: Mapped[str] = mapped_column(String(255), nullable=False)
    remote_net: Mapped[str] = mapped_column(String(255), nullable=False)
    encryption: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)  # e.g., ["aes256gcm16"]
    hash: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)  # e.g., ["sha256"]
    pfs_group: Mapped[str] = mapped_column(String(16), default="14", nullable=False)  # off, 14, 15, 16, 17, 18, 19, 20, 21
    lifetime: Mapped[int] = mapped_column(Integer, default=3600, nullable=False)  # seconds
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
