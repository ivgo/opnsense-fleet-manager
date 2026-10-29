from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import HealthStatus, SteeringStrategy, TopologyType, TunnelStatus, VpnProtocol
from app.schemas.common import TimestampedModel


class TopologyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    topology_type: TopologyType = TopologyType.HUB_SPOKE
    hub_device_ids: list[uuid.UUID] = Field(default_factory=list)
    spoke_device_ids: list[uuid.UUID] = Field(default_factory=list)
    configuration: dict = Field(default_factory=dict)
    routing_config: dict = Field(default_factory=dict)


class TopologyUpdate(BaseModel):
    description: str | None = None
    status: str | None = None
    hub_device_ids: list[uuid.UUID] | None = None
    spoke_device_ids: list[uuid.UUID] | None = None
    configuration: dict | None = None
    routing_config: dict | None = None


class TopologyOut(TimestampedModel):
    name: str
    description: str | None
    topology_type: TopologyType
    status: str
    hub_device_ids: list[uuid.UUID]
    spoke_device_ids: list[uuid.UUID]
    configuration: dict
    routing_config: dict


class TunnelCreate(BaseModel):
    topology_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    protocol: VpnProtocol = VpnProtocol.WIREGUARD
    local_device_id: uuid.UUID
    remote_device_id: uuid.UUID | None = None
    interface_name: str | None = None
    endpoint_local: str | None = None
    endpoint_remote: str | None = None
    allowed_ips: list[str] = Field(default_factory=list)
    keepalive: int = Field(25, ge=0, le=65535)
    mtu: int = Field(1420, ge=1280, le=9000)
    wan_interface: str = "wan"
    priority: int = 100
    cost: int = 10


class TunnelOut(TimestampedModel):
    topology_id: uuid.UUID
    name: str
    protocol: VpnProtocol
    local_device_id: uuid.UUID
    remote_device_id: uuid.UUID | None
    interface_name: str | None
    public_key: str | None
    peer_public_key: str | None
    tunnel_address_local: str | None
    tunnel_address_remote: str | None
    endpoint_local: str | None
    endpoint_remote: str | None
    allowed_ips: list[str]
    keepalive: int
    mtu: int
    status: TunnelStatus
    health_status: HealthStatus
    last_handshake_at: datetime | None
    metrics: dict


class TopologyDeployRequest(BaseModel):
    regenerate_keys: bool = False
    dry_run: bool = False


class TopologyDeployResult(BaseModel):
    topology_id: uuid.UUID
    tunnels_created: int
    tunnels_updated: int
    tunnels_removed: int = 0
    routes_installed: int
    devices_configured: int
    errors: list[str] = Field(default_factory=list)


class LinkOut(TimestampedModel):
    topology_id: uuid.UUID
    tunnel_id: uuid.UUID | None
    local_device_id: uuid.UUID
    remote_device_id: uuid.UUID | None
    wan_interface: str
    status: TunnelStatus
    latency_ms: float | None
    jitter_ms: float | None
    loss_pct: float | None
    bandwidth_mbps: float | None
    cost: int
    priority: int
    sla_latency_ms: float
    sla_loss_pct: float
    measured_at: datetime | None


class LinkMeasurement(BaseModel):
    latency_ms: float | None = Field(None, ge=0)
    jitter_ms: float | None = Field(None, ge=0)
    loss_pct: float | None = Field(None, ge=0, le=100)
    bandwidth_mbps: float | None = Field(None, ge=0)
    status: TunnelStatus | None = None


class TrafficPolicyCreate(BaseModel):
    topology_id: uuid.UUID
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    strategy: SteeringStrategy = SteeringStrategy.LOWEST_LATENCY
    match: dict = Field(default_factory=dict)
    preferred_link_ids: list[uuid.UUID] = Field(default_factory=list)
    priority: int = 100
    enabled: bool = True


class TrafficPolicyOut(TimestampedModel):
    topology_id: uuid.UUID
    name: str
    description: str | None
    strategy: SteeringStrategy
    match: dict
    preferred_link_ids: list[uuid.UUID]
    priority: int
    enabled: bool


class RouteOut(TimestampedModel):
    topology_id: uuid.UUID
    device_id: uuid.UUID
    destination: str
    next_hop: str | None
    tunnel_id: uuid.UUID | None
    metric: int
    protocol: str
    installed: bool


class TopologyNode(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    status: str
    site: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class TopologyEdge(BaseModel):
    id: uuid.UUID
    source: uuid.UUID
    target: uuid.UUID | None
    status: str
    health: str
    latency_ms: float | None = None
    loss_pct: float | None = None
    label: str | None = None


class TopologyGraph(BaseModel):
    topology_id: uuid.UUID
    name: str
    type: TopologyType
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
    generated_at: datetime


class FailoverEvent(BaseModel):
    link_id: uuid.UUID
    topology_id: uuid.UUID
    previous_link_id: uuid.UUID | None
    reason: str
    occurred_at: datetime


class WireGuardKeyOut(TimestampedModel):
    """Public half of a device WireGuard identity. Private keys never leave the API."""

    topology_id: uuid.UUID
    device_id: uuid.UUID
    public_key: str
    listen_port: int
    tunnel_address: str


class VpnEndpointStatus(BaseModel):
    device_id: uuid.UUID | None = None
    device: str | None = None
    state: str
    last_handshake_at: datetime | None = None
    details: dict = Field(default_factory=dict)


class VpnTunnelStatus(BaseModel):
    tunnel_id: uuid.UUID
    name: str
    protocol: VpnProtocol
    status: TunnelStatus
    endpoints: list[VpnEndpointStatus] = Field(default_factory=list)


class VpnStatusOut(BaseModel):
    topology_id: uuid.UUID
    generated_at: datetime
    tunnels: list[VpnTunnelStatus] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
