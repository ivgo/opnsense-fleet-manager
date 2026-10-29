"""GitOps aggregates: repositories, policies, deployments, drift, change requests."""

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


class GitRepository(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "git_repositories"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_git_repositories_tenant_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[GitProvider] = mapped_column(
        SAEnum(GitProvider, native_enum=False, length=32), default=GitProvider.GENERIC, nullable=False
    )
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), default="main", nullable=False)
    auth_type: Mapped[GitAuthType] = mapped_column(
        SAEnum(GitAuthType, native_enum=False, length=16), default=GitAuthType.TOKEN, nullable=False
    )
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_commit_sha: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    settings: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)

    policies: Mapped[list[Policy]] = relationship(back_populates="repository", lazy="noload")


class Policy(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "environment", name="uq_policies_tenant_name_env"),
        Index("ix_policies_tenant_kind", "tenant_id", "kind", "environment"),
    )

    repo_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("git_repositories.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[PolicyKind] = mapped_column(
        SAEnum(PolicyKind, native_enum=False, length=32), default=PolicyKind.FIREWALL, nullable=False
    )
    environment: Mapped[Environment] = mapped_column(
        SAEnum(Environment, native_enum=False, length=32), default=Environment.DEVELOPMENT, nullable=False
    )
    path: Mapped[str | None] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[PolicyStatus] = mapped_column(
        SAEnum(PolicyStatus, native_enum=False, length=32), default=PolicyStatus.DRAFT, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    target_selector: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validation_errors: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))

    repository: Mapped[GitRepository | None] = relationship(back_populates="policies", lazy="joined")


class PolicyDeployment(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "policy_deployments"
    __table_args__ = (Index("ix_policy_deployments_tenant_env", "tenant_id", "environment", "created_at"),)

    policy_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("policies.id", ondelete="CASCADE"), index=True
    )
    environment: Mapped[Environment] = mapped_column(
        SAEnum(Environment, native_enum=False, length=32), nullable=False
    )
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[DeploymentStatus] = mapped_column(
        SAEnum(DeploymentStatus, native_enum=False, length=32),
        default=DeploymentStatus.PENDING,
        nullable=False,
    )
    plan: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    #: Materialised desired state captured at deploy time so a later rollback can
    #: replay the exact rule/NAT set instead of only changing the status.
    snapshot: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    target_device_ids: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    results: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    logs: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))


class DriftReport(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "drift_reports"
    __table_args__ = (Index("ix_drift_reports_tenant_device", "tenant_id", "device_id", "status"),)

    device_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("policies.id", ondelete="SET NULL")
    )
    status: Mapped[DriftStatus] = mapped_column(
        SAEnum(DriftStatus, native_enum=False, length=32), default=DriftStatus.OPEN, nullable=False
    )
    differences: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    desired_hash: Mapped[str | None] = mapped_column(String(64))
    actual_hash: Mapped[str | None] = mapped_column(String(64))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class ChangeRequest(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "change_requests"
    __table_args__ = (Index("ix_change_requests_tenant_status", "tenant_id", "status", "created_at"),)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[ChangeType] = mapped_column(SAEnum(ChangeType, native_enum=False, length=32), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    status: Mapped[ChangeStatus] = mapped_column(
        SAEnum(ChangeStatus, native_enum=False, length=32), default=ChangeStatus.PENDING, nullable=False
    )
    priority: Mapped[Priority] = mapped_column(
        SAEnum(Priority, native_enum=False, length=16), default=Priority.MEDIUM, nullable=False
    )
    environment: Mapped[Environment | None] = mapped_column(SAEnum(Environment, native_enum=False, length=32))
    requested_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    required_approvals: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    approvals: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
