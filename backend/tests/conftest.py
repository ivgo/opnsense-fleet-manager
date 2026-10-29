"""Shared fixtures for the OFME backend test suite.

The suite has two layers:

* pure unit tests that need no infrastructure (security, RBAC, schemas, PKI,
  command result merging);
* integration tests that exercise the FastAPI application against a real
  PostgreSQL database. Those fixtures skip the test when the database is not
  reachable, so ``pytest`` stays useful on a workstation without Docker.

Point the suite at a disposable database with ``TEST_DATABASE_URL``. The
default matches ``docker-compose.test.yml`` (port 55432).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ofme:ofme@127.0.0.1:55432/ofme_test",
)

# The application reads configuration at import time, so every override must be
# in place before the first ``app.*`` import below.
os.environ["ENVIRONMENT"] = "testing"
os.environ["DEBUG"] = "false"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SECRET_KEY"] = "test-only-secret-key-0123456789abcdef0123456789"
os.environ["ENABLE_DOCS"] = "true"
os.environ["LOG_JSON"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = ""
os.environ["ENABLE_MFA"] = "true"
os.environ["S3_ENDPOINT"] = "http://127.0.0.1:9"
os.environ["OTEL_ENABLED"] = "false"
# Rate limiting is exercised explicitly by ``test_rate_limit.py``; every other
# test must not share a request budget with its neighbours.
os.environ["RATE_LIMIT_ENABLED"] = "false"

_PKI_DIR = Path(mkdtemp(prefix="ofme-pki-test-"))
os.environ["PKI_CA_CERT_PATH"] = str(_PKI_DIR / "ca.crt")
os.environ["PKI_CA_KEY_PATH"] = str(_PKI_DIR / "ca.key")
os.environ["PKI_KEY_SIZE"] = "2048"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 - registers every table on Base.metadata
from app.core.security import hash_password
from app.cqrs.commands import register_handlers
from app.cqrs.bus import command_bus
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models.enums import RoleName
from app.models.identity import Role, Tenant, User
from app.rbac.permissions import ROLE_MATRIX

TEST_PASSWORD = "Correct-Horse-9-Battery!"


@dataclass(slots=True)
class Account:
    tenant: Tenant
    user: User
    password: str
    role: RoleName


async def _truncate(engine: AsyncEngine) -> None:
    names = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
    if not names:
        return
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    database_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, future=True)
    try:
        async with database_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001 - any connection failure means "no database"
        await database_engine.dispose()
        pytest.skip(f"PostgreSQL test database is unavailable at {TEST_DATABASE_URL}: {exc}")
    try:
        yield database_engine
    finally:
        async with database_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await database_engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def clean_database(engine: AsyncEngine) -> AsyncIterator[None]:
    await _truncate(engine)
    yield


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession], clean_database: None
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    clean_database: None,
) -> AsyncIterator[AsyncClient]:
    if command_bus.registry.size == 0:
        register_handlers()

    application = create_app()

    async def _session_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
    application.dependency_overrides.clear()


TenantFactory = Callable[..., Coroutine[Any, Any, Tenant]]
AccountFactory = Callable[..., Coroutine[Any, Any, Account]]


@pytest_asyncio.fixture
async def tenant_factory(session_factory: async_sessionmaker[AsyncSession]) -> TenantFactory:
    async def _create(name: str = "Acme Networks", slug: str | None = None) -> Tenant:
        async with session_factory() as session:
            tenant = Tenant(name=name, slug=slug or f"tenant-{uuid.uuid4().hex[:10]}")
            session.add(tenant)
            await session.commit()
            await session.refresh(tenant)
            return tenant

    return _create


@pytest_asyncio.fixture
async def account_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> AccountFactory:
    async def _create(
        tenant: Tenant,
        *,
        role: RoleName = RoleName.ADMIN,
        username: str | None = None,
        password: str = TEST_PASSWORD,
        is_superadmin: bool = False,
        unbound: bool = False,
    ) -> Account:
        async with session_factory() as session:
            account_tenant_id = None if unbound else tenant.id
            role_row = (
                (
                    await session.execute(
                        select(Role).where(Role.tenant_id == account_tenant_id, Role.name == role.value)
                    )
                )
                .scalars()
                .first()
            )
            if role_row is None:
                role_row = Role(
                    tenant_id=account_tenant_id,
                    name=role.value,
                    description=f"System role {role.value}",
                    is_system=True,
                    permissions=sorted(permission.value for permission in ROLE_MATRIX[role]),
                )
                session.add(role_row)
                await session.flush()

            suffix = uuid.uuid4().hex[:8]
            user = User(
                tenant_id=account_tenant_id,
                username=username or f"user-{suffix}",
                email=f"{username or 'user'}-{suffix}@example.com",
                full_name="Test User",
                password_hash=hash_password(password),
                is_superadmin=is_superadmin,
            )
            if not is_superadmin:
                user.roles.append(role_row)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return Account(tenant=tenant, user=user, password=password, role=role)

    return _create


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, account_factory: AccountFactory, tenant_factory: TenantFactory):
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)

    async def _login(
        *,
        username: str | None = None,
        password: str | None = None,
        tenant_slug: str | None = None,
        account_override: Account | None = None,
    ) -> dict[str, str]:
        selected = account_override or account
        payload: dict[str, Any] = {
            "username": username or selected.user.username,
            "password": password or selected.password,
        }
        if tenant_slug:
            payload["tenant"] = tenant_slug
        response = await client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    _login.account = account  # type: ignore[attr-defined]
    _login.tenant = tenant  # type: ignore[attr-defined]
    return _login
