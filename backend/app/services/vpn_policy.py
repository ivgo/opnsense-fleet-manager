"""VPN-as-code: push a ``VpnPolicy`` document to an OPNsense appliance.

The policy path is deliberately separate from the SD-WAN topology path: a
topology describes edges between managed devices, while a VPN policy describes
one endpoint (server, peers, tunnel network) that is replicated to the selected
devices. Both paths use the same ownership marker and the same idempotent
"compare only returned fields" rule as the other configuration deployers.
"""

from __future__ import annotations

import base64
import ipaddress
import uuid
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.integrations.opnsense.client import client_for
from app.models.topology import Device
from app.services.audit import AuditService
from app.services.configuration import needs_update
from app.services.devices import DeviceService
from app.services.sdwan import (
    _generate_ca,
    _generate_certificate,
    _lan_cidr,
    _response_ref,
    _rows,
    _slug,
)

_MARKER = "OFME-"
_LEGACY_MARKER = "OFME:"
_DEFAULT_WIREGUARD_PORT = 51820
_DEFAULT_WIREGUARD_MTU = 1420
_DEFAULT_OPENVPN_PORT = 1194
_DEFAULT_OPENVPN_NETWORK = "10.251.0.0/24"


def _device_wan(device: Device | None) -> str:
    if device is None:
        return ""
    metadata = device.metadata_ or {}
    return str(metadata.get("wan_ip") or metadata.get("public_ip") or device.ip_address or "")


def _policy_slug(name: str) -> str:
    return _slug(name).strip(".-_")[:48] or "policy"


def policy_description(policy_name: str, suffix: str | None = None) -> str:
    """Return the ownership description for a policy object."""
    base = f"{_MARKER}{_policy_slug(policy_name)}"
    return f"{base}-{_slug(suffix)}" if suffix else base


def _legacy_description(value: str) -> str:
    if value.startswith(_MARKER):
        return f"{_LEGACY_MARKER} {value[len(_MARKER):]}"
    return value


def is_policy_object(value: Any, policy_name: str) -> bool:
    """True when an appliance object belongs to the named policy (any marker era)."""
    text = str(value or "").strip()
    base = policy_description(policy_name)
    legacy = _legacy_description(base)
    return text in (base, legacy) or text.startswith(f"{base}-") or text.startswith(f"{legacy}-")


def _find_policy_object(payload: Any, field: str, description: str) -> dict[str, Any] | None:
    legacy = _legacy_description(description)
    for row in _rows(payload):
        value = str(row.get(field) or "").strip()
        if value in (description, legacy):
            return row
    return None


def _derive(policy_name: str, device_id: uuid.UUID, label: str, length: int = 32) -> bytes:
    """Derive stable key material for a policy/device pair.

    VPN policy documents do not carry private keys, and generating a fresh key
    on every apply would make the policy non-idempotent. Deriving from the
    deployment secret keeps the material stable across restarts without adding
    a new secret store.
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=_policy_slug(policy_name).encode(),
        info=f"{device_id}:{label}".encode(),
    )
    return hkdf.derive(settings.SECRET_KEY.encode())


def _wireguard_keypair(policy_name: str, device_id: uuid.UUID) -> tuple[str, str]:
    raw = _derive(policy_name, device_id, "wireguard")
    key = X25519PrivateKey.from_private_bytes(raw)
    private = base64.b64encode(
        key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
        )
    ).decode()
    public = base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).decode()
    return private, public


def _default_address(policy_name: str, device_id: uuid.UUID, *, host: int, prefix: int = 24) -> str:
    octet = int.from_bytes(_derive(policy_name, device_id, "address", 1), "big") % 250 + 1
    return f"10.250.{octet}.{host}/{prefix}"


def _server_name(policy_name: str) -> str:
    return f"{_MARKER}{_policy_slug(policy_name)}"[:64]


def _peer_name(policy_name: str, peer_name: str) -> str:
    return f"{_MARKER}{_policy_slug(policy_name)}-peer-{_slug(peer_name)}"[:64]


def _network(value: str | None, default: str) -> str:
    if not value:
        return default
    try:
        return str(ipaddress.ip_network(str(value), strict=False))
    except ValueError:
        return default


def _relation_ids(value: Any) -> set[str]:
    """Normalise a ModelRelationField response (mapping or list) to UUIDs."""
    if isinstance(value, dict):
        return {str(item) for item in value}
    if isinstance(value, list | tuple):
        return {str(item) for item in value}
    return set()


class VpnPolicyDeployer:
    """Materialise a VPN policy on one device and prune its stale objects."""

    def __init__(self, session: Any, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.devices = DeviceService(session, tenant_id, actor_id)
        self.audit = AuditService(session)

    async def deploy(
        self,
        device_id: uuid.UUID,
        spec: dict[str, Any],
        policy_name: str,
        *,
        dry_run: bool = False,
        apply: bool = True,
    ) -> dict[str, Any]:
        device = await self.devices.get(device_id)
        protocol = str(spec.get("protocol") or "wireguard").lower()
        if protocol == "wireguard":
            outcome = await self._wireguard(device, spec, policy_name, dry_run=dry_run, apply=apply)
        elif protocol == "ipsec":
            outcome = await self._ipsec(device, spec, policy_name, dry_run=dry_run, apply=apply)
        elif protocol == "openvpn":
            outcome = await self._openvpn(device, spec, policy_name, dry_run=dry_run, apply=apply)
        else:
            raise BadRequestError(f"Unsupported VPN policy protocol '{protocol}'")
        if not dry_run:
            await self.audit.record(
                action="vpn.policy_applied",
                resource_type="Device",
                resource_id=device.id,
                tenant_id=self.tenant_id,
                user_id=self.actor_id,
                after={
                    "policy": policy_name,
                    "protocol": protocol,
                    "created": outcome["created"],
                    "updated": outcome["updated"],
                    "deleted": outcome["deleted"],
                    "skipped": outcome["skipped"],
                },
            )
        return outcome

    async def teardown(
        self,
        device_id: uuid.UUID,
        policy_name: str,
        *,
        dry_run: bool = False,
        apply: bool = True,
    ) -> dict[str, Any]:
        """Remove every appliance object that belongs to a VPN policy.

        Used when a rollback restores a state in which the policy did not exist
        yet and when a policy is deleted. All three protocol families are
        scanned because the protocol is not stored on the appliance object.
        """
        device = await self.devices.get(device_id)
        server_name = _server_name(policy_name)
        peer_prefix = f"{_MARKER}{_policy_slug(policy_name)}-peer-"

        if dry_run:
            return {
                "device_id": str(device.id),
                "policy": policy_name,
                "created": 0,
                "updated": 0,
                "deleted": 0,
                "skipped": [],
                "applied": False,
            }

        base_url, key, secret = await self.devices.credentials(device)
        deleted = 0
        async with client_for(base_url, key, secret) as client:
            wireguard_changed = False
            for row in _rows(await client.search_wireguard_servers()):
                if str(row.get("name") or "") == server_name and row.get("uuid"):
                    await client.delete_wireguard_server(str(row["uuid"]))
                    deleted += 1
                    wireguard_changed = True
            for row in _rows(await client.search_wireguard_clients()):
                name = str(row.get("name") or "")
                if name.startswith(peer_prefix) and row.get("uuid"):
                    await client.delete_wireguard_client(str(row["uuid"]))
                    deleted += 1
                    wireguard_changed = True
            if apply and wireguard_changed:
                await client.apply_wireguard()

            ipsec_changed = False
            for search, remove in (
                (client.search_ipsec_phase2, client.delete_ipsec_phase2),
                (client.search_ipsec_phase1, client.delete_ipsec_phase1),
            ):
                for row in _rows(await search()):
                    if is_policy_object(row.get("descr"), policy_name) and row.get("uuid"):
                        await remove(str(row["uuid"]))
                        deleted += 1
                        ipsec_changed = True
            if apply and ipsec_changed:
                await client.apply_ipsec_phase1()
                await client.apply_ipsec()

            openvpn_changed = False
            for row in _rows(await client.search_openvpn_instances()):
                if is_policy_object(row.get("description"), policy_name) and row.get("uuid"):
                    await client.delete_openvpn_instance(str(row["uuid"]))
                    deleted += 1
                    openvpn_changed = True
            for search, remove in (
                (client.search_certificates, client.delete_certificate),
                (client.search_cas, client.delete_ca),
            ):
                for row in _rows(await search()):
                    if is_policy_object(row.get("descr"), policy_name) and row.get("uuid"):
                        await remove(str(row["uuid"]))
                        deleted += 1
                        openvpn_changed = True
            if apply and openvpn_changed:
                await client.apply_openvpn()

        await self.audit.record(
            action="vpn.policy_removed",
            resource_type="Device",
            resource_id=device.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"policy": policy_name, "deleted": deleted},
        )
        return {
            "device_id": str(device.id),
            "policy": policy_name,
            "created": 0,
            "updated": 0,
            "deleted": deleted,
            "skipped": [],
            "applied": apply,
        }

    # ------------------------------------------------------------- WireGuard
    async def _wireguard(
        self,
        device: Device,
        spec: dict[str, Any],
        policy_name: str,
        *,
        dry_run: bool,
        apply: bool,
    ) -> dict[str, Any]:
        private, public = _wireguard_keypair(policy_name, device.id)
        address = str(spec.get("address") or _default_address(policy_name, device.id, host=1))
        port = int(spec.get("listen_port") or _DEFAULT_WIREGUARD_PORT)
        server_name = _server_name(policy_name)
        skipped: list[dict[str, str]] = []
        peers: list[dict[str, Any]] = []
        for position, peer in enumerate(spec.get("peers") or []):
            peer_label = str(peer.get("name") or f"peer-{position + 1}")
            peer_key = str(peer.get("public_key") or "").strip()
            if not peer_key:
                skipped.append({"name": peer_label, "reason": "peer has no public key"})
                continue
            peers.append(
                {
                    "name": _peer_name(policy_name, peer_label),
                    "pubkey": peer_key,
                    "tunneladdress": _default_address(policy_name, device.id, host=position + 2, prefix=32),
                    "endpoint": str(peer.get("endpoint") or ""),
                    "keepalive": str(peer.get("keepalive") or 25),
                }
            )

        if dry_run:
            return {
                "device_id": str(device.id),
                "protocol": "wireguard",
                "payloads": [{"server": server_name, "peers": peers}],
                "created": 0,
                "updated": 0,
                "deleted": 0,
                "skipped": skipped,
                "applied": False,
            }

        base_url, key, secret = await self.devices.credentials(device)
        created = updated = deleted = 0
        async with client_for(base_url, key, secret) as client:
            changed = False
            servers = await client.search_wireguard_servers()
            row = _rows(servers)
            server_row = next((item for item in row if str(item.get("name") or "") == server_name), None)
            server_payload = {
                "enabled": "1",
                "name": server_name,
                "pubkey": public,
                "privkey": private,
                "port": str(port),
                "mtu": str(_DEFAULT_WIREGUARD_MTU),
                "tunneladdress": address,
            }
            if server_row is not None and server_row.get("uuid"):
                server_uuid = str(server_row["uuid"])
                if needs_update(server_row, server_payload):
                    await client.set_wireguard_server(server_uuid, server_payload)
                    updated += 1
                    changed = True
            else:
                response = await client.add_wireguard_server(server_payload)
                server_uuid = _response_ref(response, "uuid", "id")
                if server_uuid is None:
                    fresh = next(
                        (
                            item
                            for item in _rows(await client.search_wireguard_servers())
                            if str(item.get("name") or "") == server_name
                        ),
                        None,
                    )
                    server_uuid = str(fresh["uuid"]) if fresh and fresh.get("uuid") else None
                created += 1
                changed = True
            if not server_uuid:
                raise BadRequestError("Could not determine the WireGuard server identifier")

            client_rows = await client.search_wireguard_clients()
            desired_peers: list[str] = []
            for peer in peers:
                payload = {
                    "enabled": "1",
                    "name": peer["name"],
                    "pubkey": peer["pubkey"],
                    "psk": "",
                    "tunneladdress": peer["tunneladdress"],
                    "serveraddress": _device_wan(device),
                    "serverport": str(port),
                    "keepalive": peer["keepalive"],
                    "servers": [server_uuid],
                }
                existing = next(
                    (item for item in _rows(client_rows) if str(item.get("name") or "") == peer["name"]),
                    None,
                )
                compare = {field: value for field, value in payload.items() if field != "servers"}
                if existing is not None and existing.get("uuid"):
                    desired_peers.append(str(existing["uuid"]))
                    if needs_update(existing, compare) or _relation_ids(existing.get("servers")) != {
                        server_uuid
                    }:
                        await client.set_wireguard_client(str(existing["uuid"]), payload)
                        updated += 1
                        changed = True
                else:
                    response = await client.add_wireguard_client(payload)
                    peer_uuid = _response_ref(response, "uuid", "id")
                    if peer_uuid is None:
                        fresh = next(
                            (
                                item
                                for item in _rows(await client.search_wireguard_clients())
                                if str(item.get("name") or "") == peer["name"]
                            ),
                            None,
                        )
                        peer_uuid = str(fresh["uuid"]) if fresh and fresh.get("uuid") else None
                    if peer_uuid:
                        desired_peers.append(peer_uuid)
                    created += 1
                    changed = True

            # The server model references peers by UUID. ``needs_update`` cannot
            # compare a relation (the API returns a mapping, the payload a list),
            # so the UUID set is compared explicitly to keep re-applies a no-op.
            relation = {"peers": desired_peers}
            if _relation_ids((server_row or {}).get("peers")) != set(desired_peers):
                await client.set_wireguard_server(server_uuid, {**server_payload, **relation})
                updated += 1
                changed = True

            prefix = f"{_MARKER}{_policy_slug(policy_name)}-peer-"
            for stale in _rows(await client.search_wireguard_clients()):
                stale_name = str(stale.get("name") or "")
                if (
                    stale_name.startswith(prefix)
                    and stale_name not in {peer["name"] for peer in peers}
                    and stale.get("uuid")
                ):
                    await client.delete_wireguard_client(str(stale["uuid"]))
                    deleted += 1
                    changed = True

            if apply and changed:
                await client.apply_wireguard()

        return {
            "device_id": str(device.id),
            "protocol": "wireguard",
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "skipped": skipped,
            "applied": apply,
        }

    # ----------------------------------------------------------------- IPsec
    async def _ipsec(
        self,
        device: Device,
        spec: dict[str, Any],
        policy_name: str,
        *,
        dry_run: bool,
        apply: bool,
    ) -> dict[str, Any]:
        skipped: list[dict[str, str]] = []
        plans: list[dict[str, Any]] = []
        local_net = _lan_cidr(device)
        for position, peer in enumerate(spec.get("peers") or []):
            label = str(peer.get("name") or f"peer-{position + 1}")
            endpoint = str(peer.get("endpoint") or "").strip()
            if not endpoint:
                skipped.append({"name": label, "reason": "IPsec peer has no endpoint"})
                continue
            remote_gateway = endpoint.split(":", 1)[0]
            remote_net = ", ".join(str(item) for item in (peer.get("allowed_ips") or [])) or "0.0.0.0/0"
            description = policy_description(policy_name, label)
            psk = base64.b64encode(_derive(policy_name, device.id, f"ipsec:{label}")).decode()
            phase1 = {
                "enabled": "1",
                "descr": description,
                "iketype": "ikev2",
                "protocol": "esp",
                "interface": "wan",
                "remote_gateway": remote_gateway,
                "local_gateway": _device_wan(device),
                "authentication_method": "pre_shared_key",
                "pre-shared-key": psk,
                "encryption": ["aes256gcm16"],
                "hash": ["sha256"],
                "lifetime": "28800",
                "disabled": "0",
            }
            phase2 = {
                "enabled": "1",
                "descr": description,
                "mode": "tunnel",
                "protocol": "esp",
                "local_net": local_net,
                "remote_net": remote_net,
                "encryption": ["aes256gcm16"],
                "hash": ["sha256"],
                "pfs_group": "14",
                "lifetime": "3600",
                "disabled": "0",
            }
            plans.append({"label": label, "phase1": phase1, "phase2": phase2})

        if dry_run:
            return {
                "device_id": str(device.id),
                "protocol": "ipsec",
                "payloads": plans,
                "created": 0,
                "updated": 0,
                "deleted": 0,
                "skipped": skipped,
                "applied": False,
            }

        base_url, key, secret = await self.devices.credentials(device)
        created = updated = deleted = 0
        async with client_for(base_url, key, secret) as client:
            changed = False
            phase1_rows = await client.search_ipsec_phase1()
            phase2_rows = await client.search_ipsec_phase2()
            desired: set[str] = set()
            for plan in plans:
                description = str(plan["phase1"]["descr"])
                desired.add(description)
                row = _find_policy_object(phase1_rows, "descr", description)
                if row is not None and row.get("uuid"):
                    phase1_uuid = str(row["uuid"])
                    if needs_update(row, plan["phase1"]):
                        await client.set_ipsec_phase1(phase1_uuid, plan["phase1"])
                        updated += 1
                        changed = True
                else:
                    response = await client.add_ipsec_phase1(plan["phase1"])
                    phase1_uuid = _response_ref(response, "uuid", "id")
                    if phase1_uuid is None:
                        fresh = _find_policy_object(await client.search_ipsec_phase1(), "descr", description)
                        phase1_uuid = str(fresh["uuid"]) if fresh and fresh.get("uuid") else None
                    created += 1
                    changed = True
                if not phase1_uuid:
                    skipped.append({"name": plan["label"], "reason": "phase1 was not created"})
                    continue

                phase2_payload = {**plan["phase2"], "phase1_uuid": phase1_uuid}
                row2 = _find_policy_object(phase2_rows, "descr", description)
                if row2 is not None and row2.get("uuid"):
                    if needs_update(row2, phase2_payload):
                        await client.set_ipsec_phase2(str(row2["uuid"]), phase2_payload)
                        updated += 1
                        changed = True
                else:
                    await client.add_ipsec_phase2(phase2_payload)
                    created += 1
                    changed = True

            for stale in _rows(await client.search_ipsec_phase2()):
                descr = str(stale.get("descr") or "")
                if is_policy_object(descr, policy_name) and descr not in desired and stale.get("uuid"):
                    await client.delete_ipsec_phase2(str(stale["uuid"]))
                    deleted += 1
                    changed = True
            for stale in _rows(await client.search_ipsec_phase1()):
                descr = str(stale.get("descr") or "")
                if is_policy_object(descr, policy_name) and descr not in desired and stale.get("uuid"):
                    await client.delete_ipsec_phase1(str(stale["uuid"]))
                    deleted += 1
                    changed = True

            if apply and changed:
                await client.apply_ipsec_phase1()
                await client.apply_ipsec()

        return {
            "device_id": str(device.id),
            "protocol": "ipsec",
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "skipped": skipped,
            "applied": apply,
        }

    # --------------------------------------------------------------- OpenVPN
    async def _openvpn(
        self,
        device: Device,
        spec: dict[str, Any],
        policy_name: str,
        *,
        dry_run: bool,
        apply: bool,
    ) -> dict[str, Any]:
        port = int(spec.get("listen_port") or _DEFAULT_OPENVPN_PORT)
        network = _network(spec.get("address"), _DEFAULT_OPENVPN_NETWORK)
        description = policy_description(policy_name)
        ca_description = policy_description(policy_name, "CA")
        cert_description = policy_description(policy_name, "CERT")
        skipped: list[dict[str, str]] = []

        if dry_run:
            return {
                "device_id": str(device.id),
                "protocol": "openvpn",
                "payloads": [
                    {
                        "description": description,
                        "role": "server",
                        "port": port,
                        "tunnel_network": network,
                        "ca": ca_description,
                        "cert": cert_description,
                    }
                ],
                "created": 0,
                "updated": 0,
                "deleted": 0,
                "skipped": skipped,
                "applied": False,
            }

        base_url, key, secret = await self.devices.credentials(device)
        created = updated = deleted = 0
        async with client_for(base_url, key, secret) as client:
            changed = False
            ca_row = _find_policy_object(await client.search_cas(), "descr", ca_description)
            ca_ref = ""
            ca_cert_pem = ""
            ca_key_pem = ""
            if ca_row is not None:
                ca_ref = str(ca_row.get("refid") or ca_row.get("uuid") or "")
            if not ca_ref:
                ca_cert_pem, ca_key_pem = _generate_ca(f"OFME {policy_name} CA")
                response = await client.add_ca(
                    {
                        "descr": ca_description,
                        "caref": uuid.uuid4().hex[:8],
                        "cert": ca_cert_pem,
                        "prv": ca_key_pem,
                    }
                )
                ca_ref = _response_ref(response, "refid", "uuid", "caref") or ""
                if not ca_ref:
                    fresh = _find_policy_object(await client.search_cas(), "descr", ca_description)
                    ca_ref = str(fresh.get("refid") or fresh.get("uuid") or "") if fresh else ""
                created += 1
                changed = True
            if not ca_ref:
                raise BadRequestError("Could not determine the OpenVPN CA reference")

            cert_row = _find_policy_object(await client.search_certificates(), "descr", cert_description)
            cert_ref = str(cert_row.get("refid") or cert_row.get("uuid") or "") if cert_row else ""
            if not cert_ref:
                if not ca_cert_pem or not ca_key_pem:
                    skipped.append(
                        {
                            "name": description,
                            "reason": (
                                "CA exists on the appliance but its key is not available; "
                                "delete the managed CA and re-apply"
                            ),
                        }
                    )
                    return {
                        "device_id": str(device.id),
                        "protocol": "openvpn",
                        "created": created,
                        "updated": updated,
                        "deleted": deleted,
                        "skipped": skipped,
                        "applied": apply,
                    }
                common_name = _slug(f"{policy_name}-{device.name}")[:64]
                cert_pem, cert_key_pem = _generate_certificate(ca_cert_pem, ca_key_pem, common_name)
                response = await client.add_certificate(
                    {
                        "descr": cert_description,
                        "caref": ca_ref,
                        "cert": cert_pem,
                        "prv": cert_key_pem,
                    }
                )
                cert_ref = _response_ref(response, "refid", "uuid") or ""
                if not cert_ref:
                    fresh = _find_policy_object(await client.search_certificates(), "descr", cert_description)
                    cert_ref = str(fresh.get("refid") or fresh.get("uuid") or "") if fresh else ""
                created += 1
                changed = True
            if not cert_ref:
                raise BadRequestError("Could not determine the OpenVPN certificate reference")

            payload = {
                "enabled": "1",
                "role": "server",
                "description": description,
                "dev": "tun",
                "proto": "udp",
                "port": str(port),
                "local": _device_wan(device),
                "tunnel_network": network,
                "ca": ca_ref,
                "cert": cert_ref,
                "key": cert_ref,
                "auth": "SHA256",
                "cipher": "AES-256-GCM",
                "digest": "SHA256",
                "keepalive_interval": "10",
                "keepalive_timeout": "60",
                "compression": "none",
                "verb": "1",
            }
            instance_row = _find_policy_object(
                await client.search_openvpn_instances(), "description", description
            )
            if instance_row is not None and instance_row.get("uuid"):
                if needs_update(instance_row, payload):
                    await client.set_openvpn_instance(str(instance_row["uuid"]), payload)
                    updated += 1
                    changed = True
            else:
                await client.add_openvpn_instance(payload)
                created += 1
                changed = True

            for stale in _rows(await client.search_openvpn_instances()):
                descr = str(stale.get("description") or "")
                if is_policy_object(descr, policy_name) and descr != description and stale.get("uuid"):
                    await client.delete_openvpn_instance(str(stale["uuid"]))
                    deleted += 1
                    changed = True

            if apply and changed:
                await client.apply_openvpn()

        return {
            "device_id": str(device.id),
            "protocol": "openvpn",
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "skipped": skipped,
            "applied": apply,
        }
