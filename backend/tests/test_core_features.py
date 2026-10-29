"""Tests for the core features completed in this change set.

The suite mixes pure unit tests (planning, payload builders, PKI) with database
and API tests (HA CRUD, rollback replay, notification delivery).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from cryptography import x509
from sqlalchemy import select

from app.core.security import encrypt_secret
from app.models.config import FirewallRule, NatRule, VlanConfig
from app.models.enums import (
    DeploymentStatus,
    Environment,
    NatType,
    PolicyKind,
    RuleAction,
    RuleDirection,
    TopologyType,
    VpnProtocol,
)
from app.models.policy import Policy, PolicyDeployment
from app.models.sdwan import SdwanTopology, VpnTunnel, WireGuardKey
from app.models.topology import Device
from app.services import sdwan as sdwan_module
from app.services.configuration import ConfigurationDeployer, nat_payload, vlan_payload
from app.services.gitops import DeploymentService
from app.services.sdwan import (
    TopologyEngine,
    TunnelProvisioner,
    _generate_ca,
    _generate_certificate,
    _latest_handshake,
)
from app.services.vpn_policy import VpnPolicyDeployer


# --------------------------------------------------------------------------- pure units
def test_topology_plan_uses_configured_protocol() -> None:
    hub = Device(id=uuid.uuid4(), name="hub", ip_address="10.0.0.1", metadata_={})
    spoke = Device(id=uuid.uuid4(), name="spoke", ip_address="10.1.0.1", metadata_={})
    topology = SdwanTopology(
        id=uuid.uuid4(),
        topology_type=TopologyType.HUB_SPOKE,
        hub_device_ids=[str(hub.id)],
        spoke_device_ids=[str(spoke.id)],
        configuration={"protocol": "openvpn", "wan_interface": "wan"},
    )

    plans = TopologyEngine.plan(topology, {hub.id: hub, spoke.id: spoke})

    assert len(plans) == 1
    assert plans[0].protocol == VpnProtocol.OPENVPN
    assert plans[0].allowed_ips == ["10.0.0.0/24"]


def test_nat_and_vlan_payloads_are_marked_and_complete() -> None:
    rule = NatRule(
        id=uuid.uuid4(),
        name="web",
        type=NatType.PORT_FORWARD,
        interface="wan",
        protocol="tcp",
        source="any",
        destination="any",
        destination_port="443",
        target="10.0.0.10",
        target_port="8443",
        enabled=True,
        order_index=10,
    )
    payload = nat_payload(rule)
    assert payload["descr"] == "OFME-web"
    assert payload["dstport"] == "443"
    assert payload["local-port"] == "8443"

    vlan = VlanConfig(
        id=uuid.uuid4(),
        vlan_id=20,
        parent_interface="igb0",
        description="voice",
        enabled=True,
    )
    vlan_payload_value = vlan_payload(vlan)
    assert vlan_payload_value["tag"] == "20"
    assert vlan_payload_value["descr"] == "OFME-voice"


def test_ca_and_client_certificate_chain() -> None:
    ca_pem, ca_key_pem = _generate_ca("OFME Test CA")
    cert_pem, key_pem = _generate_certificate(ca_pem, ca_key_pem, "device-1")

    ca = x509.load_pem_x509_certificate(ca_pem.encode())
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    assert ca.subject == ca.issuer
    assert cert.issuer == ca.subject
    assert cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value == "device-1"
    assert "BEGIN PRIVATE KEY" in key_pem


def test_latest_handshake_parses_nested_peers() -> None:
    row = {"peers": [{"latest_handshake": 1_700_000_000}, {"latest_handshake": 0}]}
    parsed = _latest_handshake(row)
    assert parsed is not None
    assert int(parsed.timestamp()) == 1_700_000_000


# --------------------------------------------------------------------------- fake OPNsense clients
class _ClientBase:
    def __init__(self) -> None:
        self.applied = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def apply_wireguard(self) -> dict:
        self.applied += 1
        return {}

    async def apply_ipsec_phase1(self) -> dict:
        return {}

    async def apply_ipsec(self) -> dict:
        self.applied += 1
        return {}


class _WireGuardClient(_ClientBase):
    def __init__(self) -> None:
        super().__init__()
        self.servers: dict[str, dict] = {}
        self.clients: dict[str, dict] = {}
        self.added = 0
        self.updated = 0
        self.clients_added = 0
        self.clients_updated = 0
        self.clients_deleted = 0
        self._seq = 0

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    async def search_wireguard_servers(self) -> dict:
        return {"rows": [dict(row) for row in self.servers.values()]}

    async def add_wireguard_server(self, payload: dict) -> dict:
        self.added += 1
        uuid = self._next("srv")
        self.servers[uuid] = {"uuid": uuid, **payload}
        return {"uuid": uuid}

    async def set_wireguard_server(self, uuid: str, payload: dict) -> dict:
        self.updated += 1
        self.servers[uuid].update(payload)
        return {}

    async def delete_wireguard_server(self, uuid: str) -> dict:
        self.servers.pop(uuid, None)
        return {}

    async def search_wireguard_clients(self) -> dict:
        return {"rows": [dict(row) for row in self.clients.values()]}

    async def add_wireguard_client(self, payload: dict) -> dict:
        self.clients_added += 1
        uuid = self._next("cli")
        self.clients[uuid] = {"uuid": uuid, **payload}
        return {"uuid": uuid}

    async def set_wireguard_client(self, uuid: str, payload: dict) -> dict:
        self.clients_updated += 1
        self.clients[uuid].update(payload)
        return {}

    async def delete_wireguard_client(self, uuid: str) -> dict:
        self.clients_deleted += 1
        self.clients.pop(uuid, None)
        return {}


class _IpsecClient(_ClientBase):
    def __init__(self) -> None:
        super().__init__()
        self.phase1: list[dict] = []
        self.phase2: list[dict] = []
        self.added_p1 = 0
        self.updated_p1 = 0
        self.added_p2 = 0
        self.updated_p2 = 0

    async def search_ipsec_phase1(self) -> dict:
        return {"rows": [dict(row) for row in self.phase1]}

    async def add_ipsec_phase1(self, payload: dict) -> dict:
        self.added_p1 += 1
        uuid = f"p1-{self.added_p1}"
        self.phase1.append({"uuid": uuid, **payload})
        return {"uuid": uuid}

    async def set_ipsec_phase1(self, uuid: str, payload: dict) -> dict:
        self.updated_p1 += 1
        return {}

    async def search_ipsec_phase2(self) -> dict:
        return {"rows": [dict(row) for row in self.phase2]}

    async def add_ipsec_phase2(self, payload: dict) -> dict:
        self.added_p2 += 1
        uuid = f"p2-{self.added_p2}"
        self.phase2.append({"uuid": uuid, **payload})
        return {"uuid": uuid}

    async def set_ipsec_phase2(self, uuid: str, payload: dict) -> dict:
        self.updated_p2 += 1
        return {}


class _FakeDevices:
    async def credentials(self, device: Device) -> tuple[str, str, str]:
        return "https://device", "key", "secret"


class _FakeKeys:
    def __init__(self, keys: dict[uuid.UUID, WireGuardKey]) -> None:
        self.keys = keys

    async def for_device(self, topology_id: uuid.UUID, device_id: uuid.UUID) -> WireGuardKey | None:
        return self.keys.get(device_id)


class _FakeUow:
    def __init__(self, keys: _FakeKeys) -> None:
        self.wireguard_keys = keys


def _provisioner(keys: _FakeKeys) -> TunnelProvisioner:
    provisioner = TunnelProvisioner(None, uuid.uuid4())  # type: ignore[arg-type]
    provisioner.devices = _FakeDevices()  # type: ignore[assignment]
    provisioner.uow = _FakeUow(keys)  # type: ignore[assignment]
    return provisioner


def _wireguard_tunnel(topology_id: uuid.UUID, local: Device, remote: Device) -> VpnTunnel:
    return VpnTunnel(
        id=uuid.uuid4(),
        topology_id=topology_id,
        name="wg-edge",
        protocol=VpnProtocol.WIREGUARD,
        local_device_id=local.id,
        remote_device_id=remote.id,
        interface_name="wgtest",
        allowed_ips=["10.9.0.0/24"],
        keepalive=25,
        mtu=1420,
        config={},
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_wireguard_endpoint_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    topology_id = uuid.uuid4()
    local = Device(
        id=uuid.uuid4(),
        name="spoke",
        ip_address="10.0.0.2",
        metadata_={"lan_cidr": "10.9.0.0/24"},
    )
    remote = Device(
        id=uuid.uuid4(),
        name="hub",
        ip_address="10.0.0.1",
        metadata_={"lan_cidr": "10.8.0.0/24"},
    )
    keys = _FakeKeys(
        {
            local.id: WireGuardKey(
                id=uuid.uuid4(),
                device_id=local.id,
                public_key="pub-local",
                private_key_encrypted=encrypt_secret("priv-local"),
                listen_port=51820,
                tunnel_address="10.250.0.2/32",
            ),
            remote.id: WireGuardKey(
                id=uuid.uuid4(),
                device_id=remote.id,
                public_key="pub-peer",
                private_key_encrypted=encrypt_secret("priv-peer"),
                listen_port=51821,
                tunnel_address="10.250.0.3/32",
            ),
        }
    )
    provisioner = _provisioner(keys)
    tunnel = _wireguard_tunnel(topology_id, local, remote)
    client = _WireGuardClient()
    monkeypatch.setattr(sdwan_module, "client_for", lambda *args, **kwargs: client)

    await provisioner._apply_wireguard_endpoint(None, tunnel, local, remote)  # type: ignore[arg-type]
    await provisioner._apply_wireguard_endpoint(None, tunnel, local, remote)  # type: ignore[arg-type]

    assert client.added == 1
    assert client.clients_added == 1
    # The server is written once for its own fields and once to attach the peer
    # relation; the second apply is a no-op.
    assert client.updated == 1
    assert client.applied == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_ipsec_endpoint_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    topology_id = uuid.uuid4()
    local = Device(
        id=uuid.uuid4(),
        name="left",
        ip_address="10.0.0.2",
        metadata_={"lan_cidr": "10.9.0.0/24"},
    )
    remote = Device(
        id=uuid.uuid4(),
        name="right",
        ip_address="10.0.0.1",
        metadata_={"lan_cidr": "10.8.0.0/24"},
    )
    tunnel = VpnTunnel(
        id=uuid.uuid4(),
        topology_id=topology_id,
        name="ipsec-edge",
        protocol=VpnProtocol.IPSEC,
        local_device_id=local.id,
        remote_device_id=remote.id,
        interface_name="ipsec0",
        allowed_ips=["10.8.0.0/24"],
        keepalive=25,
        mtu=1420,
        config={"psk_encrypted": encrypt_secret("test-psk")},
    )
    provisioner = _provisioner(_FakeKeys({}))
    client = _IpsecClient()
    monkeypatch.setattr(sdwan_module, "client_for", lambda *args, **kwargs: client)

    await provisioner._apply_ipsec_endpoint(None, tunnel, local, remote)  # type: ignore[arg-type]
    await provisioner._apply_ipsec_endpoint(None, tunnel, local, remote)  # type: ignore[arg-type]

    assert client.added_p1 == 1
    assert client.updated_p1 == 0
    assert client.added_p2 == 1
    assert client.updated_p2 == 0
    assert client.applied == 1


# --------------------------------------------------------------------------- database / API
@pytest.mark.asyncio(loop_scope="session")
async def test_rollback_replays_captured_snapshot(
    db_session, tenant_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = await tenant_factory()
    device = Device(tenant_id=tenant.id, name="edge-1", ip_address="10.0.0.1")
    policy = Policy(
        tenant_id=tenant.id,
        name="rollback-policy",
        kind=PolicyKind.FIREWALL,
        environment=Environment.DEVELOPMENT,
        content="",
    )
    db_session.add_all([device, policy])
    await db_session.flush()
    db_session.add(
        FirewallRule(
            tenant_id=tenant.id,
            device_id=device.id,
            name="current",
            action=RuleAction.PASS,
            direction=RuleDirection.IN,
            protocol="any",
            source="any",
            destination="any",
            order_index=10,
        )
    )
    deployment = PolicyDeployment(
        tenant_id=tenant.id,
        policy_id=policy.id,
        environment=Environment.DEVELOPMENT,
        status=DeploymentStatus.COMPLETED,
        target_device_ids=[str(device.id)],
        snapshot={
            "before": {
                str(device.id): {
                    "rules": [
                        {
                            "name": "old",
                            "description": None,
                            "action": "pass",
                            "direction": "in",
                            "interface": "wan",
                            "protocol": "any",
                            "source": "any",
                            "destination": "any",
                            "destination_port": None,
                            "source_port": None,
                            "gateway": None,
                            "log": False,
                            "enabled": True,
                            "order_index": 10,
                            "tags": [],
                        }
                    ]
                }
            },
            "after": {},
        },
        started_at=datetime.now(UTC),
    )
    db_session.add(deployment)
    await db_session.commit()

    async def _noop_deploy(self, device_id, *, dry_run=False, apply=True):
        return {"device_id": str(device_id), "created": 0, "updated": 0, "deleted": 0}

    monkeypatch.setattr(ConfigurationDeployer, "deploy_rules", _noop_deploy)

    service = DeploymentService(db_session, tenant.id)
    restored = await service.rollback(deployment.id)

    rows = (
        (await db_session.execute(select(FirewallRule).where(FirewallRule.device_id == device.id)))
        .scalars()
        .all()
    )
    assert restored.status == DeploymentStatus.ROLLED_BACK
    assert [row.name for row in rows] == ["old"]


VPN_POLICY_CONTENT = """\
apiVersion: fleet.opnsense.io/v1
kind: VpnPolicy
metadata:
  name: site-vpn
spec:
  protocol: wireguard
  listen_port: 51820
  peers:
    - name: branch
      public_key: pub-branch
      endpoint: 203.0.113.10:51820
"""


@pytest.mark.asyncio(loop_scope="session")
async def test_vpn_policy_deploy_records_spec_for_rollback(
    db_session, tenant_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = await tenant_factory()
    device = Device(tenant_id=tenant.id, name="edge-vpn", ip_address="10.0.0.5")
    policy = Policy(
        tenant_id=tenant.id,
        name="site-vpn",
        kind=PolicyKind.VPN,
        environment=Environment.DEVELOPMENT,
        content=VPN_POLICY_CONTENT,
    )
    db_session.add_all([device, policy])
    await db_session.commit()

    calls: list[dict] = []

    async def _fake_deploy(self, device_id, spec, policy_name, *, dry_run=False, apply=True):
        calls.append(
            {
                "device_id": device_id,
                "spec": spec,
                "policy": policy_name,
                "dry_run": dry_run,
                "apply": apply,
            }
        )
        return {
            "device_id": str(device_id),
            "protocol": spec.get("protocol"),
            "created": 1,
            "updated": 0,
            "deleted": 0,
            "skipped": [],
            "applied": apply,
        }

    monkeypatch.setattr(VpnPolicyDeployer, "deploy", _fake_deploy)
    torn_down: list[tuple] = []

    async def _fake_teardown(self, device_id, policy_name, *, dry_run=False, apply=True):
        torn_down.append((device_id, policy_name, dry_run, apply))
        return {
            "device_id": str(device_id),
            "policy": policy_name,
            "created": 0,
            "updated": 0,
            "deleted": 1,
            "skipped": [],
            "applied": apply,
        }

    monkeypatch.setattr(VpnPolicyDeployer, "teardown", _fake_teardown)
    service = DeploymentService(db_session, tenant.id)

    first = await service.deploy(policy.id, device_ids=[device.id])
    assert first.status == DeploymentStatus.COMPLETED
    assert len(calls) == 1
    assert calls[0]["spec"]["protocol"] == "wireguard"
    assert calls[0]["policy"] == "site-vpn"
    assert first.snapshot["before"][str(device.id)] == {"vpn": None, "policy": "site-vpn"}
    assert first.snapshot["after"][str(device.id)]["vpn"]["peers"][0]["name"] == "branch"

    # A second deployment captures the previously deployed spec as its before state.
    second = await service.deploy(policy.id, device_ids=[device.id])
    assert second.snapshot["before"][str(device.id)]["vpn"]["protocol"] == "wireguard"

    restored = await service.rollback(first.id)
    assert restored.status == DeploymentStatus.ROLLED_BACK
    # No earlier deployment existed, so the rollback removes the policy objects.
    assert torn_down == [(device.id, "site-vpn", False, True)]


@pytest.mark.asyncio(loop_scope="session")
async def test_vpn_rollback_tears_down_objects_that_did_not_exist(
    db_session, tenant_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = await tenant_factory()
    device = Device(tenant_id=tenant.id, name="edge-vpn", ip_address="10.0.0.6")
    policy = Policy(
        tenant_id=tenant.id,
        name="site-vpn",
        kind=PolicyKind.VPN,
        environment=Environment.DEVELOPMENT,
        content=VPN_POLICY_CONTENT,
    )
    db_session.add_all([device, policy])
    await db_session.flush()
    deployment = PolicyDeployment(
        tenant_id=tenant.id,
        policy_id=policy.id,
        environment=Environment.DEVELOPMENT,
        status=DeploymentStatus.COMPLETED,
        target_device_ids=[str(device.id)],
        snapshot={
            "before": {str(device.id): {"vpn": None, "policy": "site-vpn"}},
            "after": {},
        },
        started_at=datetime.now(UTC),
    )
    db_session.add(deployment)
    await db_session.commit()

    torn_down: list[tuple] = []

    async def _fake_teardown(self, device_id, policy_name, *, dry_run=False, apply=True):
        torn_down.append((device_id, policy_name, dry_run, apply))
        return {
            "device_id": str(device_id),
            "policy": policy_name,
            "created": 0,
            "updated": 0,
            "deleted": 2,
            "skipped": [],
            "applied": apply,
        }

    monkeypatch.setattr(VpnPolicyDeployer, "teardown", _fake_teardown)
    service = DeploymentService(db_session, tenant.id)
    restored = await service.rollback(deployment.id)

    assert restored.status == DeploymentStatus.ROLLED_BACK
    assert torn_down == [(device.id, "site-vpn", False, True)]


@pytest.mark.asyncio(loop_scope="session")
async def test_ha_cluster_crud(client, auth_headers) -> None:
    headers = await auth_headers()
    created = await client.post(
        "/api/v1/ha/clusters",
        headers=headers,
        json={
            "name": "edge-ha",
            "description": "site pair",
            "virtual_ip": "10.0.0.254",
            "interface": "lan",
            "vhid": 10,
            "advbase": 1,
            "nodes": [],
        },
    )
    assert created.status_code == 201, created.text
    cluster = created.json()
    assert cluster["sync_status"] == "unknown"

    listed = await client.get("/api/v1/ha/clusters", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1

    patched = await client.patch(
        f"/api/v1/ha/clusters/{cluster['id']}",
        headers=headers,
        json={"description": "updated"},
    )
    assert patched.status_code == 200
    assert patched.json()["description"] == "updated"

    deleted = await client.delete(f"/api/v1/ha/clusters/{cluster['id']}", headers=headers)
    assert deleted.status_code == 200

    # Soft-deleted clusters must not reserve their name forever.
    recreated = await client.post(
        "/api/v1/ha/clusters",
        headers=headers,
        json={
            "name": "edge-ha",
            "description": "recreated after delete",
            "virtual_ip": "10.0.0.254",
            "interface": "lan",
            "vhid": 10,
            "advbase": 1,
            "nodes": [],
        },
    )
    assert recreated.status_code == 201, recreated.text
    cleanup = await client.delete(f"/api/v1/ha/clusters/{recreated.json()['id']}", headers=headers)
    assert cleanup.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_notification_delivery_is_recorded(client, auth_headers) -> None:
    headers = await auth_headers()
    created = await client.post(
        "/api/v1/notifications",
        headers=headers,
        json={
            "title": "Maintenance window",
            "message": "Firewall upgrade at 22:00",
            "channels": ["unknown-channel"],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["delivery"]["unknown-channel"]["status"] == "skipped"
    assert body["delivered_at"] is None

    listed = await client.get("/api/v1/notifications", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1

    marked = await client.post(f"/api/v1/notifications/{body['id']}/read", headers=headers)
    assert marked.status_code == 200
