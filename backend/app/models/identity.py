"""Identity & tenancy aggregate: Tenant, User, Role, Permission, tokens, API keys."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
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

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AuthProvider, RoleName, TenantPlan, TenantStatus, UserStatus

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[TenantStatus] = mapped_column(
        SAEnum(TenantStatus, native_enum=False, length=32), default=TenantStatus.ACTIVE, nullable=False
    )
    plan: Mapped[TenantPlan] = mapped_column(
        SAEnum(TenantPlan, native_enum=False, length=32), default=TenantPlan.ENTERPRISE, nullable=False
    )
    device_limit: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255))
    settings: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    labels: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)

    users: Mapped[list[User]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", lazy="noload"
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        Index("ix_users_external", "auth_provider", "external_id"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, native_enum=False, length=32), default=UserStatus.ACTIVE, nullable=False
    )
    auth_provider: Mapped[AuthProvider] = mapped_column(
        SAEnum(AuthProvider, native_enum=False, length=32), default=AuthProvider.LOCAL, nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(String(512))
    mfa_backup_codes: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    mfa_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferences: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)

    tenant: Mapped[Tenant | None] = relationship(back_populates="users", lazy="joined")
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, back_populates="users", lazy="selectin")


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    permissions: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)

    users: Mapped[list[User]] = relationship(secondary=user_roles, back_populates="roles", lazy="noload")

    @property
    def role_enum(self) -> RoleName | None:
        try:
            return RoleName(self.name)
        except ValueError:
            return None


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_dangerous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user", "user_id", "revoked_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"))
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip_address: Mapped[str | None] = mapped_column(String(64))


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_tenant", "tenant_id", "revoked_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
