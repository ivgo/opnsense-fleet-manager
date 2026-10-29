from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import AuthProvider, RoleName, TenantPlan, TenantStatus, UserStatus
from app.schemas.common import ORMModel, TimestampedModel


# ------------------------------------------------------------------ tenants
class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    plan: TenantPlan = TenantPlan.ENTERPRISE
    device_limit: int = Field(1000, ge=1, le=100_000)
    contact_email: EmailStr | None = None
    settings: dict = Field(default_factory=dict)


class TenantUpdate(BaseModel):
    name: str | None = None
    status: TenantStatus | None = None
    plan: TenantPlan | None = None
    device_limit: int | None = Field(None, ge=1, le=100_000)
    contact_email: EmailStr | None = None
    settings: dict | None = None


class TenantOut(TimestampedModel):
    name: str
    slug: str
    status: TenantStatus
    plan: TenantPlan
    device_limit: int
    contact_email: str | None
    settings: dict
    device_count: int | None = None


class TenantStats(BaseModel):
    tenant_id: UUID
    devices_total: int
    devices_online: int
    devices_offline: int
    active_alerts: int
    storage_bytes: int
    users: int


# ------------------------------------------------------------------ roles & permissions
class PermissionOut(ORMModel):
    id: UUID
    code: str
    category: str
    description: str | None


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    description: str | None = None
    permissions: list[str] | None = None


class RoleOut(TimestampedModel):
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]
    tenant_id: UUID | None


class RoleMatrixEntry(BaseModel):
    role: RoleName
    description: str
    permissions: list[str]


# ------------------------------------------------------------------ users
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9._@-]+$")
    email: EmailStr
    full_name: str | None = None
    password: str | None = Field(None, min_length=12, max_length=128)
    role_ids: list[UUID] = Field(default_factory=list)
    role_names: list[RoleName] = Field(default_factory=list)
    auth_provider: AuthProvider = AuthProvider.LOCAL
    external_id: str | None = None
    is_superadmin: bool = False


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    status: UserStatus | None = None
    role_ids: list[UUID] | None = None
    preferences: dict | None = None


class UserOut(TimestampedModel):
    tenant_id: UUID | None
    username: str
    email: str
    full_name: str | None
    status: UserStatus
    auth_provider: AuthProvider
    is_superadmin: bool
    mfa_enabled: bool
    roles: list[str] = Field(default_factory=list)
    last_login_at: datetime | None


class UserInvite(BaseModel):
    email: EmailStr
    role_names: list[RoleName] = Field(default_factory=lambda: [RoleName.READ_ONLY])


# ------------------------------------------------------------------ api keys
class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    scopes: list[str] = Field(default_factory=list)
    expires_in_days: int | None = Field(None, ge=1, le=3650)


class ApiKeyOut(TimestampedModel):
    name: str
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="Plaintext key - returned exactly once")
