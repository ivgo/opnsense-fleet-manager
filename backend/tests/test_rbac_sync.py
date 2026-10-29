"""System-role synchronisation: upgraded deployments must gain new permissions.

Adding a permission to ``ROLE_MATRIX`` is only half the job — role rows are
materialised in the database, so a deployment installed before the permission
existed keeps the old list unless startup re-aligns it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RoleName
from app.models.identity import Role, Tenant
from app.rbac.permissions import ROLE_MATRIX, permissions_for
from app.services.identity import RoleService, TenantService


async def _tenant(session: AsyncSession) -> Tenant:
    tenant = Tenant(
        name="RBAC Sync",
        slug=f"rbac-sync-{uuid.uuid4().hex[:8]}",
        plan="enterprise",
        device_limit=10,
    )
    session.add(tenant)
    await session.flush()
    return tenant


@pytest.mark.asyncio(loop_scope="session")
async def test_seed_roles_creates_current_matrix(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    await TenantService(db_session, tenant.id)._seed_roles(tenant.id)
    await db_session.flush()

    rows = (await db_session.execute(select(Role).where(Role.tenant_id == tenant.id))).scalars().all()
    assert {row.name for row in rows} == {role.value for role in ROLE_MATRIX}
    for row in rows:
        if row.name in {RoleName.SUPER_ADMIN.value, RoleName.ADMIN.value, RoleName.OPERATOR.value}:
            assert "dhcp:write" in row.permissions
            assert "dns:write" in row.permissions
        if row.name == RoleName.READ_ONLY.value:
            assert "dhcp:read" in row.permissions
            assert "dns:read" in row.permissions
            assert "dhcp:write" not in row.permissions
    await db_session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_sync_system_roles_repairs_stale_rows_only(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    await TenantService(db_session, tenant.id)._seed_roles(tenant.id)
    await db_session.flush()

    stale = (
        (await db_session.execute(select(Role).where(Role.tenant_id == tenant.id, Role.name == "Admin")))
        .scalars()
        .first()
    )
    assert stale is not None
    stale.permissions = ["device:read", "device:write"]
    custom = Role(
        tenant_id=tenant.id,
        name="Custom",
        description="Hand-written role",
        is_system=False,
        permissions=["device:read"],
    )
    db_session.add(custom)
    await db_session.flush()

    updated = await RoleService(db_session, None).sync_system_roles()
    await db_session.flush()

    assert updated >= 1
    await db_session.refresh(stale)
    await db_session.refresh(custom)
    assert stale.permissions == permissions_for(RoleName.ADMIN)
    assert custom.permissions == ["device:read"]
    await db_session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_sync_system_roles_is_idempotent(db_session: AsyncSession) -> None:
    tenant = await _tenant(db_session)
    await TenantService(db_session, tenant.id)._seed_roles(tenant.id)
    await db_session.flush()

    service = RoleService(db_session, None)
    assert await service.sync_system_roles() == 0
    assert await service.sync_system_roles() == 0
    await db_session.commit()
