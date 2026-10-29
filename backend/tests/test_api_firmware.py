"""Firmware lifecycle endpoints: status probe, upgrade and reboot.

The OPNsense REST client is replaced by a deterministic fake, so the tests cover
routing, permissions, the audit entry and the service response mapping without a
real appliance.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.audit import AuditLog
from app.models.enums import RoleName
from tests.conftest import Account, AccountFactory, TenantFactory


class FakeOpnsenseClient:
    def __init__(self, firmware: dict[str, Any] | None, info: dict[str, Any] | None) -> None:
        self.firmware = firmware
        self.info = info
        self.calls: list[tuple[str, Any]] = []

    async def __aenter__(self) -> FakeOpnsenseClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def firmware_status(self) -> dict[str, Any] | None:
        return self.firmware

    async def firmware_info(self) -> dict[str, Any] | None:
        return self.info

    async def upgrade_firmware(self, package: str | None = None) -> dict[str, Any]:
        self.calls.append(("upgrade", package))
        return {"status": "ok", "msg_uuid": "abc"}

    async def reboot(self) -> dict[str, Any]:
        self.calls.append(("reboot", None))
        return {"status": "ok"}


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeOpnsenseClient:
    fake = FakeOpnsenseClient(
        firmware={
            "product_version": "25.1.2",
            "product": {"name": "OPNsense", "series": "25.1", "product_version": "25.1.2"},
        },
        info={"latest": "25.1.2", "upgrade_available": False},
    )

    def _client_for(*args: Any, **kwargs: Any) -> FakeOpnsenseClient:
        return fake

    monkeypatch.setattr("app.integrations.opnsense.client.client_for", _client_for)
    return fake


async def _login(client: AsyncClient, account: Account) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _device_with_credentials(
    client: AsyncClient, headers: dict[str, str], name: str = "fw-firmware"
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/devices",
        headers=headers,
        json={
            "name": name,
            "ip_address": "192.0.2.40",
            "api_key": "device-key",
            "api_secret": "device-secret",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio(loop_scope="session")
async def test_firmware_status_is_readable_by_read_only_roles(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_client: FakeOpnsenseClient,
) -> None:
    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _login(client, admin)
    device = await _device_with_credentials(client, headers)

    reader = await account_factory(tenant, role=RoleName.READ_ONLY)
    reader_headers = await _login(client, reader)

    response = await client.get(f"/api/v1/devices/{device['id']}/firmware/status", headers=reader_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["product_version"] == "25.1.2"
    assert body["product_name"] == "OPNsense"
    assert body["latest_release"] == "25.1.2"
    assert body["needs_upgrade"] is False
    assert body["upgrade_available"] is False

    fake_client.info = {"latest": "25.7", "upgrade_available": True}
    refreshed = await client.get(f"/api/v1/devices/{device['id']}/firmware/status", headers=reader_headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["needs_upgrade"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_firmware_status_reports_missing_credentials(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _login(client, admin)
    device = (await client.post("/api/v1/devices", headers=headers, json={"name": "fw-no-creds"})).json()

    response = await client.get(f"/api/v1/devices/{device['id']}/firmware/status", headers=headers)
    assert response.status_code == 400
    assert "no OPNsense API credentials" in response.json()["error"]["message"]


@pytest.mark.asyncio(loop_scope="session")
async def test_upgrade_requires_the_firmware_permission(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_client: FakeOpnsenseClient,
) -> None:
    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _login(client, admin)
    device = await _device_with_credentials(client, headers, "fw-firmware-ro")

    readonly = await account_factory(tenant, role=RoleName.READ_ONLY)
    readonly_headers = await _login(client, readonly)

    denied = await client.post(
        f"/api/v1/devices/{device['id']}/firmware/upgrade",
        headers=readonly_headers,
        json={},
    )
    assert denied.status_code == 403
    assert fake_client.calls == []


@pytest.mark.asyncio(loop_scope="session")
async def test_upgrade_and_reboot_are_audited(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_client: FakeOpnsenseClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant = await tenant_factory()
    operator = await account_factory(tenant, role=RoleName.OPERATOR)
    headers = await _login(client, operator)
    device = await _device_with_credentials(client, headers, "fw-firmware-op")

    upgraded = await client.post(
        f"/api/v1/devices/{device['id']}/firmware/upgrade",
        headers=headers,
        json={"package": "OPNsense-25.7"},
    )
    assert upgraded.status_code == 202, upgraded.text
    body = upgraded.json()
    assert body["status"] == "initiated"
    assert body["package"] == "OPNsense-25.7"
    assert fake_client.calls[-1] == ("upgrade", "OPNsense-25.7")

    rebooted = await client.post(f"/api/v1/devices/{device['id']}/firmware/reboot", headers=headers)
    assert rebooted.status_code == 202, rebooted.text
    assert fake_client.calls[-1] == ("reboot", None)

    async with session_factory() as session:
        actions = (
            (
                await session.execute(
                    select(AuditLog.action).where(AuditLog.tenant_id == tenant.id).order_by(AuditLog.id)
                )
            )
            .scalars()
            .all()
        )
    assert "firmware.upgrade" in actions
    assert "firmware.reboot" in actions


@pytest.mark.asyncio(loop_scope="session")
async def test_upgrade_without_package_or_known_version_is_rejected(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_client: FakeOpnsenseClient,
) -> None:
    tenant = await tenant_factory()
    operator = await account_factory(tenant, role=RoleName.OPERATOR)
    headers = await _login(client, operator)
    device = await _device_with_credentials(client, headers, "fw-firmware-unknown")

    response = await client.post(f"/api/v1/devices/{device['id']}/firmware/upgrade", headers=headers, json={})
    assert response.status_code == 400
    assert "no package given" in response.json()["error"]["message"]
    assert fake_client.calls == []
