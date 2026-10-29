from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import (
    AliasType,
    DnsRecordType,
    NatType,
    RuleAction,
    RuleDirection,
    TemplateKind,
)
from app.schemas.common import TimestampedModel


# ------------------------------------------------------------------ templates
class TemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    kind: TemplateKind = TemplateKind.CONFIG
    parent_id: uuid.UUID | None = None
    body: dict = Field(default_factory=dict)
    variables: dict = Field(default_factory=dict)
    is_active: bool = True


class TemplateUpdate(BaseModel):
    description: str | None = None
    body: dict | None = None
    variables: dict | None = None
    parent_id: uuid.UUID | None = None
    is_active: bool | None = None


class TemplateOut(TimestampedModel):
    name: str
    description: str | None
    kind: TemplateKind
    parent_id: uuid.UUID | None
    body: dict
    version: int
    is_active: bool
    variables: dict


class TemplateRenderRequest(BaseModel):
    variables: dict = Field(default_factory=dict)


class TemplateRenderResponse(BaseModel):
    rendered: dict
    variables_used: list[str]
    warnings: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ firewall rules
class RuleCreate(BaseModel):
    device_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_ .:-]+$")
    description: str | None = None
    action: RuleAction
    direction: RuleDirection = RuleDirection.IN
    interface: str | None = "wan"
    protocol: str = Field("any", pattern=r"^(any|tcp|udp|icmp|icmp6|esp|ah|gre|tcp/udp)$")
    source: str = "any"
    destination: str = "any"
    destination_port: str | None = None
    source_port: str | None = None
    gateway: str | None = None
    log: bool = False
    enabled: bool = True
    order_index: int | None = None
    tags: list[str] = Field(default_factory=list)


class RuleUpdate(BaseModel):
    description: str | None = None
    action: RuleAction | None = None
    direction: RuleDirection | None = None
    interface: str | None = None
    protocol: str | None = None
    source: str | None = None
    destination: str | None = None
    destination_port: str | None = None
    source_port: str | None = None
    gateway: str | None = None
    log: bool | None = None
    enabled: bool | None = None
    order_index: int | None = None
    tags: list[str] | None = None


class RuleOut(TimestampedModel):
    device_id: uuid.UUID | None
    name: str
    description: str | None
    action: RuleAction
    direction: RuleDirection
    interface: str | None
    protocol: str
    source: str
    destination: str
    destination_port: str | None
    source_port: str | None
    gateway: str | None
    log: bool
    enabled: bool
    order_index: int
    tags: list[str]
    version: int


class RuleReorder(BaseModel):
    rule_ids: list[uuid.UUID]


# ------------------------------------------------------------------ aliases
class AliasCreate(BaseModel):
    device_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    description: str | None = None
    type: AliasType
    content: list[str] = Field(default_factory=list)
    enabled: bool = True


class AliasUpdate(BaseModel):
    description: str | None = None
    content: list[str] | None = None
    enabled: bool | None = None


class AliasOut(TimestampedModel):
    device_id: uuid.UUID | None
    name: str
    description: str | None
    type: AliasType
    content: list[str]
    enabled: bool


# ------------------------------------------------------------------ NAT
class NatCreate(BaseModel):
    device_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    type: NatType
    interface: str = "wan"
    protocol: str = "tcp"
    source: str = "any"
    destination: str = "any"
    destination_port: str | None = None
    target: str
    target_port: str | None = None
    enabled: bool = True
    order_index: int = 0


class NatUpdate(BaseModel):
    description: str | None = None
    interface: str | None = None
    protocol: str | None = None
    source: str | None = None
    destination: str | None = None
    destination_port: str | None = None
    target: str | None = None
    target_port: str | None = None
    enabled: bool | None = None
    order_index: int | None = None


class NatOut(TimestampedModel):
    device_id: uuid.UUID | None
    name: str
    description: str | None
    type: NatType
    interface: str
    protocol: str
    source: str
    destination: str
    destination_port: str | None
    target: str
    target_port: str | None
    enabled: bool
    order_index: int


# ------------------------------------------------------------------ interfaces / routes / vlans
class InterfaceCreate(BaseModel):
    device_id: uuid.UUID
    name: str = Field(min_length=1, max_length=32)
    description: str | None = None
    physical_if: str | None = None
    ip_address: str | None = None
    subnet_bits: int | None = Field(None, ge=0, le=32)
    gateway: str | None = None
    dhcp: bool = False
    enabled: bool = True


class InterfaceOut(TimestampedModel):
    device_id: uuid.UUID
    name: str
    description: str | None
    physical_if: str | None
    ip_address: str | None
    subnet_bits: int | None
    gateway: str | None
    dhcp: bool
    enabled: bool


class RouteCreate(BaseModel):
    device_id: uuid.UUID
    network: str
    gateway: str
    interface: str | None = None
    metric: int = 0
    description: str | None = None


class RouteOut(TimestampedModel):
    device_id: uuid.UUID
    network: str
    gateway: str
    interface: str | None
    metric: int
    description: str | None
    managed_by_sdwan: bool


class VlanCreate(BaseModel):
    device_id: uuid.UUID
    vlan_id: int = Field(ge=1, le=4094)
    parent_interface: str
    description: str | None = None
    enabled: bool = True


class VlanOut(TimestampedModel):
    device_id: uuid.UUID
    vlan_id: int
    parent_interface: str
    description: str | None
    enabled: bool


class DeployRequest(BaseModel):
    """Push the stored desired state of one device to the appliance."""

    device_id: uuid.UUID
    dry_run: bool = False
    apply: bool = True


# ------------------------------------------------------------------ DHCP
class DhcpScopeCreate(BaseModel):
    device_id: uuid.UUID
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_. -]+$")
    description: str | None = None
    subnet: str = Field(min_length=1, max_length=64)
    pool_start: str = Field(min_length=1, max_length=64)
    pool_end: str = Field(min_length=1, max_length=64)
    gateway: str | None = Field(None, max_length=64)
    dns_servers: list[str] = Field(default_factory=list)
    domain_name: str | None = Field(None, max_length=255)
    lease_time_seconds: int = Field(86400, ge=60, le=31_536_000)
    enabled: bool = True
    options: dict[str, str] = Field(default_factory=dict)


class DhcpScopeUpdate(BaseModel):
    description: str | None = None
    pool_start: str | None = None
    pool_end: str | None = None
    gateway: str | None = None
    dns_servers: list[str] | None = None
    domain_name: str | None = None
    lease_time_seconds: int | None = Field(None, ge=60, le=31_536_000)
    enabled: bool | None = None
    options: dict[str, str] | None = None


class DhcpScopeOut(TimestampedModel):
    device_id: uuid.UUID
    name: str
    description: str | None
    subnet: str
    pool_start: str
    pool_end: str
    gateway: str | None
    dns_servers: list[str]
    domain_name: str | None
    lease_time_seconds: int
    enabled: bool
    options: dict


class DhcpReservationCreate(BaseModel):
    scope_id: uuid.UUID
    hostname: str = Field(min_length=1, max_length=253)
    mac_address: str = Field(min_length=17, max_length=17)
    ip_address: str = Field(min_length=1, max_length=64)
    description: str | None = None
    enabled: bool = True


class DhcpReservationUpdate(BaseModel):
    hostname: str | None = Field(None, min_length=1, max_length=253)
    mac_address: str | None = Field(None, min_length=17, max_length=17)
    ip_address: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = None
    enabled: bool | None = None


class DhcpReservationOut(TimestampedModel):
    device_id: uuid.UUID
    scope_id: uuid.UUID
    hostname: str
    mac_address: str
    ip_address: str
    description: str | None
    enabled: bool


# ------------------------------------------------------------------ DNS
class DnsRecordCreate(BaseModel):
    device_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    record_type: DnsRecordType
    value: str = Field(min_length=1, max_length=4096)
    ttl: int = Field(300, ge=0, le=604_800)
    priority: int | None = Field(None, ge=0, le=65_535)
    weight: int | None = Field(None, ge=0, le=65_535)
    port: int | None = Field(None, ge=1, le=65_535)
    description: str | None = None
    enabled: bool = True


class DnsRecordUpdate(BaseModel):
    value: str | None = Field(None, min_length=1, max_length=4096)
    ttl: int | None = Field(None, ge=0, le=604_800)
    priority: int | None = Field(None, ge=0, le=65_535)
    weight: int | None = Field(None, ge=0, le=65_535)
    port: int | None = Field(None, ge=1, le=65_535)
    description: str | None = None
    enabled: bool | None = None


class DnsRecordOut(TimestampedModel):
    device_id: uuid.UUID
    name: str
    record_type: DnsRecordType
    value: str
    ttl: int
    priority: int | None
    weight: int | None
    port: int | None
    description: str | None
    enabled: bool


# ------------------------------------------------------------------ diff / apply
class ConfigChange(BaseModel):
    resource: str
    operation: str
    payload: dict


class ConfigDiff(BaseModel):
    device_id: uuid.UUID
    generated_at: datetime
    additions: list[ConfigChange] = Field(default_factory=list)
    removals: list[ConfigChange] = Field(default_factory=list)
    modifications: list[ConfigChange] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class ApplyRequest(BaseModel):
    """Push stored desired state for one or more devices.

    ``resources`` selects which deployers run. When omitted only firewall rules
    are applied, which keeps the historical behaviour of this endpoint.
    """

    device_ids: list[uuid.UUID]
    dry_run: bool = False
    reload: bool = True
    resources: list[str] | None = None


class ApplyResult(BaseModel):
    device_id: uuid.UUID
    success: bool
    applied: int = 0
    message: str | None = None
    errors: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)
