"""DHCP and DNS management integration tests."""

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


async def _device(client: AsyncClient, headers: dict[str, str], name: str = "fw-dhcp") -> dict:
    response = await client.post("/api/v1/devices", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _scope_payload(device_id: str, **overrides) -> dict:
    payload = {
        "device_id": device_id,
        "name": "LAN",
        "description": "Branch LAN",
        "subnet": "192.0.2.0/24",
        "pool_start": "192.0.2.100",
        "pool_end": "192.0.2.200",
        "gateway": "192.0.2.1",
        "dns_servers": ["192.0.2.1", "1.1.1.1"],
        "domain_name": "branch.example.com",
        "lease_time_seconds": 86400,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio(loop_scope="session")
async def test_dhcp_scope_and_reservation_lifecycle(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _login(client, account)
    device = await _device(client, headers)

    created = await client.post("/api/v1/dhcp/scopes", headers=headers, json=_scope_payload(device["id"]))
    assert created.status_code == 201, created.text
    scope = created.json()
    assert scope["subnet"] == "192.0.2.0/24"
    assert scope["dns_servers"] == ["192.0.2.1", "1.1.1.1"]
    assert scope["lease_time_seconds"] == 86400

    listed = await client.get("/api/v1/dhcp/scopes", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1

    updated = await client.patch(
        f"/api/v1/dhcp/scopes/{scope['id']}",
        headers=headers,
        json={"pool_end": "192.0.2.210", "lease_time_seconds": 3600, "enabled": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["pool_end"] == "192.0.2.210"
    assert updated.json()["lease_time_seconds"] == 3600
    assert updated.json()["enabled"] is False

    reservation = await client.post(
        "/api/v1/dhcp/reservations",
        headers=headers,
        json={
            "scope_id": scope["id"],
            "hostname": "printer-01",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "ip_address": "192.0.2.50",
        },
    )
    assert reservation.status_code == 201, reservation.text
    row = reservation.json()
    assert row["mac_address"] == "aa:bb:cc:dd:ee:ff"
    assert row["device_id"] == device["id"]

    duplicate_mac = await client.post(
        "/api/v1/dhcp/reservations",
        headers=headers,
        json={
            "scope_id": scope["id"],
            "hostname": "printer-02",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "ip_address": "192.0.2.51",
        },
    )
    assert duplicate_mac.status_code == 409, duplicate_mac.text

    duplicate_ip = await client.post(
        "/api/v1/dhcp/reservations",
        headers=headers,
        json={
            "scope_id": scope["id"],
            "hostname": "printer-03",
            "mac_address": "aa:bb:cc:dd:ee:01",
            "ip_address": "192.0.2.50",
        },
    )
    assert duplicate_ip.status_code == 409, duplicate_ip.text

    fetched = await client.get(f"/api/v1/dhcp/reservations/{row['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["hostname"] == "printer-01"

    moved = await client.patch(
        f"/api/v1/dhcp/reservations/{row['id']}",
        headers=headers,
        json={"ip_address": "192.0.2.60", "description": "Floor 2"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["ip_address"] == "192.0.2.60"

    deleted = await client.delete(f"/api/v1/dhcp/scopes/{scope['id']}", headers=headers)
    assert deleted.status_code == 200
    assert "1 reservation" in deleted.json()["message"]

    missing = await client.get(f"/api/v1/dhcp/scopes/{scope['id']}", headers=headers)
    assert missing.status_code == 404
    missing_reservation = await client.get(f"/api/v1/dhcp/reservations/{row['id']}", headers=headers)
    assert missing_reservation.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_dhcp_validation_rejects_invalid_pools(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _login(client, account)
    device = await _device(client, headers)

    cases = [
        {"pool_start": "10.0.0.10", "pool_end": "10.0.0.20"},
        {"pool_start": "192.0.2.200", "pool_end": "192.0.2.100"},
        {"pool_start": "192.0.2.1", "pool_end": "192.0.2.20"},
        {"dns_servers": ["not-an-ip"]},
        {"subnet": "192.0.2.0/31"},
        {"domain_name": "bad domain!"},
    ]
    for index, overrides in enumerate(cases):
        response = await client.post(
            "/api/v1/dhcp/scopes",
            headers=headers,
            json=_scope_payload(device["id"], name=f"scope-{index}", **overrides),
        )
        assert response.status_code == 400, (overrides, response.text)
        assert response.json()["error"]["code"] == "bad_request"

    scope = (
        await client.post("/api/v1/dhcp/scopes", headers=headers, json=_scope_payload(device["id"]))
    ).json()

    outside = await client.post(
        "/api/v1/dhcp/reservations",
        headers=headers,
        json={
            "scope_id": scope["id"],
            "hostname": "rogue",
            "mac_address": "aa:bb:cc:dd:ee:02",
            "ip_address": "198.51.100.10",
        },
    )
    assert outside.status_code == 400

    bad_mac = await client.post(
        "/api/v1/dhcp/reservations",
        headers=headers,
        json={
            "scope_id": scope["id"],
            "hostname": "rogue",
            "mac_address": "zz:zz:zz:zz:zz:zz",
            "ip_address": "192.0.2.40",
        },
    )
    assert bad_mac.status_code == 400

    gateway = await client.post(
        "/api/v1/dhcp/reservations",
        headers=headers,
        json={
            "scope_id": scope["id"],
            "hostname": "gateway",
            "mac_address": "aa:bb:cc:dd:ee:03",
            "ip_address": "192.0.2.1",
        },
    )
    assert gateway.status_code == 400

    duplicate_scope = await client.post(
        "/api/v1/dhcp/scopes",
        headers=headers,
        json=_scope_payload(device["id"], name="LAN-copy"),
    )
    assert duplicate_scope.status_code == 409


@pytest.mark.asyncio(loop_scope="session")
async def test_dns_record_types_and_conflicts(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _login(client, account)
    device = await _device(client, headers, name="fw-dns")

    records = [
        {"name": "www", "record_type": "A", "value": "192.0.2.10", "ttl": 300},
        {"name": "www", "record_type": "AAAA", "value": "2001:db8::10"},
        {"name": "alias", "record_type": "CNAME", "value": "www.example.com"},
        {"name": "example.com", "record_type": "MX", "value": "mail.example.com", "priority": 10},
        {
            "name": "_sip._tcp.example.com",
            "record_type": "SRV",
            "value": "sip.example.com",
            "priority": 10,
            "weight": 5,
            "port": 5060,
        },
        {"name": "example.com", "record_type": "TXT", "value": "v=spf1 -all"},
        {"name": "10.0.0.1.in-addr.arpa", "record_type": "PTR", "value": "host.example.com"},
        {"name": "example.com", "record_type": "NS", "value": "ns1.example.com"},
    ]
    created: list[dict] = []
    for payload in records:
        response = await client.post(
            "/api/v1/dns/records",
            headers=headers,
            json={"device_id": device["id"], **payload},
        )
        assert response.status_code == 201, (payload, response.text)
        created.append(response.json())

    assert created[0]["name"] == "www"
    assert created[1]["record_type"] == "AAAA"
    assert created[3]["priority"] == 10
    assert created[4]["port"] == 5060

    listed = await client.get("/api/v1/dns/records", headers=headers, params={"record_type": "A"})
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1

    duplicate = await client.post(
        "/api/v1/dns/records",
        headers=headers,
        json={"device_id": device["id"], "name": "WWW.", "record_type": "A", "value": "192.0.2.10"},
    )
    assert duplicate.status_code == 409, duplicate.text

    cname_conflict = await client.post(
        "/api/v1/dns/records",
        headers=headers,
        json={"device_id": device["id"], "name": "alias", "record_type": "A", "value": "192.0.2.11"},
    )
    assert cname_conflict.status_code == 409, cname_conflict.text

    invalid_a = await client.post(
        "/api/v1/dns/records",
        headers=headers,
        json={"device_id": device["id"], "name": "bad", "record_type": "A", "value": "999.1.1.1"},
    )
    assert invalid_a.status_code == 400

    mx_without_priority = await client.post(
        "/api/v1/dns/records",
        headers=headers,
        json={
            "device_id": device["id"],
            "name": "mx",
            "record_type": "MX",
            "value": "mail.example.com",
        },
    )
    assert mx_without_priority.status_code == 400

    srv_without_port = await client.post(
        "/api/v1/dns/records",
        headers=headers,
        json={
            "device_id": device["id"],
            "name": "_sip._tcp",
            "record_type": "SRV",
            "value": "sip.example.com",
            "priority": 1,
            "weight": 1,
        },
    )
    assert srv_without_port.status_code == 400

    updated = await client.patch(
        f"/api/v1/dns/records/{created[0]['id']}",
        headers=headers,
        json={"value": "192.0.2.20", "ttl": 60},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["value"] == "192.0.2.20"
    assert updated.json()["ttl"] == 60

    removed = await client.delete(f"/api/v1/dns/records/{created[0]['id']}", headers=headers)
    assert removed.status_code == 200
    assert (await client.get(f"/api/v1/dns/records/{created[0]['id']}", headers=headers)).status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_networking_is_tenant_isolated_and_rbac_guarded(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant_a = await tenant_factory(name="Tenant A")
    tenant_b = await tenant_factory(name="Tenant B")
    admin_a = await account_factory(tenant_a, role=RoleName.ADMIN)
    admin_b = await account_factory(tenant_b, role=RoleName.ADMIN)
    readonly = await account_factory(tenant_a, role=RoleName.READ_ONLY)
    headers_a = await _login(client, admin_a)
    headers_b = await _login(client, admin_b)
    readonly_headers = await _login(client, readonly)

    device = await _device(client, headers_a)
    scope = (
        await client.post("/api/v1/dhcp/scopes", headers=headers_a, json=_scope_payload(device["id"]))
    ).json()

    foreign_list = await client.get("/api/v1/dhcp/scopes", headers=headers_b)
    assert foreign_list.status_code == 200
    assert foreign_list.json()["meta"]["total"] == 0

    foreign_get = await client.get(f"/api/v1/dhcp/scopes/{scope['id']}", headers=headers_b)
    assert foreign_get.status_code == 404

    denied_scope = await client.post(
        "/api/v1/dhcp/scopes", headers=readonly_headers, json=_scope_payload(device["id"])
    )
    assert denied_scope.status_code == 403

    denied_dns = await client.post(
        "/api/v1/dns/records",
        headers=readonly_headers,
        json={"device_id": device["id"], "name": "www", "record_type": "A", "value": "192.0.2.5"},
    )
    assert denied_dns.status_code == 403

    can_read = await client.get("/api/v1/dhcp/scopes", headers=readonly_headers)
    assert can_read.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_dhcp_dns_mutations_are_audited(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)
    auditor = await account_factory(tenant, role=RoleName.AUDITOR)
    admin_headers = await _login(client, admin)
    auditor_headers = await _login(client, auditor)
    device = await _device(client, admin_headers)

    scope = (
        await client.post("/api/v1/dhcp/scopes", headers=admin_headers, json=_scope_payload(device["id"]))
    ).json()
    await client.post(
        "/api/v1/dns/records",
        headers=admin_headers,
        json={"device_id": device["id"], "name": "www", "record_type": "A", "value": "192.0.2.10"},
    )

    scopes = await client.get(
        "/api/v1/audit",
        headers=auditor_headers,
        params={"action": "dhcp.scope.created", "resource_id": scope["id"]},
    )
    assert scopes.status_code == 200, scopes.text
    assert scopes.json()["meta"]["total"] == 1
    entry = scopes.json()["items"][0]
    assert entry["resource_type"] == "DhcpScope"
    assert entry["after"]["subnet"] == "192.0.2.0/24"

    dns = await client.get(
        "/api/v1/audit",
        headers=auditor_headers,
        params={"action": "dns.record.created", "resource_type": "DnsRecord"},
    )
    assert dns.status_code == 200, dns.text
    assert dns.json()["meta"]["total"] == 1
