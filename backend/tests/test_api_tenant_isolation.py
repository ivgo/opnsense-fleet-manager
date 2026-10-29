"""Multi-tenancy isolation tests.

A tenant-bound principal must never reach another tenant, and a SuperAdmin must
always state the target tenant explicitly.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.enums import RoleName
from tests.conftest import AccountFactory, TenantFactory


async def _login(client: AsyncClient, account) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_tenant_user_cannot_cross_tenant_header(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant_a = await tenant_factory(name="Tenant A")
    tenant_b = await tenant_factory(name="Tenant B")
    user_a = await account_factory(tenant_a, role=RoleName.ADMIN)
    headers = await _login(client, user_a)

    own = await client.get("/api/v1/devices", headers=headers)
    assert own.status_code == 200

    crossed = await client.get("/api/v1/devices", headers={**headers, "X-Tenant-Id": str(tenant_b.id)})
    assert crossed.status_code == 403
    assert crossed.json()["error"]["code"] == "tenant_isolation_violation"


@pytest.mark.asyncio(loop_scope="session")
async def test_tenant_user_cannot_read_foreign_device(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant_a = await tenant_factory()
    tenant_b = await tenant_factory()
    user_a = await account_factory(tenant_a, role=RoleName.ADMIN)
    user_b = await account_factory(tenant_b, role=RoleName.ADMIN)
    headers_a = await _login(client, user_a)
    headers_b = await _login(client, user_b)

    device = (await client.post("/api/v1/devices", headers=headers_b, json={"name": "fw-tenant-b"})).json()

    stolen = await client.get(f"/api/v1/devices/{device['id']}", headers=headers_a)
    assert stolen.status_code == 403
    assert stolen.json()["error"]["code"] == "tenant_isolation_violation"


@pytest.mark.asyncio(loop_scope="session")
async def test_superadmin_must_specify_tenant(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    superadmin = await account_factory(tenant, is_superadmin=True, unbound=True)
    headers = await _login(client, superadmin)

    missing = await client.get("/api/v1/devices", headers=headers)
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "tenant_isolation_violation"

    explicit = await client.get("/api/v1/devices", headers={**headers, "X-Tenant-Id": str(tenant.id)})
    assert explicit.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_superadmin_unknown_tenant_is_rejected(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    import uuid

    tenant = await tenant_factory()
    superadmin = await account_factory(tenant, is_superadmin=True, unbound=True)
    headers = await _login(client, superadmin)

    response = await client.get("/api/v1/devices", headers={**headers, "X-Tenant-Id": str(uuid.uuid4())})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "tenant_isolation_violation"
