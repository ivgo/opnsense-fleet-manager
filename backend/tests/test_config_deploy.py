"""Idempotency tests for the desired-state deployers.

The tests need no PostgreSQL and no appliance: the device, repository, audit and
session layers are replaced with in-memory fakes, and the OPNsense client is a
fake that mirrors the REST surface the deployers use. Every scenario asserts
that the first apply writes the desired objects, the second apply is a no-op,
and objects carrying the ``OFME-`` marker are pruned when they disappear from
the desired state.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

import app.services.configuration as config_module
from app.models.config import DhcpReservation, DhcpScope, DnsRecord, FirewallRule, NatRule, VlanConfig
from app.models.enums import DnsRecordType, NatType, RuleAction, RuleDirection
from app.services.configuration import ConfigurationDeployer, nat_payload

DEVICE_ID = uuid.uuid4()


# --------------------------------------------------------------------------- fakes
class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeAudit:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class FakeDevices:
    async def get(self, device_id: uuid.UUID) -> Any:
        return type("Device", (), {"id": device_id, "name": "fw-test"})()

    async def credentials(self, device: Any) -> tuple[str, str, str]:
        return "https://fw.test", "key", "secret"


class FakeRepo:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    async def for_device(self, device_id: uuid.UUID) -> list[Any]:
        return list(self.rows)

    async def for_scope(self, scope_id: uuid.UUID) -> list[Any]:
        return [row for row in self.rows if row.scope_id == scope_id]


class FakeUow:
    def __init__(
        self,
        *,
        rules: list[Any] | None = None,
        nat: list[Any] | None = None,
        vlans: list[Any] | None = None,
        scopes: list[Any] | None = None,
        reservations: list[Any] | None = None,
        records: list[Any] | None = None,
    ) -> None:
        self.rules = FakeRepo(rules or [])
        self.nat = FakeRepo(nat or [])
        self.vlans = FakeRepo(vlans or [])
        self.dhcp_scopes = FakeRepo(scopes or [])
        self.dhcp_reservations = FakeRepo(reservations or [])
        self.dns_records = FakeRepo(records or [])


class FakeOpnsense:
    """In-memory stand-in for the OPNsense REST client."""

    def __init__(self) -> None:
        self.rules: list[dict[str, Any]] = []
        self.nat: dict[str, list[dict[str, Any]]] = {
            "d_nat": [],
            "source_nat": [],
            "one_to_one": [],
        }
        self.vlans: list[dict[str, Any]] = []
        self.subnets: list[dict[str, Any]] = []
        self.reservations: list[dict[str, Any]] = []
        self.overrides: list[dict[str, Any]] = []
        self.aliases: list[dict[str, Any]] = []
        self.applied: list[str] = []

    @staticmethod
    def _add(store: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
        row = {"uuid": str(uuid.uuid4()), **payload}
        store.append(row)
        return row

    @staticmethod
    def _set(store: list[dict[str, Any]], uuid_value: str, payload: dict[str, Any]) -> None:
        for row in store:
            if row["uuid"] == uuid_value:
                row.update(payload)
                return
        raise AssertionError(f"object {uuid_value} not found")

    @staticmethod
    def _delete(store: list[dict[str, Any]], uuid_value: str) -> None:
        store[:] = [row for row in store if row["uuid"] != uuid_value]

    async def __aenter__(self) -> FakeOpnsense:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    # rules
    async def search_rules(self) -> dict[str, Any]:
        return {"rows": self.rules}

    async def add_rule(self, rule: dict[str, Any]) -> dict[str, Any]:
        return self._add(self.rules, rule)

    async def set_rule(self, uuid_value: str, rule: dict[str, Any]) -> dict[str, Any]:
        self._set(self.rules, uuid_value, rule)
        return {}

    async def delete_rule(self, uuid_value: str) -> dict[str, Any]:
        self._delete(self.rules, uuid_value)
        return {}

    async def apply_rules(self) -> dict[str, Any]:
        self.applied.append("rules")
        return {}

    # NAT
    async def search_nat(self, kind: str) -> dict[str, Any]:
        return {"rows": self.nat[kind]}

    async def add_nat_rule(self, kind: str, rule: dict[str, Any]) -> dict[str, Any]:
        return self._add(self.nat[kind], rule)

    async def set_nat_rule(self, kind: str, uuid_value: str, rule: dict[str, Any]) -> dict[str, Any]:
        self._set(self.nat[kind], uuid_value, rule)
        return {}

    async def delete_nat_rule(self, kind: str, uuid_value: str) -> dict[str, Any]:
        self._delete(self.nat[kind], uuid_value)
        return {}

    async def apply_nat(self, kind: str) -> dict[str, Any]:
        self.applied.append(f"nat:{kind}")
        return {}

    # VLAN
    async def search_vlans(self) -> dict[str, Any]:
        return {"rows": self.vlans}

    async def add_vlan(self, vlan: dict[str, Any]) -> dict[str, Any]:
        return self._add(self.vlans, vlan)

    async def set_vlan(self, uuid_value: str, vlan: dict[str, Any]) -> dict[str, Any]:
        self._set(self.vlans, uuid_value, vlan)
        return {}

    async def delete_vlan(self, uuid_value: str) -> dict[str, Any]:
        self._delete(self.vlans, uuid_value)
        return {}

    async def apply_interfaces(self) -> dict[str, Any]:
        self.applied.append("vlans")
        return {}

    # DHCP
    async def search_kea_subnets(self) -> dict[str, Any]:
        return {"rows": self.subnets}

    async def add_kea_subnet(self, subnet: dict[str, Any]) -> dict[str, Any]:
        return self._add(self.subnets, subnet)

    async def set_kea_subnet(self, uuid_value: str, subnet: dict[str, Any]) -> dict[str, Any]:
        self._set(self.subnets, uuid_value, subnet)
        return {}

    async def delete_kea_subnet(self, uuid_value: str) -> dict[str, Any]:
        self._delete(self.subnets, uuid_value)
        return {}

    async def search_kea_reservations(self) -> dict[str, Any]:
        return {"rows": self.reservations}

    async def add_kea_reservation(self, reservation: dict[str, Any]) -> dict[str, Any]:
        return self._add(self.reservations, reservation)

    async def set_kea_reservation(self, uuid_value: str, reservation: dict[str, Any]) -> dict[str, Any]:
        self._set(self.reservations, uuid_value, reservation)
        return {}

    async def delete_kea_reservation(self, uuid_value: str) -> dict[str, Any]:
        self._delete(self.reservations, uuid_value)
        return {}

    async def apply_kea(self) -> dict[str, Any]:
        self.applied.append("dhcp")
        return {}

    # DNS
    async def search_unbound_host_overrides(self) -> dict[str, Any]:
        return {"rows": self.overrides}

    async def add_unbound_host_override(self, host: dict[str, Any]) -> dict[str, Any]:
        return self._add(self.overrides, host)

    async def set_unbound_host_override(self, uuid_value: str, host: dict[str, Any]) -> dict[str, Any]:
        self._set(self.overrides, uuid_value, host)
        return {}

    async def delete_unbound_host_override(self, uuid_value: str) -> dict[str, Any]:
        self._delete(self.overrides, uuid_value)
        return {}

    async def search_unbound_host_aliases(self) -> dict[str, Any]:
        return {"rows": self.aliases}

    async def add_unbound_host_alias(self, alias: dict[str, Any]) -> dict[str, Any]:
        return self._add(self.aliases, alias)

    async def set_unbound_host_alias(self, uuid_value: str, alias: dict[str, Any]) -> dict[str, Any]:
        self._set(self.aliases, uuid_value, alias)
        return {}

    async def delete_unbound_host_alias(self, uuid_value: str) -> dict[str, Any]:
        self._delete(self.aliases, uuid_value)
        return {}

    async def apply_unbound(self) -> dict[str, Any]:
        self.applied.append("dns")
        return {}


def _deployer(monkeypatch: pytest.MonkeyPatch, uow: FakeUow, client: FakeOpnsense) -> ConfigurationDeployer:
    deployer = ConfigurationDeployer(None, uuid.uuid4())  # type: ignore[arg-type]
    deployer.devices = FakeDevices()  # type: ignore[assignment]
    deployer.uow = uow  # type: ignore[assignment]
    deployer.audit = FakeAudit()  # type: ignore[assignment]
    deployer.session = FakeSession()  # type: ignore[assignment]
    monkeypatch.setattr(config_module, "client_for", lambda *args, **kwargs: client)
    return deployer


def _counts(outcome: dict[str, Any]) -> tuple[int, int, int]:
    return outcome["created"], outcome["updated"], outcome["deleted"]


# --------------------------------------------------------------------------- models
def _rule(name: str) -> FirewallRule:
    return FirewallRule(
        id=uuid.uuid4(),
        name=name,
        description=None,
        action=RuleAction.PASS,
        direction=RuleDirection.IN,
        interface="lan",
        protocol="tcp",
        source="any",
        destination="any",
        destination_port="443",
        source_port=None,
        gateway=None,
        log=False,
        enabled=True,
        order_index=10,
    )


def _nat(name: str, nat_type: NatType = NatType.PORT_FORWARD) -> NatRule:
    return NatRule(
        id=uuid.uuid4(),
        name=name,
        description=None,
        type=nat_type,
        interface="wan",
        protocol="tcp",
        source="any",
        destination="wan",
        destination_port="443",
        target="10.10.0.10",
        target_port="443",
        enabled=True,
        order_index=0,
    )


def _vlan(vlan_id: int) -> VlanConfig:
    return VlanConfig(
        id=uuid.uuid4(),
        vlan_id=vlan_id,
        parent_interface="igb1",
        description=None,
        enabled=True,
    )


def _scope(scope_id: uuid.UUID | None = None) -> DhcpScope:
    return DhcpScope(
        id=scope_id or uuid.uuid4(),
        name="LAN",
        subnet="10.10.0.0/24",
        pool_start="10.10.0.100",
        pool_end="10.10.0.200",
        gateway="10.10.0.1",
        dns_servers=["1.1.1.1"],
        domain_name="lan.example.com",
        lease_time_seconds=3600,
        enabled=True,
    )


def _reservation(scope: DhcpScope) -> DhcpReservation:
    return DhcpReservation(
        id=uuid.uuid4(),
        scope_id=scope.id,
        hostname="printer",
        mac_address="aa:bb:cc:dd:ee:ff",
        ip_address="10.10.0.50",
        enabled=True,
    )


def _record(
    name: str,
    record_type: DnsRecordType,
    value: str,
    *,
    ttl: int = 300,
    priority: int | None = None,
) -> DnsRecord:
    return DnsRecord(
        id=uuid.uuid4(),
        name=name,
        record_type=record_type,
        value=value,
        ttl=ttl,
        priority=priority,
        weight=None,
        port=None,
        enabled=True,
    )


# --------------------------------------------------------------------------- tests
def test_nat_payloads_follow_the_per_kind_model() -> None:
    port_forward = nat_payload(_nat("WEB"))
    assert port_forward["descr"] == "OFME-WEB"
    assert "description" not in port_forward

    outbound = nat_payload(_nat("MASQ", NatType.OUTBOUND))
    assert outbound["description"] == "OFME-MASQ"
    assert outbound["source_net"] == "any"
    assert outbound["destination_net"] == "wan"
    assert outbound["target"] == "10.10.0.10"
    assert "descr" not in outbound

    one_to_one = nat_payload(_nat("BINAT", NatType.ONE_TO_ONE))
    assert one_to_one["description"] == "OFME-BINAT"
    assert one_to_one["type"] == "binat"
    assert one_to_one["external"] == "10.10.0.10"
    assert "descr" not in one_to_one


@pytest.mark.asyncio(loop_scope="session")
async def test_rules_apply_is_idempotent_and_prunes(monkeypatch: pytest.MonkeyPatch) -> None:
    uow = FakeUow(rules=[_rule("ALLOW-WEB")])
    client = FakeOpnsense()
    client.rules = [
        {"uuid": "stale", "description": "OFME-OLD-RULE", "action": "block"},
        {"uuid": "foreign", "description": "admin-managed", "action": "pass"},
    ]
    deployer = _deployer(monkeypatch, uow, client)

    first = await deployer.deploy_rules(DEVICE_ID)
    assert _counts(first) == (1, 0, 1)
    assert client.applied == ["rules"]
    assert {row["description"] for row in client.rules} == {"OFME-ALLOW-WEB", "admin-managed"}

    second = await deployer.deploy_rules(DEVICE_ID)
    assert _counts(second) == (0, 0, 0)
    assert client.applied == ["rules"], "a no-op apply must not reload the ruleset"

    uow.rules.rows.clear()
    pruned = await deployer.deploy_rules(DEVICE_ID)
    assert _counts(pruned) == (0, 0, 1)
    assert {row["description"] for row in client.rules} == {"admin-managed"}


@pytest.mark.asyncio(loop_scope="session")
async def test_nat_apply_adopts_legacy_marker_and_prunes(monkeypatch: pytest.MonkeyPatch) -> None:
    uow = FakeUow(nat=[_nat("WEB")])
    client = FakeOpnsense()
    client.nat["d_nat"] = [
        {
            "uuid": "legacy",
            "descr": "OFME: WEB",
            "enabled": "1",
            "interface": "wan",
            "protocol": "tcp",
            "src": "",
            "dst": "wan",
            "dstport": "443",
            "target": "10.10.0.10",
            "local-port": "443",
            "natreflection": "disable",
            "log": "0",
        }
    ]
    client.nat["source_nat"] = [{"uuid": "stale", "description": "OFME-OLD-OUTBOUND", "enabled": "1"}]
    deployer = _deployer(monkeypatch, uow, client)

    first = await deployer.deploy_nat(DEVICE_ID)
    assert _counts(first) == (0, 1, 1)
    assert client.nat["d_nat"][0]["descr"] == "OFME-WEB"
    assert client.nat["source_nat"] == []
    assert sorted(client.applied) == ["nat:d_nat", "nat:source_nat"]

    second = await deployer.deploy_nat(DEVICE_ID)
    assert _counts(second) == (0, 0, 0)
    assert sorted(client.applied) == ["nat:d_nat", "nat:source_nat"]


@pytest.mark.asyncio(loop_scope="session")
async def test_vlans_apply_is_idempotent_and_prunes(monkeypatch: pytest.MonkeyPatch) -> None:
    uow = FakeUow(vlans=[_vlan(100)])
    client = FakeOpnsense()
    client.vlans = [
        {"uuid": "stale", "if": "igb1", "tag": "200", "descr": "OFME-OLD-VLAN"},
        {"uuid": "foreign", "if": "igb1", "tag": "300", "descr": "manual"},
    ]
    deployer = _deployer(monkeypatch, uow, client)

    first = await deployer.deploy_vlans(DEVICE_ID)
    assert _counts(first) == (1, 0, 1)
    assert client.applied == ["vlans"]

    second = await deployer.deploy_vlans(DEVICE_ID)
    assert _counts(second) == (0, 0, 0)
    assert client.applied == ["vlans"]
    assert {(row["if"], row["tag"]) for row in client.vlans} == {("igb1", "100"), ("igb1", "300")}


@pytest.mark.asyncio(loop_scope="session")
async def test_dhcp_apply_is_idempotent_and_prunes(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope()
    reservation = _reservation(scope)
    uow = FakeUow(scopes=[scope], reservations=[reservation])
    client = FakeOpnsense()
    client.subnets = [{"uuid": "stale-subnet", "subnet": "10.99.0.0/24", "description": "OFME-OLD"}]
    client.reservations = [
        {
            "uuid": "stale-reservation",
            "subnet": "stale-subnet",
            "hw_address": "11:22:33:44:55:66",
            "description": "OFME-ghost",
        }
    ]
    deployer = _deployer(monkeypatch, uow, client)

    first = await deployer.deploy_dhcp(DEVICE_ID)
    assert _counts(first) == (2, 0, 2)
    assert client.applied == ["dhcp"]
    assert {row["subnet"] for row in client.subnets} == {"10.10.0.0/24"}
    assert len(client.reservations) == 1
    assert client.reservations[0]["hw_address"] == "aa:bb:cc:dd:ee:ff"
    assert client.reservations[0]["subnet"] == client.subnets[0]["uuid"]

    second = await deployer.deploy_dhcp(DEVICE_ID)
    assert _counts(second) == (0, 0, 0)
    assert client.applied == ["dhcp"]

    # Kea may return list-valued option data as lists; that must still compare
    # equal to the comma-separated string we write.
    client.subnets[0]["option_data"] = {
        "domain_name_servers": ["1.1.1.1"],
        "routers": ["10.10.0.1"],
        "domain_name": ["lan.example.com"],
    }
    third = await deployer.deploy_dhcp(DEVICE_ID)
    assert _counts(third) == (0, 0, 0)
    assert client.applied == ["dhcp"]

    scope.enabled = False
    disabled = await deployer.deploy_dhcp(DEVICE_ID)
    assert _counts(disabled) == (0, 0, 2)
    assert client.subnets == []
    assert client.reservations == []


@pytest.mark.asyncio(loop_scope="session")
async def test_dns_apply_is_idempotent_skips_unsupported_and_prunes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        _record("www.lan.example.com", DnsRecordType.A, "10.10.0.10"),
        _record("mail.lan.example.com", DnsRecordType.MX, "mx.example.com", priority=10),
        _record("alias.lan.example.com", DnsRecordType.CNAME, "www.lan.example.com"),
        _record("unqualified", DnsRecordType.A, "10.10.0.20"),
    ]
    disabled = _record("off.lan.example.com", DnsRecordType.A, "10.10.0.30")
    disabled.enabled = False
    records.append(disabled)
    uow = FakeUow(records=records)
    client = FakeOpnsense()
    client.overrides = [
        {
            "uuid": "stale",
            "hostname": "old",
            "domain": "lan.example.com",
            "rr": "A",
            "server": "10.10.0.99",
            "description": "OFME-old.lan.example.com",
        },
        {
            "uuid": "foreign",
            "hostname": "keep",
            "domain": "lan.example.com",
            "rr": "A",
            "server": "10.10.0.98",
            "description": "manual entry",
        },
    ]
    deployer = _deployer(monkeypatch, uow, client)

    first = await deployer.deploy_dns(DEVICE_ID)
    assert _counts(first) == (3, 0, 1)
    assert client.applied == ["dns"]
    assert {row["hostname"] for row in client.overrides} == {"www", "mail", "keep"}
    # The CNAME is published as a host alias of the managed A record it targets.
    assert len(client.aliases) == 1
    alias = client.aliases[0]
    target = next(row for row in client.overrides if row["hostname"] == "www")
    assert alias["host"] == target["uuid"]
    assert (alias["hostname"], alias["domain"]) == ("alias", "lan.example.com")
    assert alias["description"] == "OFME-alias.lan.example.com"
    skipped = {item["name"]: item["reason"] for item in first["skipped"]}
    assert set(skipped) == {"unqualified", "off.lan.example.com"}
    assert skipped["off.lan.example.com"] == "record is disabled"

    second = await deployer.deploy_dns(DEVICE_ID)
    assert _counts(second) == (0, 0, 0)
    assert client.applied == ["dns"]


@pytest.mark.asyncio(loop_scope="session")
async def test_dhcp_dry_run_does_not_touch_the_appliance(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope()
    uow = FakeUow(scopes=[scope], reservations=[_reservation(scope)])
    client = FakeOpnsense()
    deployer = _deployer(monkeypatch, uow, client)

    outcome = await deployer.deploy_dhcp(DEVICE_ID, dry_run=True)
    assert outcome["applied"] is False
    assert outcome["subnets"][0]["subnet"] == "10.10.0.0/24"
    assert outcome["reservations"][0]["hostname"] == "printer"
    assert client.subnets == []
    assert client.reservations == []
    assert client.applied == []


@pytest.mark.asyncio(loop_scope="session")
async def test_apply_resources_rejects_unknown_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    deployer = _deployer(monkeypatch, FakeUow(), FakeOpnsense())
    with pytest.raises(Exception, match="Unknown configuration resource"):
        await deployer.apply_resources(DEVICE_ID, ["rules", "bogus"])
