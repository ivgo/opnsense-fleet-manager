"""FastAPI dependencies: authentication, tenant context, RBAC guards, pagination."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError, TenantIsolationError
from app.core.logging import tenant_id_ctx, user_id_ctx
from app.core.security import decode_token, token_fingerprint
from app.db.session import get_session
from app.models.enums import UserStatus
from app.models.identity import ApiKey, User
from app.models.topology import Device
from app.rbac.permissions import SUPER_ADMIN, P
from app.repositories.identity import ApiKeyRepository, TenantRepository, UserRepository

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token or OFME API key")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(slots=True)
class Principal:
    subject: str
    username: str
    email: str | None
    tenant_id: uuid.UUID | None
    user_id: uuid.UUID | None = None
    roles: list[str] = field(default_factory=list)
    permissions: frozenset[str] = field(default_factory=frozenset)
    is_superadmin: bool = False
    auth_method: Literal["jwt", "api_key"] = "jwt"
    api_key_id: uuid.UUID | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)

    def can(self, permission: P | str) -> bool:
        if self.is_superadmin:
            return True
        code = permission.value if isinstance(permission, P) else permission
        if code == "*":
            return True
        return code in self.permissions

    def can_all(self, permissions: list[P | str]) -> bool:
        return all(self.can(permission) for permission in permissions)

    def can_any(self, permissions: list[P | str]) -> bool:
        return any(self.can(permission) for permission in permissions)

    @property
    def is_platform_admin(self) -> bool:
        return self.is_superadmin


async def _user_principal(
    session: AsyncSession, user: User, *, method: Literal["jwt", "api_key"]
) -> Principal:
    if user.status != UserStatus.ACTIVE:
        raise AuthenticationError("User account is not active")
    users = UserRepository(session, user.tenant_id)
    role_names = await users.role_names(user)
    if user.is_superadmin:
        perms = frozenset(p.value for p in SUPER_ADMIN)
    else:
        perms = frozenset(await users.permissions_for(user))
    return Principal(
        subject=str(user.id),
        username=user.username,
        email=user.email,
        tenant_id=user.tenant_id,
        user_id=user.id,
        roles=role_names,
        permissions=perms,
        is_superadmin=user.is_superadmin,
        auth_method=method,
    )


async def principal_from_token(session: AsyncSession, token: str) -> Principal:
    """Shared by HTTP dependencies and the WebSocket handshake."""
    if not token:
        raise AuthenticationError("Missing bearer token")

    if token.startswith(f"{settings.API_KEY_PREFIX}_"):
        repository = ApiKeyRepository(session)
        api_key: ApiKey | None = await repository.get_by_hash(token_fingerprint(token))
        if api_key is None:
            raise AuthenticationError("Invalid API key")
        from datetime import UTC, datetime

        if api_key.expires_at and api_key.expires_at <= datetime.now(UTC):
            raise AuthenticationError("API key has expired")
        if api_key.user_id is None:
            raise AuthenticationError("API key has no owner")
        user = await session.get(User, api_key.user_id)
        if user is None:
            raise AuthenticationError("API key owner no longer exists")
        principal = await _user_principal(session, user, method="api_key")
        scopes = frozenset(api_key.scopes or [])
        if scopes and "*" not in scopes:
            principal.scopes = scopes
            if not principal.is_superadmin:
                principal.permissions = frozenset(principal.permissions & scopes)
        principal.tenant_id = api_key.tenant_id
        principal.api_key_id = api_key.id
        api_key.last_used_at = datetime.now(UTC)
        await session.flush()
    else:
        payload = decode_token(token, expected_type="access")
        try:
            user_id = uuid.UUID(str(payload["sub"]))
        except (KeyError, ValueError) as exc:
            raise AuthenticationError("Malformed subject claim") from exc
        user = await session.get(User, user_id)
        if user is None:
            raise AuthenticationError("User no longer exists")
        principal = await _user_principal(session, user, method="jwt")

    tenant_id_ctx.set(str(principal.tenant_id) if principal.tenant_id else "-")
    user_id_ctx.set(str(principal.user_id) if principal.user_id else "-")
    return principal


async def get_principal(
    request: Request,
    session: SessionDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    # Support both Authorization header and HttpOnly cookies
    token = credentials.credentials if credentials else None
    if not token:
        token = request.cookies.get("ofme_access_token")
    if not token:
        raise AuthenticationError("Authentication required")
    principal = await principal_from_token(session, token)
    request.state.principal = principal
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


async def get_tenant_id(
    principal: CurrentPrincipal,
    session: SessionDep,
    x_tenant_id: uuid.UUID | None = Header(None, alias="X-Tenant-Id"),
) -> uuid.UUID:
    """Resolve the effective tenant, enforcing isolation for tenant-bound users."""
    if principal.is_superadmin:
        if x_tenant_id is not None:
            tenants = TenantRepository(session)
            tenant = await tenants.get(x_tenant_id)
            if tenant is None:
                raise TenantIsolationError("Requested tenant does not exist")
            return tenant.id
        if principal.tenant_id is not None:
            return principal.tenant_id
        raise TenantIsolationError("SuperAdmin requests must specify X-Tenant-Id")

    if principal.tenant_id is None:
        raise TenantIsolationError("User is not bound to a tenant")
    if x_tenant_id is not None and x_tenant_id != principal.tenant_id:
        raise TenantIsolationError("Cross-tenant access is not permitted")
    return principal.tenant_id


TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


def require_permissions(*required: P | str, any_of: bool = False):
    """Dependency factory enforcing the RBAC matrix on an endpoint."""

    async def guard(principal: CurrentPrincipal) -> Principal:
        if principal.is_superadmin:
            return principal
        allowed = principal.can_any(list(required)) if any_of else principal.can_all(list(required))
        if not allowed:
            raise PermissionDeniedError(
                "Missing required permission(s)",
                details=[p.value if isinstance(p, P) else p for p in required],
            )
        return principal

    return guard


def require_superadmin():
    async def guard(principal: CurrentPrincipal) -> Principal:
        if not principal.is_superadmin:
            raise PermissionDeniedError("SuperAdmin privileges are required")
        return principal

    return guard


@dataclass(slots=True)
class Pagination:
    page: int
    size: int
    sort: str | None
    order: str

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


async def get_pagination(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    sort: str | None = Query(None, max_length=64),
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> Pagination:
    return Pagination(page=page, size=size, sort=sort, order=order)


PaginationDep = Annotated[Pagination, Depends(get_pagination)]


async def get_device_for_principal(
    device_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> Device:
    """Resolve a device and guarantee it belongs to the caller's tenant."""
    device = await session.get(Device, device_id)
    if device is None or device.deleted_at is not None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Device not found")
    if not principal.is_superadmin and device.tenant_id != principal.tenant_id:
        raise TenantIsolationError("Device belongs to another tenant")
    return device


DeviceDep = Annotated[Device, Depends(get_device_for_principal)]


async def get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


ClientIP = Annotated[str | None, Depends(get_client_ip)]


async def get_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
