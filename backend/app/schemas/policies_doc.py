from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FirewallPolicyRule(BaseModel):
    name: str
    action: str = Field(pattern=r"^(pass|block|reject)$")
    direction: str = Field("in", pattern=r"^(in|out)$")
    interface: str | None = "wan"
    protocol: str = "any"
    source: str = "any"
    destination: str = "any"
    destination_port: str | int | None = None
    source_port: str | int | None = None
    log: bool = False
    description: str | None = None
    tags: list[str] = Field(default_factory=list)


class FirewallPolicySpec(BaseModel):
    rules: list[FirewallPolicyRule] = Field(default_factory=list)
    default_action: str = Field("block", pattern=r"^(pass|block|reject)$")


class NatPolicyEntry(BaseModel):
    name: str
    type: str = Field(pattern=r"^(port_forward|outbound|one_to_one)$")
    interface: str = "wan"
    protocol: str = "tcp"
    source: str = "any"
    destination: str = "any"
    destination_port: str | int | None = None
    target: str
    target_port: str | int | None = None


class VlanPolicyEntry(BaseModel):
    vlan_id: int = Field(ge=1, le=4094)
    parent_interface: str
    description: str | None = None


class VpnPeerSpec(BaseModel):
    name: str
    public_key: str | None = None
    allowed_ips: list[str] = Field(default_factory=list)
    endpoint: str | None = None
    keepalive: int = 25


class VpnPolicySpec(BaseModel):
    protocol: str = Field("wireguard", pattern=r"^(wireguard|ipsec|openvpn)$")
    interface: str = "wg0"
    listen_port: int = 51820
    address: str | None = None
    peers: list[VpnPeerSpec] = Field(default_factory=list)


class PolicyMetadata(BaseModel):
    name: str
    environment: str = "development"
    description: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class PolicyDocument(BaseModel):
    apiVersion: str = "fleet.opnsense.io/v1"
    kind: str
    metadata: PolicyMetadata
    spec: dict[str, Any]


class TemplateContext(BaseModel):
    site: dict[str, Any] = Field(default_factory=dict)
    device: dict[str, Any] = Field(default_factory=dict)
    tenant: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)
