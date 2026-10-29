"""Identity administration: users, roles, permission catalogue and API keys."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import update

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.security import enforce_password_policy, hash_password
from app.models.identity import ApiKey, RefreshToken, Role, User
from app.rbac.permissions import P
from app.repositories.identity import PermissionRepository
from app.schemas.common import Message, PageResponse
from app.schemas.identity import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    PermissionOut,
    RoleCreate,
    RoleMatrixEntry,
    RoleOut,
    RoleUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services.audit import AuditService
from app.services.identity import ApiKeyService, RoleService, UserService

users_router = APIRouter(prefix="/users", tags=["Users"])
roles_router = APIRouter(prefix="/roles", tags=["Roles"])
permissions_router = APIRouter(prefix="/permissions", tags=["Roles"])
api_keys_router = APIRouter(prefix="/api-keys", tags=["API keys"])


# --------------------------------------------------------------------------- serialisers
def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        created_at=user.created_at,
        updated_at=user.updated_at,
        tenant_id=user.tenant_id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        auth_provider=user.auth_provider,
        is_superadmin=user.is_superadmin,
        mfa_enabled=user.mfa_enabled,
        roles=sorted(role.name for role in user.roles),
        last_login_at=user.last_login_at,
    )


def _role_out(role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        created_at=role.created_at,
        updated_at=role.updated_at,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=list(role.permissions or []),
        tenant_id=role.tenant_id,
    )


def _api_key_out(key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id,
        created_at=key.created_at,
        updated_at=key.updated_at,
        name=key.name,
        key_prefix=key.key_prefix,
        scopes=list(key.scopes or []),
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
    )


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=12, max_length=128)
    revoke_sessions: bool = True


class UnlockResponse(BaseModel):
    id: uuid.UUID
    locked_until: datetime | None = None


# --------------------------------------------------------------------------- users
@users_router.get(
    "",
    response_model=PageResponse[UserOut],
    dependencies=[Depends(require_permissions(P.USER_READ))],
    summary="List users",
)
async def list_users(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    search: str | None = None,
) -> PageResponse[UserOut]:
    users, total = await UserService(session, tenant_id).list(
        page=pagination.page, size=pagination.size, search=search
    )
    return paginate([_user_out(user) for user in users], total, pagination, UserOut)


@users_router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.USER_WRITE))],
    summary="Create a user",
)
async def create_user(
    payload: UserCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> UserOut:
    service = UserService(session, tenant_id, principal.user_id)
    user = await service.create(payload)
    await session.commit()
    return _user_out(user)


@users_router.get(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_permissions(P.USER_READ))],
    summary="Get a user",
)
async def get_user(user_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> UserOut:
    return _user_out(await UserService(session, tenant_id).get(user_id))


@users_router.patch(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_permissions(P.USER_WRITE))],
    summary="Update a user",
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> UserOut:
    user = await UserService(session, tenant_id, principal.user_id).update(user_id, payload)
    await session.commit()
    return _user_out(user)


@users_router.delete(
    "/{user_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.USER_DELETE))],
    summary="Delete a user",
)
async def delete_user(
    user_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await UserService(session, tenant_id, principal.user_id).delete(user_id)
    await session.commit()
    return Message(message="User deleted")


@users_router.post(
    "/{user_id}/reset-password",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.USER_WRITE))],
    summary="Reset a user's password",
)
async def reset_password(
    user_id: uuid.UUID,
    payload: PasswordReset,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    enforce_password_policy(payload.new_password)
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id or user.deleted_at is not None:
        raise NotFoundError("User not found")
    if user.is_superadmin and not principal.is_superadmin:
        raise BadRequestError("Only a SuperAdmin can reset another SuperAdmin's password")

    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(UTC)
    user.failed_login_attempts = 0
    user.locked_until = None
    if payload.revoke_sessions:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    await AuditService(session).record(
        action="user.password_reset",
        resource_type="User",
        resource_id=user.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
        after={"revoke_sessions": payload.revoke_sessions},
    )
    await session.commit()
    return Message(
        message="Password reset; active sessions revoked" if payload.revoke_sessions else "Password reset"
    )


@users_router.post(
    "/{user_id}/unlock",
    response_model=UnlockResponse,
    dependencies=[Depends(require_permissions(P.USER_WRITE))],
    summary="Clear a lockout",
)
async def unlock_user(
    user_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> UnlockResponse:
    user = await session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id or user.deleted_at is not None:
        raise NotFoundError("User not found")
    user.failed_login_attempts = 0
    user.locked_until = None
    await AuditService(session).record(
        action="user.unlocked",
        resource_type="User",
        resource_id=user.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
    )
    await session.commit()
    return UnlockResponse(id=user.id, locked_until=user.locked_until)


# --------------------------------------------------------------------------- roles
@roles_router.get(
    "",
    response_model=list[RoleOut],
    dependencies=[Depends(require_permissions(P.ROLE_READ))],
    summary="List roles",
)
async def list_roles(session: SessionDep, tenant_id: TenantDep) -> list[RoleOut]:
    return [_role_out(role) for role in await RoleService(session, tenant_id).list()]


@roles_router.get(
    "/matrix",
    response_model=list[RoleMatrixEntry],
    dependencies=[Depends(require_permissions(P.ROLE_READ))],
    summary="Built-in role matrix",
)
async def role_matrix() -> list[RoleMatrixEntry]:
    return [RoleMatrixEntry(**entry) for entry in RoleService.matrix()]


@roles_router.post(
    "",
    response_model=RoleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.ROLE_WRITE))],
    summary="Create a custom role",
)
async def create_role(
    payload: RoleCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> RoleOut:
    role = await RoleService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return _role_out(role)


@roles_router.patch(
    "/{role_id}",
    response_model=RoleOut,
    dependencies=[Depends(require_permissions(P.ROLE_WRITE))],
    summary="Update a custom role",
)
async def update_role(
    role_id: uuid.UUID,
    payload: RoleUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> RoleOut:
    role = await RoleService(session, tenant_id, principal.user_id).update(role_id, payload)
    await session.commit()
    return _role_out(role)


# --------------------------------------------------------------------------- permissions
@permissions_router.get(
    "",
    response_model=list[PermissionOut],
    dependencies=[Depends(require_permissions(P.ROLE_READ))],
    summary="Permission catalogue",
)
async def list_permissions(session: SessionDep, tenant_id: TenantDep) -> list[PermissionOut]:
    service = RoleService(session, tenant_id)
    await service.sync_permission_catalogue()
    await session.commit()
    rows, _ = await PermissionRepository(session).list(size=1000, sort="code", order="asc")
    return [PermissionOut.model_validate(row) for row in rows]


# --------------------------------------------------------------------------- API keys
@api_keys_router.get(
    "",
    response_model=list[ApiKeyOut],
    dependencies=[Depends(require_permissions(P.APIKEY_READ))],
    summary="List API keys",
)
async def list_api_keys(session: SessionDep, tenant_id: TenantDep) -> list[ApiKeyOut]:
    return [_api_key_out(key) for key in await ApiKeyService(session, tenant_id).list()]


@api_keys_router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.APIKEY_WRITE))],
    summary="Create an API key (plaintext returned once)",
)
async def create_api_key(
    payload: ApiKeyCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> ApiKeyCreated:
    key, plaintext = await ApiKeyService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return ApiKeyCreated(**_api_key_out(key).model_dump(), key=plaintext)


@api_keys_router.delete(
    "/{key_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.APIKEY_WRITE))],
    summary="Revoke an API key",
)
async def revoke_api_key(
    key_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await ApiKeyService(session, tenant_id, principal.user_id).revoke(key_id)
    await session.commit()
    return Message(message="API key revoked")
