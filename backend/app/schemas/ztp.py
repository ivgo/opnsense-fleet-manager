from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.enums import DiscoveryMethod, ZtpStatus
from app.schemas.common import TimestampedModel


class EnrollmentTokenCreate(BaseModel):
    site_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    device_serial: str | None = None
    device_mac: str | None = Field(None, pattern=r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
    hostname: str | None = None
    ttl_minutes: int = Field(default_factory=lambda: settings.ENROLLMENT_TOKEN_TTL_MINUTES, ge=5, le=10080)
    discovery_method: DiscoveryMethod = DiscoveryMethod.TOKEN


class EnrollmentTokenResponse(BaseModel):
    enrollment_id: uuid.UUID
    token: str = Field(description="One-time bootstrap token, shown exactly once")
    expires_at: datetime
    bootstrap_url: str
    site_id: uuid.UUID | None
    template_id: uuid.UUID | None


class EnrollmentOut(TimestampedModel):
    site_id: uuid.UUID | None
    token_hint: str
    device_serial: str | None
    device_mac: str | None
    hostname: str | None
    status: ZtpStatus
    discovery_method: DiscoveryMethod
    template_id: uuid.UUID | None
    group_id: uuid.UUID | None
    device_id: uuid.UUID | None
    certificate_serial: str | None
    hardware_profile: dict
    enrolled_at: datetime | None
    provisioned_at: datetime | None
    expires_at: datetime


class EnrollmentRequest(BaseModel):
    token: str = Field(min_length=16)
    serial_number: str = Field(min_length=3, max_length=128)
    mac_address: str | None = None
    hostname: str | None = None
    model: str | None = None
    firmware_version: str | None = None
    csr_pem: str | None = Field(None, description="PKCS#10 CSR generated on the device")
    hardware_profile: dict = Field(default_factory=dict)


class BootstrapPackage(BaseModel):
    enrollment_id: uuid.UUID
    device_name: str
    site_id: uuid.UUID | None
    template: dict | None
    policies: list[dict] = Field(default_factory=list)
    vpn: list[dict] = Field(default_factory=list)
    monitoring: dict = Field(default_factory=dict)
    platform: dict = Field(default_factory=dict)


class EnrollmentResponse(BaseModel):
    status: str
    device_id: uuid.UUID
    device_name: str
    certificate_pem: str
    ca_pem: str
    certificate_serial: str
    valid_to: datetime
    bootstrap: BootstrapPackage
    heartbeat_url: str
    heartbeat_interval_seconds: int


class DiscoveryInfo(BaseModel):
    platform_url: str
    bootstrap_endpoint: str
    enrollment_endpoint: str
    ca_fingerprint: str | None = None
    tenant_hint: str | None = None
