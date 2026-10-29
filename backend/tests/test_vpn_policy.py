"""VPN-as-code deployer: payload shapes, idempotency, pruning and teardown."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.models.enums import VpnProtocol
from app.models.topology import Device
from app.services import vpn_policy as vpn_module
from app.services.vpn_policy import VpnPolicyDeployer, policy_description

TENANT_ID = uuid.uuid4()
DEVICE_ID = uuid.uuid4()


class FakeDevices:
    def __init__(self, device: Device) -> None:
        self.device = device

    async def get(self, device_id: uuid.UUID) -> Device:
        assert device_id == self.device.id
        return self.device

    async def credentials(self, device: Device) -> tuple[str, str, str]:
        return "https://fw.test", "key", "secret"


class FakeAudit:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


class FakeClient:
    """In-memory OPNsense stand-in for the VPN endpoints."""

    def __init__(self) -> None:
        self.servers: dict[str, dict[str, Any]] = {}
        self.clients: dict[str, dict[str, Any]] = {}
        self.phase1: dict[str, dict[str, Any]] = {}
        self.phase2: dict[str, dict[str, Any]] = {}
        self.instances: dict[str, dict[str, Any]] = {}
        self.cas: dict[str, dict[str, Any]] = {}
        self.certificates: dict[str, dict[str, Any]] = {}
        self.applied: list[str] = []
        self._seq = 0

    def _uuid(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    # WireGuard
    async def search_wireguard_servers(self) -> dict[str, Any]:
        return {"rows": [dict(row) for row in self.servers.values()]}

    async def add_wireguard_server(self, payload: dict[str, Any]) -> dict[str, Any]:
        uuid_value = self._uuid("srv")
        self.servers[uuid_value] = {"uuid": uuid_value, **payload}
        return {"uuid": uuid_value}

    async def set_wireguard_server(self, uuid_value: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.servers[uuid_value].update(payload)
        return {}

    async def delete_wireguard_server(self, uuid_value: str) -> dict[str, Any]:
        self.servers.pop(uuid_value, None)
        return {}

    async def search_wireguard_clients(self) -> dict[str, Any]:
        return {"rows": [dict(row) for row in self.clients.values()]}

    async def add_wireguard_client(self, payload: dict[str, Any]) -> dict[str, Any]:
        uuid_value = self._uuid("cli")
        self.clients[uuid_value] = {"uuid": uuid_value, **payload}
        return {"uuid": uuid_value}

    async def set_wireguard_client(self, uuid_value: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.clients[uuid_value].update(payload)
        return {}

    async def delete_wireguard_client(self, uuid_value: str) -> dict[str, Any]:
        self.clients.pop(uuid_value, None)
        return {}

    async def apply_wireguard(self) -> dict[str, Any]:
        self.applied.append("wireguard")
        return {}

    # IPsec
    async def search_ipsec_phase1(self) -> dict[str, Any]:
        return {"rows": [dict(row) for row in self.phase1.values()]}

    async def add_ipsec_phase1(self, payload: dict[str, Any]) -> dict[str, Any]:
        uuid_value = self._uuid("p1")
        self.phase1[uuid_value] = {"uuid": uuid_value, **payload}
        return {"uuid": uuid_value}

    async def set_ipsec_phase1(self, uuid_value: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.phase1[uuid_value].update(payload)
        return {}

    async def delete_ipsec_phase1(self, uuid_value: str) -> dict[str, Any]:
        self.phase1.pop(uuid_value, None)
        return {}

    async def search_ipsec_phase2(self) -> dict[str, Any]:
        return {"rows": [dict(row) for row in self.phase2.values()]}

    async def add_ipsec_phase2(self, payload: dict[str, Any]) -> dict[str, Any]:
        uuid_value = self._uuid("p2")
        self.phase2[uuid_value] = {"uuid": uuid_value, **payload}
        return {"uuid": uuid_value}

    async def set_ipsec_phase2(self, uuid_value: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.phase2[uuid_value].update(payload)
        return {}

    async def delete_ipsec_phase2(self, uuid_value: str) -> dict[str, Any]:
        self.phase2.pop(uuid_value, None)
        return {}

    async def apply_ipsec_phase1(self) -> dict[str, Any]:
        self.applied.append("ipsec-phase1")
        return {}

    async def apply_ipsec(self) -> dict[str, Any]:
        self.applied.append("ipsec")
        return {}

    # OpenVPN
    async def search_openvpn_instances(self) -> dict[str, Any]:
        return {"rows": [dict(row) for row in self.instances.values()]}

    async def add_openvpn_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        uuid_value = self._uuid("ovpn")
        self.instances[uuid_value] = {"uuid": uuid_value, **payload}
        return {"uuid": uuid_value}

    async def set_openvpn_instance(self, uuid_value: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.instances[uuid_value].update(payload)
        return {}

    async def delete_openvpn_instance(self, uuid_value: str) -> dict[str, Any]:
        self.instances.pop(uuid_value, None)
        return {}

    async def apply_openvpn(self) -> dict[str, Any]:
        self.applied.append("openvpn")
        return {}

    # Trust store
    async def search_cas(self) -> dict[str, Any]:
        return {"rows": [dict(row) for row in self.cas.values()]}

    async def add_ca(self, payload: dict[str, Any]) -> dict[str, Any]:
        uuid_value = self._uuid("ca")
        self.cas[uuid_value] = {"uuid": uuid_value, "refid": uuid_value, **payload}
        return {"refid": uuid_value}

    async def delete_ca(self, uuid_value: str) -> dict[str, Any]:
        self.cas.pop(uuid_value, None)
        return {}

    async def search_certificates(self) -> dict[str, Any]:
        return {"rows": [dict(row) for row in self.certificates.values()]}

    async def add_certificate(self, payload: dict[str, Any]) -> dict[str, Any]:
        uuid_value = self._uuid("cert")
        self.certificates[uuid_value] = {"uuid": uuid_value, "refid": uuid_value, **payload}
        return {"refid": uuid_value}

    async def delete_certificate(self, uuid_value: str) -> dict[str, Any]:
        self.certificates.pop(uuid_value, None)
        return {}


@pytest.fixture
def device() -> Device:
    return Device(
        id=DEVICE_ID,
        tenant_id=TENANT_ID,
        name="edge-1",
        ip_address="198.51.100.10",
        metadata_={"wan_ip": "198.51.100.10", "lan_cidr": "10.10.0.0/24"},
    )


def _deployer(monkeypatch: pytest.MonkeyPatch, device: Device, client: FakeClient) -> VpnPolicyDeployer:
    deployer = VpnPolicyDeployer(None, TENANT_ID)  # type: ignore[arg-type]
    deployer.devices = FakeDevices(device)  # type: ignore[assignment]
    deployer.audit = FakeAudit()  # type: ignore[assignment]
    monkeypatch.setattr(vpn_module, "client_for", lambda *args, **kwargs: client)
    return deployer


def _counts(outcome: dict[str, Any]) -> tuple[int, int, int]:
    return outcome["created"], outcome["updated"], outcome["deleted"]


def _wireguard_spec(peers: list[str]) -> dict[str, Any]:
    return {
        "protocol": VpnProtocol.WIREGUARD.value,
        "listen_port": 51820,
        "peers": [
            {
                "name": name,
                "public_key": f"pub-{name}",
                "endpoint": f"203.0.113.{index + 1}:51820",
                "keepalive": 25,
            }
            for index, name in enumerate(peers)
        ],
    }


@pytest.mark.asyncio(loop_scope="session")
async def test_wireguard_dry_run_does_not_call_the_appliance(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    deployer = _deployer(monkeypatch, device, client)

    outcome = await deployer.deploy(DEVICE_ID, _wireguard_spec(["branch"]), "site-vpn", dry_run=True)

    assert outcome["applied"] is False
    assert _counts(outcome) == (0, 0, 0)
    assert outcome["payloads"][0]["server"] == "OFME-site-vpn"
    assert outcome["payloads"][0]["peers"][0]["name"] == "OFME-site-vpn-peer-branch"
    assert client.servers == {}


@pytest.mark.asyncio(loop_scope="session")
async def test_wireguard_apply_is_idempotent_and_attaches_peers(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    deployer = _deployer(monkeypatch, device, client)
    spec = _wireguard_spec(["branch", "lab"])

    first = await deployer.deploy(DEVICE_ID, spec, "site-vpn")
    assert first["created"] == 3
    assert first["updated"] == 1
    assert client.applied == ["wireguard"]
    assert len(client.servers) == 1
    server = next(iter(client.servers.values()))
    assert server["name"] == "OFME-site-vpn"
    assert server["tunneladdress"].endswith("/24")
    assert set(server["peers"]) == set(client.clients)

    second = await deployer.deploy(DEVICE_ID, spec, "site-vpn")
    assert _counts(second) == (0, 0, 0)
    assert client.applied == ["wireguard"]


@pytest.mark.asyncio(loop_scope="session")
async def test_wireguard_prunes_peers_that_left_the_policy(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    deployer = _deployer(monkeypatch, device, client)
    await deployer.deploy(DEVICE_ID, _wireguard_spec(["branch", "lab"]), "site-vpn")

    outcome = await deployer.deploy(DEVICE_ID, _wireguard_spec(["branch"]), "site-vpn")

    assert outcome["deleted"] == 1
    assert [row["name"] for row in client.clients.values()] == ["OFME-site-vpn-peer-branch"]


@pytest.mark.asyncio(loop_scope="session")
async def test_wireguard_skips_peers_without_a_public_key(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    deployer = _deployer(monkeypatch, device, client)
    spec = _wireguard_spec(["branch"])
    spec["peers"][0]["public_key"] = ""

    outcome = await deployer.deploy(DEVICE_ID, spec, "site-vpn")

    assert outcome["skipped"] == [{"name": "branch", "reason": "peer has no public key"}]
    assert outcome["created"] == 1
    assert client.clients == {}


@pytest.mark.asyncio(loop_scope="session")
async def test_ipsec_apply_creates_phase1_and_phase2_once(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    deployer = _deployer(monkeypatch, device, client)
    spec = {
        "protocol": VpnProtocol.IPSEC.value,
        "peers": [{"name": "hq", "endpoint": "203.0.113.5:500", "allowed_ips": ["10.20.0.0/24"]}],
    }

    first = await deployer.deploy(DEVICE_ID, spec, "site-vpn")
    assert _counts(first) == (2, 0, 0)
    assert first["skipped"] == []
    assert client.applied == ["ipsec-phase1", "ipsec"]
    phase1 = next(iter(client.phase1.values()))
    phase2 = next(iter(client.phase2.values()))
    assert phase1["descr"] == "OFME-site-vpn-hq"
    assert phase1["remote_gateway"] == "203.0.113.5"
    assert phase2["local_net"] == "10.10.0.0/24"
    assert phase2["remote_net"] == "10.20.0.0/24"

    second = await deployer.deploy(DEVICE_ID, spec, "site-vpn")
    assert _counts(second) == (0, 0, 0)
    assert client.applied == ["ipsec-phase1", "ipsec"]


@pytest.mark.asyncio(loop_scope="session")
async def test_ipsec_skips_peers_without_endpoint(device: Device, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    deployer = _deployer(monkeypatch, device, client)
    spec = {"protocol": VpnProtocol.IPSEC.value, "peers": [{"name": "hq"}]}

    outcome = await deployer.deploy(DEVICE_ID, spec, "site-vpn")

    assert outcome["skipped"] == [{"name": "hq", "reason": "IPsec peer has no endpoint"}]
    assert client.phase1 == {}


@pytest.mark.asyncio(loop_scope="session")
async def test_openvpn_apply_creates_ca_certificate_and_instance_once(
    device: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    deployer = _deployer(monkeypatch, device, client)
    spec = {"protocol": VpnProtocol.OPENVPN.value, "listen_port": 1194}

    first = await deployer.deploy(DEVICE_ID, spec, "remote-access")
    assert _counts(first) == (3, 0, 0)
    assert client.applied == ["openvpn"]
    instance = next(iter(client.instances.values()))
    assert instance["description"] == policy_description("remote-access")
    assert instance["role"] == "server"
    assert instance["port"] == "1194"

    second = await deployer.deploy(DEVICE_ID, spec, "remote-access")
    assert _counts(second) == (0, 0, 0)
    assert client.applied == ["openvpn"]


@pytest.mark.asyncio(loop_scope="session")
async def test_openvpn_reports_a_ca_without_its_key(device: Device, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    client.cas["ca-existing"] = {
        "uuid": "ca-existing",
        "refid": "ca-existing",
        "descr": policy_description("remote-access", "CA"),
    }
    deployer = _deployer(monkeypatch, device, client)

    outcome = await deployer.deploy(DEVICE_ID, {"protocol": VpnProtocol.OPENVPN.value}, "remote-access")

    assert outcome["created"] == 0
    assert outcome["skipped"][0]["name"] == policy_description("remote-access")
    assert "key is not available" in outcome["skipped"][0]["reason"]
    assert client.instances == {}


@pytest.mark.asyncio(loop_scope="session")
async def test_teardown_removes_every_managed_object(device: Device, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    deployer = _deployer(monkeypatch, device, client)
    await deployer.deploy(DEVICE_ID, _wireguard_spec(["branch"]), "site-vpn")
    client.applied.clear()

    outcome = await deployer.teardown(DEVICE_ID, "site-vpn")

    assert outcome["deleted"] == 2
    assert client.servers == {}
    assert client.clients == {}
    assert client.applied == ["wireguard"]
