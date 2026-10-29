"""Platform bootstrap regression tests.

The API seeds the default tenant, the role/permission catalogue and a SuperAdmin
account during startup. These tests pin two properties that the live container
run depends on:

* the bootstrap works on an empty database without triggering lazy-load IO
  (asyncpg raises ``MissingGreenlet`` when a relationship is loaded implicitly);
* running it again is idempotent and keeps the SuperAdmin role attached.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.security import verify_password
from app.models.enums import RoleName
from app.models.identity import User
from app.services.identity import SystemBootstrapService

ADMIN_EMAIL = "admin@ofme.test"
ADMIN_PASSWORD = "Correct-Horse-9-Battery!"
TENANT_SLUG = "default"


async def _run_bootstrap(session_factory: async_sessionmaker[AsyncSession]) -> dict:
    async with session_factory() as session:
        return await SystemBootstrapService(session).run(
            admin_email=ADMIN_EMAIL,
            admin_password=ADMIN_PASSWORD,
            tenant_slug=TENANT_SLUG,
            tenant_name="Default Tenant",
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_bootstrap_is_idempotent_and_grants_superadmin(
    session_factory: async_sessionmaker[AsyncSession], clean_database: None
) -> None:
    first = await _run_bootstrap(session_factory)
    assert first["admin_created"] is True
    assert first["password_set"] is True

    second = await _run_bootstrap(session_factory)
    assert second["admin_created"] is False
    assert second["admin_id"] == first["admin_id"]
    assert second["tenant_slug"] == TENANT_SLUG

    async with session_factory() as session:
        admin = (
            (
                await session.execute(
                    select(User)
                    .options(selectinload(User.roles))
                    .where(User.id == uuid.UUID(first["admin_id"]))
                )
            )
            .scalars()
            .one()
        )

    assert admin.email == ADMIN_EMAIL
    assert admin.is_superadmin is True
    assert admin.password_hash is not None
    assert verify_password(ADMIN_PASSWORD, admin.password_hash) is True
    assert [role.name for role in admin.roles] == [RoleName.SUPER_ADMIN.value]


@pytest.mark.asyncio(loop_scope="session")
async def test_bootstrap_rejects_special_use_admin_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """`CurrentUser.email` is an ``EmailStr``; `.local` addresses must fail early."""
    from app.core.config import settings
    from app.seeds.bootstrap import bootstrap_if_configured

    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_EMAIL", "admin@ofme.local")

    assert await bootstrap_if_configured() is None
