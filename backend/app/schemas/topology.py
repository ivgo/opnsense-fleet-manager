from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import CertificateStatus, ConnectionStatus, DeviceStatus, HARole
from app.schemas.common import ORMModel, TimestampedModel


# ------------------------------------------------------------------ sites
class SiteCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_-]+$")
    description: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = Field(None, min_length=2, max_length=2)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    timezone: str = "UTC"
    contact_info: dict = Field(default_factory=dict)


class SiteUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    contact_info: dict | None = None


class SiteOut(TimestampedModel):
    name: str
    code: str
    description: str | None
    city: str | None
    country: str | None
    latitude: float | None
    longitude: float | None
    timezone: str
    device_count: int | None = None


# ------------------------------------------------------------------ groups
class DeviceGroupCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    parent_id: UUID | None = None
    template_id: UUID | None = None
    labels: list[str] = Field(default_factory=list)


class DeviceGroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    parent_id: UUID | None = None
    template_id: UUID | None = None
    labels: list[str] | None = None


class DeviceGroupOut(TimestampedModel):
    name: str
    description: str | None
    parent_id: UUID | None
    template_id: UUID | None
    labels: list[str]
    device_count: int | None = None


# ------------------------------------------------------------------ devices
class DeviceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255, pattern=r"^[a-zA-Z0-9._-]+$")
    site_id: UUID | None = None
    group_id: UUID | None = None
    hostname: str | None = None
    description: str | None = None
    ip_address: str | None = None
    api_port: int = Field(443, ge=1, le=65535)
    serial_number: str | None = None
    model: str | None = None
    is_ha: bool = False
    ha_role: HARole | None = None
    tags: list[str] = Field(default_factory=list)
    api_key: str | None = Field(None, description="OPNsense API key (encrypted at rest)")
    api_secret: str | None = Field(None, description="OPNsense API secret (encrypted at rest)")


class DeviceUpdate(BaseModel):
    name: str | None = None
    site_id: UUID | None = None
    group_id: UUID | None = None
    hostname: str | None = None
    description: str | None = None
    ip_address: str | None = None
    api_port: int | None = Field(None, ge=1, le=65535)
    status: DeviceStatus | None = None
    is_ha: bool | None = None
    ha_role: HARole | None = None
    tags: list[str] | None = None
    api_key: str | None = None
    api_secret: str | None = None


class DeviceOut(TimestampedModel):
    tenant_id: UUID
    site_id: UUID | None
    group_id: UUID | None
    name: str
    hostname: str | None
    description: str | None
    serial_number: str | None
    model: str | None
    firmware_version: str | None
    agent_version: str | None
    ip_address: str | None
    api_port: int
    status: DeviceStatus
    connection_status: ConnectionStatus
    is_ha: bool
    ha_role: HARole | None
    tags: list[str]
    certificate_serial: str | None
    last_seen_at: datetime | None
    last_heartbeat_at: datetime | None
    uptime_seconds: int | None
    enrolled_at: datetime | None
    provisioned_at: datetime | None


class DeviceSummary(BaseModel):
    total: int
    online: int
    offline: int
    error: int
    maintenance: int
    unregistered: int


class CommandResultPayload(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=64)
    status: str = Field(default="error", max_length=32)
    message: str | None = Field(None, max_length=2048)
    output: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = Field(None, ge=0)


class InterfaceCounters(BaseModel):
    """Cumulative byte counters for one interface, as reported by the device."""

    name: str | None = None
    inbytes: int = Field(ge=0)
    outbytes: int = Field(ge=0)


class TrafficSample(BaseModel):
    """Cumulative interface counters.

    The platform derives rates from two consecutive samples, so devices only
    report monotonic counters. ``time`` is the device clock (informational); the
    server uses its own receipt time for the elapsed interval.
    """

    time: float | None = None
    interfaces: dict[str, InterfaceCounters] = Field(default_factory=dict, max_length=256)


class HeartbeatPayload(BaseModel):
    serial_number: str | None = None
    hostname: str | None = None
    firmware_version: str | None = None
    agent_version: str | None = None
    uptime_seconds: int | None = None
    cpu_pct: float | None = Field(None, ge=0, le=100)
    memory_pct: float | None = Field(None, ge=0, le=100)
    disk_pct: float | None = Field(None, ge=0, le=100)
    load_1m: float | None = None
    sessions: int | None = None
    vpn_up: int | None = None
    vpn_total: int | None = None
    gateways_up: int | None = None
    gateways_total: int | None = None
    carp_status: str | None = None
    interfaces: list[dict] = Field(default_factory=list)
    traffic: TrafficSample | None = None
    arp: list[dict] | None = None
    dhcp_leases: list[dict] | None = None
    lldp: list[dict] | None = None
    command_results: list[CommandResultPayload] = Field(default_factory=list, max_length=50)

    @field_validator("carp_status")
    @classmethod
    def _carp(cls, value: str | None) -> str | None:
        if value and value.lower() not in {"master", "backup", "disabled", "unknown"}:
            return "unknown"
        return value.lower() if value else None


class HeartbeatResponse(BaseModel):
    accepted: bool
    device_id: UUID
    server_time: datetime
    commands: list[dict] = Field(default_factory=list)
    command_results_accepted: int = 0


DeviceCommandAction = Literal[
    "noop",
    "ping",
    "sync_config",
    "renew_certificate",
    "restart_agent",
    "collect_diagnostics",
    "reload_firewall",
    "update_telemetry",
    "firmware_upgrade",
    "firmware_reboot",
]


class DeviceCommandRequest(BaseModel):
    action: DeviceCommandAction
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _payload_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, default=str, separators=(",", ":"))
        if len(encoded) > 8192:
            raise ValueError("Command payload must not exceed 8 KiB")
        return value


class DeviceCommandOut(BaseModel):
    id: str
    action: str
    payload: dict[str, Any]
    requested_at: datetime
    requested_by: UUID | None = None
    pending_count: int


class DeviceCommandStatus(BaseModel):
    device_id: UUID
    pending: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    pending_count: int = 0
    last_result_at: datetime | None = None


class DeviceSearchResult(BaseModel):
    id: UUID
    name: str
    hostname: str | None
    ip_address: str | None
    status: DeviceStatus


# ------------------------------------------------------------------ certificates
class CertificateOut(TimestampedModel):
    device_id: UUID
    serial_number: str
    subject_cn: str
    issuer_cn: str | None
    fingerprint_sha256: str | None
    valid_from: datetime
    valid_to: datetime
    status: CertificateStatus
    revoked_at: datetime | None


class CertificateIssueRequest(BaseModel):
    device_id: UUID
    common_name: str | None = None
    validity_days: int | None = Field(None, ge=1, le=3650)


class CertificateIssueResponse(BaseModel):
    serial_number: str
    certificate_pem: str
    ca_pem: str
    valid_to: datetime


class RevokeRequest(BaseModel):
    reason: str = "unspecified"


class SiteMapPoint(ORMModel):
    id: UUID
    name: str
    city: str | None
    country: str | None
    latitude: float | None
    longitude: float | None
    devices_total: int
    devices_online: int
    worst_severity: str | None
