"""Identity & tenancy application services."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.security import (
    enforce_password_policy,
    generate_api_key,
    hash_password,
)
from app.models.enums import RoleName, TenantStatus
from app.models.identity import ApiKey, Permission, Role, Tenant, User
from app.models.topology import Device
from app.rbac.permissions import ROLE_MATRIX, permissions_for, role_descriptions
from app.repositories import UnitOfWork
from app.schemas.identity import (
    ApiKeyCreate,
    RoleCreate,
    RoleUpdate,
    TenantCreate,
    TenantUpdate,
    UserCreate,
    UserUpdate,
)
from app.services.audit import AuditService

log = get_logger("ofme.identity")


class TenantService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID | None = None, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.uow = UnitOfWork(session, tenant_id)
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, payload: TenantCreate) -> Tenant:
        if await self.uow.tenants.get_by_slug(payload.slug):
            raise ConflictError(f"Tenant slug '{payload.slug}' is already taken")
        tenant = Tenant(
            name=payload.name,
            slug=payload.slug,
            plan=payload.plan,
            device_limit=payload.device_limit,
            contact_email=payload.contact_email,
            settings=payload.settings,
            status=TenantStatus.ACTIVE,
        )
        self.session.add(tenant)
        await self.session.flush()
        await self._seed_roles(tenant.id)
        await self.audit.record(
            action="tenant.created",
            resource_type="Tenant",
            resource_id=tenant.id,
            tenant_id=tenant.id,
            user_id=self.actor_id,
            after={"name": tenant.name, "slug": tenant.slug},
        )
        log.info("tenant.created", tenant=tenant.slug)
        return tenant

    async def _seed_roles(self, tenant_id: uuid.UUID) -> None:
        descriptions = role_descriptions()
        for role_name in ROLE_MATRIX:
            expected = permissions_for(role_name)
            existing = (
                (
                    await self.session.execute(
                        select(Role).where(Role.tenant_id == tenant_id, Role.name == role_name.value)
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                # Upgrade path: a system role created by an earlier release must
                # pick up permissions added to the matrix since then.
                if existing.is_system:
                    if existing.permissions != expected:
                        existing.permissions = expected
                    if existing.description != descriptions[role_name]:
                        existing.description = descriptions[role_name]
                continue
            self.session.add(
                Role(
                    tenant_id=tenant_id,
                    name=role_name.value,
                    description=descriptions[role_name],
                    is_system=True,
                    permissions=expected,
                )
            )
        await self.session.flush()

    async def update(self, tenant_id: uuid.UUID, payload: TenantUpdate) -> Tenant:
        tenant = await self.uow.tenants.get_or_404(tenant_id)
        before = {"name": tenant.name, "status": tenant.status.value, "plan": tenant.plan.value}
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(tenant, field, value)
        await self.session.flush()
        await self.audit.record(
            action="tenant.updated",
            resource_type="Tenant",
            resource_id=tenant.id,
            tenant_id=tenant.id,
            user_id=self.actor_id,
            before=before,
            after=payload.model_dump(exclude_unset=True),
        )
        return tenant

    async def list(
        self, *, page: int = 1, size: int = 50, search: str | None = None
    ) -> tuple[list[Tenant], int]:
        return await self.uow.tenants.list(search=search, page=page, size=size)

    async def stats(self, tenant_id: uuid.UUID) -> dict:
        total = (
            await self.session.execute(
                select(func.count())
                .select_from(Device)
                .where(Device.tenant_id == tenant_id, Device.deleted_at.is_(None))
            )
        ).scalar_one()
        online = (
            await self.session.execute(
                select(func.count())
                .select_from(Device)
                .where(Device.tenant_id == tenant_id, Device.status == "online", Device.deleted_at.is_(None))
            )
        ).scalar_one()
        users = (
            await self.session.execute(
                select(func.count())
                .select_from(User)
                .where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
            )
        ).scalar_one()
        return {"devices_total": int(total), "devices_online": int(online), "users": int(users)}


class RoleService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def list(self) -> list[Role]:
        roles, _ = await self.uow.roles.list(size=200)
        return roles

    async def create(self, payload: RoleCreate) -> Role:
        if await self.uow.roles.get_by_name(payload.name, self.tenant_id):
            raise ConflictError(f"Role '{payload.name}' already exists")
        self._validate_permissions(payload.permissions)
        role = Role(
            tenant_id=self.tenant_id,
            name=payload.name,
            description=payload.description,
            is_system=False,
            permissions=sorted(set(payload.permissions)),
        )
        self.session.add(role)
        await self.session.flush()
        await self.audit.record(
            action="role.created",
            resource_type="Role",
            resource_id=role.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": role.name, "permissions": role.permissions},
        )
        return role

    async def update(self, role_id: uuid.UUID, payload: RoleUpdate) -> Role:
        role = await self.uow.roles.get_or_404(role_id)
        if role.is_system:
            raise BadRequestError("System roles cannot be modified; create a custom role instead")
        if payload.permissions is not None:
            self._validate_permissions(payload.permissions)
            role.permissions = sorted(set(payload.permissions))
        if payload.description is not None:
            role.description = payload.description
        await self.session.flush()
        await self.audit.record(
            action="role.updated",
            resource_type="Role",
            resource_id=role.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"permissions": role.permissions},
        )
        return role

    @staticmethod
    def _validate_permissions(codes: list[str]) -> None:
        from app.rbac.permissions import P

        valid = {p.value for p in P}
        unknown = sorted(set(codes) - valid)
        if unknown:
            raise BadRequestError(f"Unknown permissions: {', '.join(unknown)}")

    @staticmethod
    def matrix() -> list[dict]:
        return [
            {
                "role": role.value,
                "description": role_descriptions()[role],
                "permissions": permissions_for(role),
            }
            for role in RoleName
        ]

    async def sync_permission_catalogue(self) -> int:
        from app.rbac.permissions import P

        created = 0
        existing = {row.code for row in (await self.session.execute(select(Permission))).scalars().all()}
        for permission in P:
            if permission.value in existing:
                continue
            category = permission.value.split(":", 1)[0]
            self.session.add(
                Permission(
                    code=permission.value,
                    category=category,
                    description=permission.name.replace("_", " ").title(),
                    is_dangerous=permission.value.split(":", 1)[1]
                    in {"delete", "restore", "deploy", "approve"},
                )
            )
            created += 1
        await self.session.flush()
        return created

    async def sync_system_roles(self) -> int:
        """Align every built-in role row with the current ``ROLE_MATRIX``.

        Roles marked ``is_system`` are owned by the application, so new
        permissions must reach existing deployments too — ``_seed_roles`` alone
        only runs when a tenant or the platform is first created. Custom roles
        are never modified.
        """
        descriptions = role_descriptions()
        rows = (await self.session.execute(select(Role).where(Role.is_system.is_(True)))).scalars().all()
        updated = 0
        for role in rows:
            try:
                role_name = RoleName(role.name)
            except ValueError:
                continue
            expected = permissions_for(role_name)
            description = descriptions[role_name]
            if role.permissions != expected or role.description != description:
                role.permissions = expected
                role.description = description
                updated += 1
        await self.session.flush()
        return updated


class UserService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, payload: UserCreate) -> User:
        if await self.uow.users.get_by_username(payload.username, self.tenant_id):
            raise ConflictError(f"Username '{payload.username}' already exists")
        if await self.uow.users.get_by_email(payload.email, self.tenant_id):
            raise ConflictError(f"Email '{payload.email}' already exists")

        if payload.password:
            enforce_password_policy(payload.password)
        elif payload.auth_provider == "local":
            raise BadRequestError("Local users require a password")

        roles: list[Role] = []
        for role_id in payload.role_ids:
            role = await self.uow.roles.get(role_id)
            if role:
                roles.append(role)
        for role_name in payload.role_names:
            role = await self.uow.roles.get_by_name(role_name.value, self.tenant_id)
            if role:
                roles.append(role)
        if not roles:
            default = await self.uow.roles.get_by_name(RoleName.READ_ONLY.value, self.tenant_id)
            if default:
                roles.append(default)

        user = User(
            tenant_id=self.tenant_id,
            username=payload.username,
            email=payload.email,
            full_name=payload.full_name,
            password_hash=hash_password(payload.password) if payload.password else None,
            auth_provider=payload.auth_provider,
            external_id=payload.external_id,
            is_superadmin=payload.is_superadmin,
            roles=roles,
        )
        self.session.add(user)
        await self.session.flush()
        await self.audit.record(
            action="user.created",
            resource_type="User",
            resource_id=user.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"username": user.username, "email": user.email, "roles": [r.name for r in roles]},
        )
        return user

    async def update(self, user_id: uuid.UUID, payload: UserUpdate) -> User:
        user = await self.uow.users.get_or_404(user_id)
        before = {"status": user.status.value, "email": user.email, "roles": [r.name for r in user.roles]}
        data = payload.model_dump(exclude_unset=True)
        role_ids = data.pop("role_ids", None)
        for field, value in data.items():
            setattr(user, field, value)
        if role_ids is not None:
            roles: list[Role] = []
            for role_id in role_ids:
                role = await self.uow.roles.get(role_id)
                if role:
                    roles.append(role)
            user.roles = roles
        await self.session.flush()
        await self.audit.record(
            action="user.updated",
            resource_type="User",
            resource_id=user.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before=before,
            after={"status": user.status.value, "email": user.email, "roles": [r.name for r in user.roles]},
        )
        return user

    async def delete(self, user_id: uuid.UUID) -> None:
        user = await self.uow.users.get_or_404(user_id)
        if user.id == self.actor_id:
            raise BadRequestError("You cannot delete your own account")
        await self.uow.users.delete(user)
        await self.audit.record(
            action="user.deleted",
            resource_type="User",
            resource_id=user.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
        )

    async def list(
        self, *, page: int = 1, size: int = 50, search: str | None = None
    ) -> tuple[list[User], int]:
        return await self.uow.users.list(
            search=search, search_fields=("username", "email", "full_name"), page=page, size=size
        )

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self.uow.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user


class ApiKeyService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.uow = UnitOfWork(session, tenant_id)
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, payload: ApiKeyCreate) -> tuple[ApiKey, str]:
        plaintext, prefix, key_hash = generate_api_key()
        from datetime import UTC, datetime, timedelta

        expires_at = (
            datetime.now(UTC) + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
        )
        api_key = ApiKey(
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            name=payload.name,
            key_prefix=prefix,
            key_hash=key_hash,
            scopes=payload.scopes,
            expires_at=expires_at,
        )
        self.session.add(api_key)
        await self.session.flush()
        await self.audit.record(
            action="apikey.created",
            resource_type="ApiKey",
            resource_id=api_key.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": api_key.name, "prefix": prefix},
        )
        return api_key, plaintext

    async def list(self) -> list[ApiKey]:
        keys, _ = await self.uow.api_keys.list(size=200)
        return keys

    async def revoke(self, key_id: uuid.UUID) -> None:
        from datetime import UTC, datetime

        api_key = await self.uow.api_keys.get_or_404(key_id)
        api_key.revoked_at = datetime.now(UTC)
        await self.session.flush()
        await self.audit.record(
            action="apikey.revoked",
            resource_type="ApiKey",
            resource_id=api_key.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
        )


class SystemBootstrapService:
    """Idempotent platform bootstrap: default tenant, roles, SuperAdmin, permissions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(
        self, *, admin_email: str, admin_password: str | None, tenant_slug: str, tenant_name: str
    ) -> dict:
        tenant = (
            (await self.session.execute(select(Tenant).where(Tenant.slug == tenant_slug))).scalars().first()
        )
        if tenant is None:
            tenant = Tenant(name=tenant_name, slug=tenant_slug, plan="enterprise", device_limit=10_000)
            self.session.add(tenant)
            await self.session.flush()

        await TenantService(self.session, tenant.id)._seed_roles(tenant.id)
        await RoleService(self.session, tenant.id).sync_permission_catalogue()

        superadmin_role = (
            (
                await self.session.execute(
                    select(Role).where(Role.tenant_id == tenant.id, Role.name == RoleName.SUPER_ADMIN.value)
                )
            )
            .scalars()
            .first()
        )

        # `selectinload` keeps the relationship loaded so the membership check
        # below never triggers implicit IO (which asyncpg/greenlet forbids).
        admin = (
            (
                await self.session.execute(
                    select(User)
                    .options(selectinload(User.roles))
                    .where(User.email == admin_email, User.tenant_id == tenant.id)
                )
            )
            .scalars()
            .first()
        )
        created_admin = False
        if admin is None:
            admin = User(
                tenant_id=tenant.id,
                username="admin",
                email=admin_email,
                full_name="Platform Administrator",
                password_hash=hash_password(admin_password) if admin_password else None,
                status="active",
                is_superadmin=True,
                roles=[superadmin_role] if superadmin_role is not None else [],
            )
            self.session.add(admin)
            await self.session.flush()
            created_admin = True
        elif superadmin_role is not None and superadmin_role not in admin.roles:
            admin.roles.append(superadmin_role)

        await self.session.commit()
        return {
            "tenant_id": str(tenant.id),
            "tenant_slug": tenant.slug,
            "admin_id": str(admin.id),
            "admin_created": created_admin,
            "password_set": bool(admin_password),
        }
