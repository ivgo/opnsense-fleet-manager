from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    ChangeStatus,
    ChangeType,
    DeploymentStatus,
    DriftStatus,
    Environment,
    GitAuthType,
    GitProvider,
    PolicyKind,
    PolicyStatus,
    Priority,
)
from app.schemas.common import TimestampedModel


class GitRepositoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    provider: GitProvider
    url: str = Field(min_length=8, max_length=512)
    default_branch: str = "main"
    auth_type: GitAuthType = GitAuthType.TOKEN
    token: str | None = Field(None, description="PAT / deploy token, encrypted at rest")
    ssh_key: str | None = None
    auto_sync: bool = False
    sync_interval_minutes: int = Field(60, ge=5, le=1440)


class GitRepositoryUpdate(BaseModel):
    default_branch: str | None = None
    token: str | None = None
    auto_sync: bool | None = None
    sync_interval_minutes: int | None = None


class GitRepositoryOut(TimestampedModel):
    name: str
    provider: GitProvider
    url: str
    default_branch: str
    auth_type: GitAuthType
    auto_sync: bool
    sync_interval_minutes: int
    last_sync_at: datetime | None
    last_commit_sha: str | None
    status: str


class GitBranch(BaseModel):
    name: str
    sha: str
    protected: bool = False


class GitCommit(BaseModel):
    sha: str
    message: str
    author: str
    date: datetime


class PolicyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    kind: PolicyKind = PolicyKind.FIREWALL
    environment: Environment = Environment.DEVELOPMENT
    repo_id: uuid.UUID | None = None
    path: str | None = None
    content: str = ""
    description: str | None = None
    target_selector: dict = Field(default_factory=dict)


class PolicyUpdate(BaseModel):
    content: str | None = None
    description: str | None = None
    target_selector: dict | None = None
    status: PolicyStatus | None = None


class PolicyOut(TimestampedModel):
    name: str
    kind: PolicyKind
    environment: Environment
    repo_id: uuid.UUID | None
    path: str | None
    content: str
    content_hash: str | None
    version: int
    status: PolicyStatus
    description: str | None
    validated_at: datetime | None
    validation_errors: list[Any]
    target_selector: dict


class PolicyValidationIssue(BaseModel):
    severity: str = "error"
    code: str
    message: str
    path: str | None = None
    line: int | None = None
    remediation: str | None = None


class PolicyValidationResult(BaseModel):
    valid: bool
    errors: list[PolicyValidationIssue] = Field(default_factory=list)
    warnings: list[PolicyValidationIssue] = Field(default_factory=list)
    rule_count: int = 0
    conflict_count: int = 0
    compiled: dict | None = None


class PolicyDiffEntry(BaseModel):
    path: str
    change: str
    before: Any | None = None
    after: Any | None = None


class PolicyDiff(BaseModel):
    policy_id: uuid.UUID
    base_version: int
    target_version: int
    entries: list[PolicyDiffEntry] = Field(default_factory=list)
    summary: str


class DeployRequest(BaseModel):
    policy_id: uuid.UUID
    device_ids: list[uuid.UUID] = Field(
        default_factory=list, description="Empty = resolve via target_selector"
    )
    environment: Environment | None = None
    dry_run: bool = False
    change_request_id: uuid.UUID | None = None


class DeploymentOut(TimestampedModel):
    policy_id: uuid.UUID
    environment: Environment
    commit_sha: str | None
    status: DeploymentStatus
    plan: dict
    target_device_ids: list[uuid.UUID]
    results: list[dict]
    logs: str | None
    started_at: datetime | None
    completed_at: datetime | None


class RollbackRequest(BaseModel):
    deployment_id: uuid.UUID


class DriftOut(TimestampedModel):
    device_id: uuid.UUID
    policy_id: uuid.UUID | None
    status: DriftStatus
    differences: list[dict]
    desired_hash: str | None
    actual_hash: str | None
    detected_at: datetime
    resolved_at: datetime | None


class DriftScanRequest(BaseModel):
    device_ids: list[uuid.UUID] = Field(default_factory=list)


class ChangeRequestCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str | None = None
    type: ChangeType
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    payload: dict = Field(default_factory=dict)
    priority: Priority = Priority.MEDIUM
    environment: Environment | None = None
    required_approvals: int = Field(1, ge=1, le=5)
    expires_in_hours: int = Field(72, ge=1, le=720)


class ChangeRequestOut(TimestampedModel):
    title: str
    description: str | None
    type: ChangeType
    resource_type: str | None
    resource_id: uuid.UUID | None
    payload: dict
    status: ChangeStatus
    priority: Priority
    environment: Environment | None
    requested_by: uuid.UUID
    required_approvals: int
    approvals: list[dict]
    expires_at: datetime | None
    applied_at: datetime | None


class ApprovalDecision(BaseModel):
    comment: str | None = Field(None, max_length=2000)


class PolicySimulationRequest(BaseModel):
    policy_id: uuid.UUID
    source_ip: str
    destination_ip: str
    protocol: str = "tcp"
    destination_port: int | None = None
    interface: str | None = None


class PolicySimulationResult(BaseModel):
    matched: bool
    action: str
    rule_name: str | None
    rule_index: int | None
    evaluated: int
    shadowed_rules: list[str] = Field(default_factory=list)


class PromotionRequest(BaseModel):
    policy_id: uuid.UUID
    source_environment: Environment
    target_environment: Environment
    create_change_request: bool = True
