from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ComplianceFramework
from app.schemas.common import TimestampedModel


class ComplianceRunRequest(BaseModel):
    framework: ComplianceFramework
    device_ids: list[uuid.UUID] = Field(default_factory=list, description="Empty = all devices in tenant")


class ControlResult(BaseModel):
    control_id: str
    title: str
    status: str
    severity: str
    evidence: str | None = None
    remediation: str | None = None
    affected_devices: list[uuid.UUID] = Field(default_factory=list)


class ComplianceReportOut(TimestampedModel):
    framework: ComplianceFramework
    scope: dict
    status: str
    score: float
    controls_total: int
    controls_passed: int
    controls_failed: int
    findings: list[dict]
    controls: list[dict]
    summary: str | None
    artifact_key: str | None
    generated_at: datetime


class ComplianceSummary(BaseModel):
    framework: ComplianceFramework
    latest_score: float | None
    controls_total: int
    controls_failed: int
    last_run: datetime | None
    trend: list[dict] = Field(default_factory=list)


class RemediationRequest(BaseModel):
    finding_ids: list[str] = Field(default_factory=list)
    device_ids: list[uuid.UUID] = Field(default_factory=list)
    dry_run: bool = True


class RemediationResult(BaseModel):
    requested: int
    remediated: int
    failed: int
    details: list[dict] = Field(default_factory=list)


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: uuid.UUID | None
    user_id: uuid.UUID | None
    actor: str | None
    action: str
    resource_type: str
    resource_id: str | None
    result: str
    ip_address: str | None
    request_id: str | None
    method: str | None
    path: str | None
    status_code: int | None
    before: dict | None
    after: dict | None
    error: str | None
    created_at: datetime


class AuditQuery(BaseModel):
    action: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    user_id: uuid.UUID | None = None
    result: str | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None


class AuditIntegrityResult(BaseModel):
    checked: int
    valid: bool
    first_broken_id: int | None = None
    last_hash: str | None = None
