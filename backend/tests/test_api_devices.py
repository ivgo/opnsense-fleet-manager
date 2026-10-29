"""Device registry, heartbeat and command round-trip integration tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.enums import RoleName
from tests.conftest import AccountFactory, TenantFactory


async def _admin_headers(client: AsyncClient, tenant, account) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_device_crud(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _admin_headers(client, tenant, account)

    created = await client.post(
        "/api/v1/devices",
        headers=headers,
        json={"name": "fw-branch-01", "hostname": "fw-branch-01.example.test", "ip_address": "192.0.2.10"},
    )
    assert created.status_code == 201, created.text
    device = created.json()
    assert device["name"] == "fw-branch-01"
    assert device["status"] == "registered"

    fetched = await client.get(f"/api/v1/devices/{device['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["hostname"] == "fw-branch-01.example.test"

    listed = await client.get("/api/v1/devices", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1
    assert listed.json()["meta"]["pages"] == 1
    assert listed.json()["items"][0]["id"] == device["id"]

    summary = await client.get("/api/v1/devices/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["total"] == 1

    updated = await client.patch(
        f"/api/v1/devices/{device['id']}",
        headers=headers,
        json={"description": "Branch firewall"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Branch firewall"


@pytest.mark.asyncio(loop_scope="session")
async def test_duplicate_device_name_conflicts(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _admin_headers(client, tenant, account)

    payload = {"name": "fw-dup"}
    first = await client.post("/api/v1/devices", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    second = await client.post("/api/v1/devices", headers=headers, json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio(loop_scope="session")
async def test_command_dispatch_and_heartbeat_result_roundtrip(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _admin_headers(client, tenant, account)

    device = (await client.post("/api/v1/devices", headers=headers, json={"name": "fw-cmd"})).json()

    dispatched = await client.post(
        f"/api/v1/devices/{device['id']}/commands",
        headers=headers,
        json={"action": "ping", "payload": {}},
    )
    assert dispatched.status_code == 201, dispatched.text
    command = dispatched.json()
    assert command["action"] == "ping"
    assert command["pending_count"] == 1

    pending = await client.get(f"/api/v1/devices/{device['id']}/commands", headers=headers)
    assert pending.status_code == 200
    assert pending.json()["pending_count"] == 1
    assert pending.json()["pending"][0]["id"] == command["id"]

    heartbeat = await client.post(
        f"/api/v1/devices/{device['id']}/heartbeat",
        headers=headers,
        json={
            "firmware_version": "24.7.11",
            "command_results": [
                {
                    "id": command["id"],
                    "action": "ping",
                    "status": "ok",
                    "message": "pong",
                    "output": {"agent_version": "1.0.0"},
                    "duration_ms": 8,
                }
            ],
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["command_results_accepted"] == 1
    assert heartbeat.json()["commands"] == []

    after = await client.get(f"/api/v1/devices/{device['id']}/commands", headers=headers)
    assert after.status_code == 200
    body = after.json()
    assert body["pending_count"] == 0
    assert len(body["history"]) == 1
    assert body["history"][0]["status"] == "ok"
    assert body["last_result_at"]


@pytest.mark.asyncio(loop_scope="session")
async def test_command_whitelist_and_payload_limits(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _admin_headers(client, tenant, account)
    device = (await client.post("/api/v1/devices", headers=headers, json={"name": "fw-cmd-2"})).json()

    unknown = await client.post(
        f"/api/v1/devices/{device['id']}/commands",
        headers=headers,
        json={"action": "shell", "payload": {}},
    )
    assert unknown.status_code == 422

    oversized = await client.post(
        f"/api/v1/devices/{device['id']}/commands",
        headers=headers,
        json={"action": "ping", "payload": {"blob": "x" * 9000}},
    )
    assert oversized.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_read_only_user_cannot_dispatch_commands(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)
    viewer = await account_factory(tenant, role=RoleName.READ_ONLY)
    admin_headers = await _admin_headers(client, tenant, admin)
    viewer_headers = await _admin_headers(client, tenant, viewer)

    device = (await client.post("/api/v1/devices", headers=admin_headers, json={"name": "fw-ro"})).json()

    forbidden = await client.post(
        f"/api/v1/devices/{device['id']}/commands",
        headers=viewer_headers,
        json={"action": "ping", "payload": {}},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "permission_denied"

    readable = await client.get(f"/api/v1/devices/{device['id']}/commands", headers=viewer_headers)
    assert readable.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_pending_command_limit(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _admin_headers(client, tenant, account)
    device = (await client.post("/api/v1/devices", headers=headers, json={"name": "fw-limit"})).json()

    for _ in range(50):
        response = await client.post(
            f"/api/v1/devices/{device['id']}/commands",
            headers=headers,
            json={"action": "noop", "payload": {}},
        )
        assert response.status_code == 201, response.text

    overflow = await client.post(
        f"/api/v1/devices/{device['id']}/commands",
        headers=headers,
        json={"action": "noop", "payload": {}},
    )
    assert overflow.status_code == 400
    assert "50" in overflow.json()["error"]["message"]
