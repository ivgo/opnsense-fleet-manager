from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select

from app.core.exceptions import NotFoundError
from app.models.identity import ApiKey, Permission, RefreshToken, Role, Tenant, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def __init__(self, session, tenant_id: uuid.UUID | None = None) -> None:  # noqa: ANN001
        super().__init__(session, tenant_id)

    async def get_by_username(self, username: str, tenant_id: uuid.UUID | None = None) -> User | None:
        stmt = select(User).where(User.username == username, User.deleted_at.is_(None))
        tid = tenant_id or self.tenant_id
        if tid is not None:
            stmt = stmt.where(or_(User.tenant_id == tid, User.tenant_id.is_(None)))
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_email(self, email: str, tenant_id: uuid.UUID | None = None) -> User | None:
        stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
        tid = tenant_id or self.tenant_id
        if tid is not None:
            stmt = stmt.where(or_(User.tenant_id == tid, User.tenant_id.is_(None)))
        return (await self.session.execute(stmt)).scalars().first()

    async def get_with_roles(self, user_id: uuid.UUID) -> User:
        stmt = select(User).where(User.id == user_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def permissions_for(self, user: User) -> set[str]:
        if user.is_superadmin:
            from app.rbac.permissions import SUPER_ADMIN

            return {p.value for p in SUPER_ADMIN}
        perms: set[str] = set()
        for role in user.roles:
            perms.update(role.permissions or [])
        return perms

    async def role_names(self, user: User) -> list[str]:
        if user.is_superadmin:
            return ["SuperAdmin"]
        return [role.name for role in user.roles]


class RoleRepository(BaseRepository[Role]):
    model = Role
    soft_delete = False

    async def get_by_name(self, name: str, tenant_id: uuid.UUID | None = None) -> Role | None:
        stmt = select(Role).where(Role.name == name)
        tid = tenant_id or self.tenant_id
        if tid is not None:
            stmt = stmt.where(Role.tenant_id == tid)
        return (await self.session.execute(stmt)).scalars().first()

    async def system_roles(self) -> list[Role]:
        stmt = select(Role).where(Role.is_system.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())


class PermissionRepository(BaseRepository[Permission]):
    model = Permission
    tenant_scoped = False
    soft_delete = False

    async def by_category(self) -> dict[str, list[Permission]]:
        stmt = select(Permission).order_by(Permission.category, Permission.code)
        grouped: dict[str, list[Permission]] = {}
        for permission in (await self.session.execute(stmt)).scalars().all():
            grouped.setdefault(permission.category, []).append(permission)
        return grouped


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken
    soft_delete = False

    async def get_active(self, jti: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(
            RefreshToken.jti == jti,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.utcnow(),
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def revoke_all_for_user(self, user_id: uuid.UUID, *, except_jti: str | None = None) -> int:
        from app.db.base import utcnow

        stmt = select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        tokens = (await self.session.execute(stmt)).scalars().all()
        count = 0
        for token in tokens:
            if except_jti and token.jti == except_jti:
                continue
            token.revoked_at = utcnow()
            count += 1
        await self.session.flush()
        return count


class ApiKeyRepository(BaseRepository[ApiKey]):
    model = ApiKey
    soft_delete = False

    async def get_by_prefix(self, prefix: str) -> ApiKey | None:
        stmt = select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.revoked_at.is_(None))
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        return (await self.session.execute(stmt)).scalars().first()


class TenantRepository(BaseRepository[Tenant]):
    model = Tenant
    tenant_scoped = False

    async def get_by_slug(self, slug: str) -> Tenant | None:
        stmt = select(Tenant).where(Tenant.slug == slug, Tenant.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalars().first()
