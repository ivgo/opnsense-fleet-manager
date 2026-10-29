from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import AuthProvider
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=512)
    tenant: str | None = Field(None, description="Tenant slug; omitted for platform (SuperAdmin) login")
    mfa_code: str | None = Field(None, description="TOTP code or backup code")


class MfaChallenge(BaseModel):
    mfa_required: bool = True
    challenge_token: str
    methods: list[str] = ["totp", "backup_code"]


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int
    mfa_required: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
    all_sessions: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)


class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    backup_codes: list[str]


class MfaVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=12)
    challenge_token: str | None = Field(
        None, description="Challenge token returned by /auth/login when MFA is required"
    )


class MfaDisableRequest(BaseModel):
    password: str
    code: str


class OidcCallback(BaseModel):
    code: str
    state: str | None = None
    redirect_uri: str | None = None


class SessionInfo(ORMModel):
    id: UUID
    user_id: UUID
    jti: str
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    expires_at: datetime


class CurrentUser(BaseModel):
    id: UUID
    tenant_id: UUID | None
    username: str
    email: EmailStr
    full_name: str | None
    roles: list[str]
    permissions: list[str]
    is_superadmin: bool
    mfa_enabled: bool
    auth_provider: AuthProvider
    last_login_at: datetime | None = None


class LoginResponse(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    mfa_required: bool = False
    challenge_token: str | None = None
    methods: list[str] = Field(default_factory=list)
    user: CurrentUser | None = None


class AuthProviders(BaseModel):
    local: bool = True
    ldap: bool = False
    oidc: bool = False
    entra_id: bool = False
    saml: bool = False
    mfa_enabled: bool = True


class OidcAuthorizeResponse(BaseModel):
    authorization_url: str
    state: str


class SamlAuthorizeResponse(BaseModel):
    authorization_url: str
    state: str
