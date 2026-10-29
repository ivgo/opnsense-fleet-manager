"""SD-WAN orchestration: topology planning, VPN provisioning, routing, steering."""

from __future__ import annotations

import base64
import ipaddress
import math
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import combinations
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import TunnelStateChanged, event_bus
from app.core.exceptions import BadRequestError, UpstreamError
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret
from app.integrations.opnsense.client import client_for
from app.models.enums import (
    HealthStatus,
    SteeringStrategy,
    TopologyType,
    TunnelStatus,
    VpnProtocol,
)
from app.models.sdwan import (
    OpenVpnCa,
    OpenVpnCertificate,
    SdwanLink,
    SdwanRoute,
    SdwanTopology,
    TrafficPolicy,
    VpnTunnel,
    WireGuardKey,
)
from app.models.topology import Device
from app.repositories import UnitOfWork
from app.schemas.sdwan import (
    TopologyCreate,
    TopologyDeployResult,
    TopologyEdge,
    TopologyGraph,
    TopologyNode,
    TopologyUpdate,
    TunnelCreate,
    VpnEndpointStatus,
    VpnStatusOut,
    VpnTunnelStatus,
)
from app.services.audit import AuditService
from app.services.configuration import needs_update
from app.services.devices import DeviceService

log = get_logger("ofme.sdwan")

_MARKER = "OFME-"
_LEGACY_MARKER = "OFME:"
_DEFAULT_TUNNEL_NETWORK = "10.250.0.0/16"
_DEFAULT_WG_PORT = 51820
_DEFAULT_OPENVPN_PORT = 1194
_DEFAULT_OPENVPN_NETWORK = "10.251.0.0/24"
_HANDSHAKE_FRESH_SECONDS = 180


def generate_wireguard_keypair() -> tuple[str, str]:
    private_key = X25519PrivateKey.generate()
    private_b64 = base64.b64encode(private_key.private_bytes_raw()).decode()
    public_b64 = base64.b64encode(
        private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    return private_b64, public_b64


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("rows") or payload.get("items") or payload.get("vips") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _match_row(payload: Any, field: str, value: Any) -> dict[str, Any] | None:
    expected = str(value)
    for row in _rows(payload):
        if str(row.get(field) or "") == expected:
            return row
    return None


def _response_ref(response: Any, *keys: str) -> str | None:
    if not isinstance(response, dict):
        return None
    for key in keys:
        if response.get(key):
            return str(response[key])
    return None


def _device_wan(device: Device | None) -> str:
    if device is None:
        return ""
    metadata = device.metadata_ or {}
    return str(metadata.get("wan_ip") or metadata.get("public_ip") or device.ip_address or "")


def _tunnel_network(topology: SdwanTopology) -> ipaddress.IPv4Network:
    raw = str((topology.configuration or {}).get("tunnel_network") or _DEFAULT_TUNNEL_NETWORK)
    try:
        network = ipaddress.ip_network(raw, strict=False)
    except ValueError as exc:
        raise BadRequestError(f"Invalid tunnel network '{raw}'") from exc
    if network.version != 4 or network.num_addresses < 4:
        raise BadRequestError("Tunnel network must be an IPv4 network with at least two hosts")
    return network


def _topology_protocol(topology: SdwanTopology) -> VpnProtocol:
    raw = (topology.configuration or {}).get("protocol", VpnProtocol.WIREGUARD.value)
    try:
        return raw if isinstance(raw, VpnProtocol) else VpnProtocol(str(raw))
    except ValueError as exc:
        raise BadRequestError(f"Unsupported VPN protocol '{raw}'") from exc


def _as_list(value: Any, default: str) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item) for item in value] or [default]
    return [str(value)] if value else [default]


def _descr(value: VpnTunnel) -> str:
    return f"{_MARKER}{value.name}"


def _ca_descr(ca: OpenVpnCa) -> str:
    return f"{_MARKER}CA {ca.common_name}"


def _cert_descr(cert: OpenVpnCertificate) -> str:
    return f"{_MARKER}CERT {cert.common_name}"


def _legacy_description(value: str) -> str:
    """Translate a new-style description to the pre-1.0 ``OFME:`` form."""
    if value.startswith(_MARKER):
        return f"{_LEGACY_MARKER} {value[len(_MARKER):]}"
    return value


def is_managed_description(value: Any) -> bool:
    """True when an appliance object was created by OFME (any marker era)."""
    return str(value or "").strip().startswith((_MARKER, _LEGACY_MARKER))


def _find_managed(payload: Any, field: str, description: str) -> dict[str, Any] | None:
    """Find an object by its managed description, accepting the legacy marker."""
    legacy = _legacy_description(description)
    for row in _rows(payload):
        value = str(row.get(field) or "").strip()
        if value in (description, legacy):
            return row
    return None


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)[:64]


def _latest_handshake(row: dict[str, Any] | None) -> datetime | None:
    best: float | None = None

    def visit(value: Any) -> None:
        nonlocal best
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"latest-handshake", "latest_handshake", "last_handshake"}:
                    try:
                        timestamp = float(item)
                    except (TypeError, ValueError):
                        continue
                    if timestamp > 0 and (best is None or timestamp > best):
                        best = timestamp
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(row)
    if best is None:
        return None
    return datetime.fromtimestamp(best, UTC)


def _generate_ca(common_name: str) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name[:64]),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OFME"),
        ]
    )
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode()
    return certificate.public_bytes(Encoding.PEM).decode(), key_pem


def _generate_certificate(ca_cert_pem: str, ca_key_pem: str, common_name: str) -> tuple[str, str]:
    ca_certificate = x509.load_pem_x509_certificate(ca_cert_pem.encode())
    ca_key = serialization.load_pem_private_key(ca_key_pem.encode(), password=None)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, common_name[:64]),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OFME"),
                ]
            )
        )
        .issuer_name(ca_certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode()
    return certificate.public_bytes(Encoding.PEM).decode(), key_pem


@dataclass(slots=True)
class PlannedTunnel:
    name: str
    local_device_id: uuid.UUID
    remote_device_id: uuid.UUID | None
    protocol: VpnProtocol
    allowed_ips: list[str]
    endpoint_remote: str | None
    wan_interface: str
    priority: int
    cost: int


class TopologyEngine:
    """Pure planning logic - no I/O, fully unit-testable."""

    @staticmethod
    def plan(
        topology: SdwanTopology,
        devices: dict[uuid.UUID, Device],
        *,
        tunnel_prefix: str = "wg",
        protocol: VpnProtocol | None = None,
    ) -> list[PlannedTunnel]:
        if protocol is None:
            protocol = _topology_protocol(topology)
        hubs = [uuid.UUID(str(d)) for d in (topology.hub_device_ids or []) if d]
        spokes = [uuid.UUID(str(d)) for d in (topology.spoke_device_ids or []) if d]
        hubs = [h for h in hubs if h in devices]
        spokes = [s for s in spokes if s in devices]

        if topology.topology_type == TopologyType.HUB_SPOKE:
            if not hubs:
                raise BadRequestError("Hub-and-spoke topology requires at least one hub device")
            return [
                PlannedTunnel(
                    name=f"{tunnel_prefix}-{devices[spoke].name}-to-{devices[hubs[0]].name}"[:100],
                    local_device_id=spoke,
                    remote_device_id=hubs[0],
                    protocol=protocol,
                    allowed_ips=[_lan_cidr(devices[hubs[0]])],
                    endpoint_remote=None,
                    wan_interface=str((topology.configuration or {}).get("wan_interface", "wan")),
                    priority=100,
                    cost=10,
                )
                for spoke in spokes
            ]

        if topology.topology_type == TopologyType.FULL_MESH:
            participants = hubs + spokes
            if len(participants) < 2:
                raise BadRequestError("Full mesh requires at least two devices")
            plans: list[PlannedTunnel] = []
            for left, right in combinations(participants, 2):
                plans.append(
                    PlannedTunnel(
                        name=f"{tunnel_prefix}-{devices[left].name}-{devices[right].name}"[:100],
                        local_device_id=left,
                        remote_device_id=right,
                        protocol=protocol,
                        allowed_ips=[_lan_cidr(devices[right])],
                        endpoint_remote=None,
                        wan_interface="wan",
                        priority=100,
                        cost=10,
                    )
                )
            return plans

        # regional hub: spokes attach to the nearest hub by great-circle distance
        if not hubs:
            raise BadRequestError("Regional topology requires at least one hub")
        plans = []
        for left, right in combinations(hubs, 2):
            plans.append(
                PlannedTunnel(
                    name=f"{tunnel_prefix}-hub-{devices[left].name}-{devices[right].name}"[:100],
                    local_device_id=left,
                    remote_device_id=right,
                    protocol=protocol,
                    allowed_ips=[_lan_cidr(devices[right])],
                    endpoint_remote=None,
                    wan_interface="wan",
                    priority=50,
                    cost=5,
                )
            )
        for spoke in spokes:
            hub = min(hubs, key=lambda h: _distance(devices[h], devices[spoke]))
            plans.append(
                PlannedTunnel(
                    name=f"{tunnel_prefix}-{devices[spoke].name}-to-{devices[hub].name}"[:100],
                    local_device_id=spoke,
                    remote_device_id=hub,
                    protocol=protocol,
                    allowed_ips=[_lan_cidr(devices[hub])],
                    endpoint_remote=None,
                    wan_interface="wan",
                    priority=100,
                    cost=10,
                )
            )
        return plans


def _lan_cidr(device: Device) -> str:
    metadata = device.metadata_ or {}
    cidr = metadata.get("lan_cidr") or metadata.get("lan_network")
    if cidr:
        return str(cidr)
    if device.ip_address:
        try:
            network = ipaddress.ip_network(f"{device.ip_address}/24", strict=False)
            return str(network)
        except ValueError:
            pass
    return "10.255.255.0/24"


def _distance(left: Device, right: Device) -> float:
    def coords(device: Device) -> tuple[float, float] | None:
        site = device.site
        if site and site.latitude is not None and site.longitude is not None:
            return site.latitude, site.longitude
        return None

    a, b = coords(left), coords(right)
    if not a or not b:
        return 0.0

    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


class TopologyService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)
        self.devices = DeviceService(session, tenant_id, actor_id)

    async def create(self, payload: TopologyCreate) -> SdwanTopology:
        topology = SdwanTopology(
            tenant_id=self.tenant_id,
            name=payload.name,
            description=payload.description,
            topology_type=payload.topology_type,
            hub_device_ids=[str(d) for d in payload.hub_device_ids],
            spoke_device_ids=[str(d) for d in payload.spoke_device_ids],
            configuration=payload.configuration,
            routing_config=payload.routing_config,
            created_by=self.actor_id,
            status="draft",
        )
        self.session.add(topology)
        await self.session.flush()
        await self.audit.record(
            action="sdwan.topology_created",
            resource_type="SdwanTopology",
            resource_id=topology.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": topology.name, "type": topology.topology_type.value},
        )
        return topology

    async def update(self, topology_id: uuid.UUID, payload: TopologyUpdate) -> SdwanTopology:
        topology = await self.uow.topologies.get_or_404(topology_id)
        data = payload.model_dump(exclude_unset=True)
        for field in ("hub_device_ids", "spoke_device_ids"):
            if field in data and data[field] is not None:
                data[field] = [str(d) for d in data[field]]
        for field, value in data.items():
            setattr(topology, field, value)
        await self.session.flush()
        return topology

    async def graph(self, topology_id: uuid.UUID) -> TopologyGraph:
        topology = await self.uow.topologies.get_or_404(topology_id)
        tunnels = await self.uow.tunnels.for_topology(topology_id)
        device_ids: set[uuid.UUID] = set()
        for tunnel in tunnels:
            device_ids.add(tunnel.local_device_id)
            if tunnel.remote_device_id:
                device_ids.add(tunnel.remote_device_id)

        nodes: list[TopologyNode] = []
        for device_id in device_ids:
            device = await self.uow.devices.get(device_id)
            if device is None:
                continue
            role = "hub" if str(device_id) in {str(h) for h in topology.hub_device_ids or []} else "spoke"
            nodes.append(
                TopologyNode(
                    id=device.id,
                    name=device.name,
                    role=role,
                    status=device.status.value if hasattr(device.status, "value") else str(device.status),
                    site=device.site.name if device.site else None,
                    latitude=device.site.latitude if device.site else None,
                    longitude=device.site.longitude if device.site else None,
                )
            )

        links = await self.uow.links.for_topology(topology_id)
        link_by_tunnel = {link.tunnel_id: link for link in links if link.tunnel_id}
        edges = [
            TopologyEdge(
                id=tunnel.id,
                source=tunnel.local_device_id,
                target=tunnel.remote_device_id,
                status=tunnel.status.value if hasattr(tunnel.status, "value") else str(tunnel.status),
                health=tunnel.health_status.value
                if hasattr(tunnel.health_status, "value")
                else str(tunnel.health_status),
                latency_ms=link_by_tunnel.get(tunnel.id).latency_ms
                if link_by_tunnel.get(tunnel.id)
                else None,
                loss_pct=link_by_tunnel.get(tunnel.id).loss_pct if link_by_tunnel.get(tunnel.id) else None,
                label=tunnel.name,
            )
            for tunnel in tunnels
        ]
        return TopologyGraph(
            topology_id=topology.id,
            name=topology.name,
            type=topology.topology_type,
            nodes=nodes,
            edges=edges,
            generated_at=datetime.now(UTC),
        )


class TunnelProvisioner:
    """Creates tunnels, key material and pushes VPN configuration to OPNsense."""

    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.devices = DeviceService(session, tenant_id, actor_id)
        self.audit = AuditService(session)
        self.actor_id = actor_id

    # ------------------------------------------------------------------ tunnels
    async def create_tunnel(self, payload: TunnelCreate) -> VpnTunnel:
        topology = await self.uow.topologies.get_or_404(payload.topology_id)
        existing = await self.session.execute(
            select(VpnTunnel).where(VpnTunnel.topology_id == topology.id, VpnTunnel.name == payload.name)
        )
        if existing.scalars().first():
            raise BadRequestError(f"Tunnel '{payload.name}' already exists")

        local_device = await self.uow.devices.get_or_404(payload.local_device_id)
        remote_device = (
            await self.uow.devices.get(payload.remote_device_id) if payload.remote_device_id else None
        )
        local_key = await self._ensure_key(topology, local_device)
        remote_key = await self._ensure_key(topology, remote_device) if remote_device else None

        config: dict[str, Any] = {
            "wan_interface": payload.wan_interface,
            "private_key_ref": "encrypted",
        }
        if payload.protocol == VpnProtocol.IPSEC:
            config["psk_encrypted"] = encrypt_secret(secrets.token_urlsafe(32))

        tunnel = VpnTunnel(
            tenant_id=self.tenant_id,
            topology_id=topology.id,
            name=payload.name,
            protocol=payload.protocol,
            local_device_id=payload.local_device_id,
            remote_device_id=payload.remote_device_id,
            interface_name=payload.interface_name,
            public_key=local_key.public_key,
            preshared_key_encrypted=local_key.private_key_encrypted,
            peer_public_key=remote_key.public_key if remote_key else None,
            tunnel_address_local=local_key.tunnel_address,
            tunnel_address_remote=remote_key.tunnel_address if remote_key else None,
            endpoint_local=payload.endpoint_local or _device_wan(local_device) or None,
            endpoint_remote=payload.endpoint_remote
            or (_device_wan(remote_device) if remote_device else None),
            allowed_ips=payload.allowed_ips,
            keepalive=payload.keepalive,
            mtu=payload.mtu,
            status=TunnelStatus.PENDING,
            config=config,
        )
        self.session.add(tunnel)
        await self.session.flush()
        if not tunnel.interface_name:
            tunnel.interface_name = f"wg{tunnel.id.hex[:8]}"

        link = SdwanLink(
            tenant_id=self.tenant_id,
            topology_id=topology.id,
            tunnel_id=tunnel.id,
            local_device_id=payload.local_device_id,
            remote_device_id=payload.remote_device_id,
            wan_interface=payload.wan_interface,
            cost=payload.cost,
            priority=payload.priority,
            status=TunnelStatus.PENDING,
        )
        self.session.add(link)
        await self.session.flush()
        return tunnel

    async def provision_topology(
        self, topology_id: uuid.UUID, *, regenerate_keys: bool = False, dry_run: bool = False
    ) -> TopologyDeployResult:
        topology = await self.uow.topologies.get_or_404(topology_id)
        device_ids = {*(topology.hub_device_ids or []), *(topology.spoke_device_ids or [])}
        devices: dict[uuid.UUID, Device] = {}
        for raw in device_ids:
            device = await self.uow.devices.get(uuid.UUID(str(raw)))
            if device:
                devices[device.id] = device

        protocol = _topology_protocol(topology)
        plans = TopologyEngine.plan(topology, devices, protocol=protocol)
        created = updated = routes_installed = configured = 0
        errors: list[str] = []

        # Stable per-device key material and tunnel addresses exist before any
        # edge is created, so both ends can reference each other's public key.
        for device in devices.values():
            await self._ensure_key(topology, device, regenerate=regenerate_keys)

        for plan in plans:
            existing = (
                (
                    await self.session.execute(
                        select(VpnTunnel).where(
                            VpnTunnel.topology_id == topology.id, VpnTunnel.name == plan.name
                        )
                    )
                )
                .scalars()
                .first()
            )
            local_device = devices[plan.local_device_id]
            remote_device = devices.get(plan.remote_device_id) if plan.remote_device_id else None

            if existing is None:
                tunnel = await self.create_tunnel(
                    TunnelCreate(
                        topology_id=topology.id,
                        name=plan.name,
                        protocol=plan.protocol,
                        local_device_id=plan.local_device_id,
                        remote_device_id=plan.remote_device_id,
                        allowed_ips=plan.allowed_ips,
                        wan_interface=plan.wan_interface,
                        priority=plan.priority,
                        cost=plan.cost,
                    )
                )
                created += 1
            else:
                tunnel = existing
                local_key = await self._ensure_key(topology, local_device, regenerate=regenerate_keys)
                remote_key = (
                    await self._ensure_key(topology, remote_device, regenerate=regenerate_keys)
                    if remote_device
                    else None
                )
                tunnel.protocol = plan.protocol
                tunnel.allowed_ips = plan.allowed_ips
                tunnel.public_key = local_key.public_key
                tunnel.preshared_key_encrypted = local_key.private_key_encrypted
                tunnel.peer_public_key = remote_key.public_key if remote_key else None
                tunnel.tunnel_address_local = local_key.tunnel_address
                tunnel.tunnel_address_remote = remote_key.tunnel_address if remote_key else None
                if remote_device:
                    tunnel.endpoint_remote = _device_wan(remote_device) or tunnel.endpoint_remote
                updated += 1

            if dry_run:
                continue

            try:
                configured += await self._apply_tunnel(topology, tunnel, local_device, remote_device)
                tunnel.status = TunnelStatus.ACTIVE
                tunnel.health_status = HealthStatus.UNKNOWN
                routes_installed += await RouteManager(self.session, self.tenant_id).sync_routes(
                    topology.id, local_device.id
                )
                if remote_device is not None:
                    routes_installed += await RouteManager(self.session, self.tenant_id).sync_routes(
                        topology.id, remote_device.id
                    )
            except Exception as exc:  # noqa: BLE001 - record per-tunnel failure
                tunnel.status = TunnelStatus.ERROR
                errors.append(f"{plan.name}: {exc}")
                log.warning("sdwan.provision_failed", tunnel=plan.name, error=str(exc))

        removed = 0
        if not dry_run:
            planned_names = {plan.name for plan in plans}
            for tunnel in await self.uow.tunnels.for_topology(topology.id):
                if tunnel.name in planned_names:
                    continue
                try:
                    await self._remove_tunnel(tunnel)
                    removed += 1
                except Exception as exc:  # noqa: BLE001 - keep tearing down the rest
                    errors.append(f"{tunnel.name}: {exc}")
                    log.warning("sdwan.teardown_failed", tunnel=tunnel.name, error=str(exc))

        topology.status = "active" if not errors else "error"
        await self.session.flush()
        await self.audit.record(
            action="sdwan.topology_deployed",
            resource_type="SdwanTopology",
            resource_id=topology.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "created": created,
                "updated": updated,
                "removed": removed,
                "routes": routes_installed,
                "devices": configured,
                "errors": errors,
            },
        )
        await self.session.commit()
        return TopologyDeployResult(
            topology_id=topology.id,
            tunnels_created=created,
            tunnels_updated=updated,
            tunnels_removed=removed,
            routes_installed=routes_installed,
            devices_configured=configured,
            errors=errors,
        )

    async def _remove_tunnel(self, tunnel: VpnTunnel) -> None:
        """Remove the appliance objects of a tunnel that left the topology plan."""
        device_ids = {tunnel.local_device_id}
        if tunnel.remote_device_id:
            device_ids.add(tunnel.remote_device_id)
        for device_id in device_ids:
            device = await self.uow.devices.get(device_id)
            if device is None:
                continue
            base_url, key, secret = await self.devices.credentials(device)
            async with client_for(base_url, key, secret) as client:
                if tunnel.protocol == VpnProtocol.WIREGUARD:
                    row = _match_row(await client.search_wireguard_servers(), "name", tunnel.interface_name)
                    if row is not None and row.get("uuid"):
                        await client.delete_wireguard_server(str(row["uuid"]))
                    for peer in _rows(await client.search_wireguard_clients()):
                        peer_name = str(peer.get("name") or "")
                        if peer_name.startswith(f"peer-{tunnel.name}-") and peer.get("uuid"):
                            await client.delete_wireguard_client(str(peer["uuid"]))
                    await client.apply_wireguard()
                elif tunnel.protocol == VpnProtocol.IPSEC:
                    for search, delete in (
                        (client.search_ipsec_phase2, client.delete_ipsec_phase2),
                        (client.search_ipsec_phase1, client.delete_ipsec_phase1),
                    ):
                        row = _find_managed(await search(), "descr", _descr(tunnel))
                        if row is not None and row.get("uuid"):
                            await delete(str(row["uuid"]))
                    await client.apply_ipsec_phase1()
                    await client.apply_ipsec()
                elif tunnel.protocol == VpnProtocol.OPENVPN:
                    row = _find_managed(
                        await client.search_openvpn_instances(), "description", _descr(tunnel)
                    )
                    if row is not None and row.get("uuid"):
                        await client.delete_openvpn_instance(str(row["uuid"]))
                    await client.apply_openvpn()
        await self.session.delete(tunnel)

    # ------------------------------------------------------------------ key material
    async def _ensure_key(
        self, topology: SdwanTopology, device: Device, *, regenerate: bool = False
    ) -> WireGuardKey:
        key = await self.uow.wireguard_keys.for_device(topology.id, device.id)
        if key is not None and not regenerate:
            return key
        private_key, public_key = generate_wireguard_keypair()
        if key is not None:
            key.public_key = public_key
            key.private_key_encrypted = encrypt_secret(private_key)
            await self.session.flush()
            return key
        key = WireGuardKey(
            tenant_id=self.tenant_id,
            topology_id=topology.id,
            device_id=device.id,
            public_key=public_key,
            private_key_encrypted=encrypt_secret(private_key),
            listen_port=await self._allocate_port(device.id),
            tunnel_address=await self._allocate_tunnel_address(topology),
            created_by=self.actor_id,
        )
        self.session.add(key)
        await self.session.flush()
        return key

    async def _allocate_port(self, device_id: uuid.UUID) -> int:
        used = {key.listen_port for key in await self.uow.wireguard_keys.all_for_device(device_id)}
        port = _DEFAULT_WG_PORT
        while port in used:
            port += 1
        return port

    async def _allocate_tunnel_address(self, topology: SdwanTopology) -> str:
        used = {
            str(key.tunnel_address).split("/")[0]
            for key in await self.uow.wireguard_keys.for_topology(topology.id)
        }
        for host in _tunnel_network(topology).hosts():
            if str(host) not in used:
                return f"{host}/32"
        raise BadRequestError("WireGuard tunnel network is exhausted")

    # ------------------------------------------------------------------ device push
    async def _apply_tunnel(
        self,
        topology: SdwanTopology,
        tunnel: VpnTunnel,
        local_device: Device,
        remote_device: Device | None,
    ) -> int:
        if tunnel.protocol == VpnProtocol.WIREGUARD:
            await self._apply_wireguard_endpoint(topology, tunnel, local_device, remote_device)
            configured = 1
            if remote_device is not None:
                await self._apply_wireguard_endpoint(topology, tunnel, remote_device, local_device)
                configured += 1
            return configured

        if tunnel.protocol == VpnProtocol.IPSEC:
            await self._apply_ipsec_endpoint(topology, tunnel, local_device, remote_device)
            configured = 1
            if remote_device is not None:
                await self._apply_ipsec_endpoint(topology, tunnel, remote_device, local_device)
                configured += 1
            return configured

        if tunnel.protocol == VpnProtocol.OPENVPN:
            ca = await self._ensure_openvpn_ca(topology)
            server_device = self._openvpn_server_device(topology, local_device, remote_device)
            endpoints = [(local_device, local_device.id == server_device.id)]
            if remote_device is not None:
                endpoints.append((remote_device, remote_device.id == server_device.id))
            configured = 0
            for device, is_server in endpoints:
                certificate = await self._ensure_openvpn_certificate(topology, ca, device)
                peer = remote_device if device.id == local_device.id else local_device
                await self._apply_openvpn_endpoint(
                    tunnel,
                    device,
                    peer,
                    is_server=is_server,
                    ca=ca,
                    certificate=certificate,
                )
                configured += 1
            return configured

        raise BadRequestError(f"Unsupported tunnel protocol {tunnel.protocol}")

    async def _apply_wireguard_endpoint(
        self,
        topology: SdwanTopology,
        tunnel: VpnTunnel,
        device: Device,
        peer_device: Device | None,
    ) -> None:
        topology_id = tunnel.topology_id
        local_key = await self.uow.wireguard_keys.for_device(topology_id, device.id)
        if local_key is None:
            raise BadRequestError(f"No WireGuard key allocated for device {device.name}")
        peer_key = (
            await self.uow.wireguard_keys.for_device(topology_id, peer_device.id)
            if peer_device is not None
            else None
        )
        server_payload = {
            "enabled": "1",
            "name": tunnel.interface_name,
            "pubkey": local_key.public_key,
            "privkey": decrypt_secret(local_key.private_key_encrypted),
            "port": str(local_key.listen_port),
            "mtu": str(tunnel.mtu),
            "tunneladdress": local_key.tunnel_address,
        }

        base_url, key, secret = await self.devices.credentials(device)
        async with client_for(base_url, key, secret) as client:
            changed = False
            servers = await client.search_wireguard_servers()
            row = _match_row(servers, "name", tunnel.interface_name)
            if row is not None and row.get("uuid"):
                server_uuid = str(row["uuid"])
                if needs_update(row, server_payload):
                    await client.set_wireguard_server(server_uuid, server_payload)
                    changed = True
            else:
                response = await client.add_wireguard_server(server_payload)
                server_uuid = _response_ref(response, "uuid", "id")
                if server_uuid is None:
                    created = _match_row(
                        await client.search_wireguard_servers(), "name", tunnel.interface_name
                    )
                    server_uuid = str(created["uuid"]) if created and created.get("uuid") else None
                changed = True
            if not server_uuid:
                raise UpstreamError("Could not determine the WireGuard server identifier")

            peer_uuid: str | None = None
            peer_name: str | None = None
            if peer_key is not None and peer_device is not None:
                peer_name = _slug(f"peer-{tunnel.name}-{peer_device.name}")[:64]
                peer_payload = {
                    "enabled": "1",
                    "name": peer_name,
                    "pubkey": peer_key.public_key,
                    "psk": "",
                    "tunneladdress": peer_key.tunnel_address,
                    "serveraddress": _device_wan(peer_device),
                    "serverport": str(peer_key.listen_port),
                    "keepalive": str(tunnel.keepalive),
                    "servers": [server_uuid],
                }
                clients = await client.search_wireguard_clients()
                client_row = _match_row(clients, "name", peer_name)
                if client_row is not None and client_row.get("uuid"):
                    peer_uuid = str(client_row["uuid"])
                    if needs_update(client_row, peer_payload):
                        await client.set_wireguard_client(peer_uuid, peer_payload)
                        changed = True
                else:
                    response = await client.add_wireguard_client(peer_payload)
                    peer_uuid = _response_ref(response, "uuid", "id")
                    if peer_uuid is None:
                        created = _match_row(await client.search_wireguard_clients(), "name", peer_name)
                        peer_uuid = str(created["uuid"]) if created and created.get("uuid") else None
                    changed = True
                if not peer_uuid:
                    raise UpstreamError("Could not determine the WireGuard peer identifier")

                # The server model references peers by UUID; keep the relation in
                # sync so the generated configuration actually contains the peer.
                peers = [str(item) for item in (row or {}).get("peers") or []]
                if peer_uuid not in peers:
                    server_row = _match_row(
                        await client.search_wireguard_servers(), "name", tunnel.interface_name
                    )
                    relation = {"peers": [*peers, peer_uuid]}
                    if server_row is not None and server_row.get("uuid"):
                        await client.set_wireguard_server(str(server_row["uuid"]), relation)
                    changed = True

                # Prune peers of this tunnel that are no longer part of the plan.
                for stale in _rows(await client.search_wireguard_clients()):
                    stale_name = str(stale.get("name") or "")
                    if (
                        stale_name.startswith(f"peer-{tunnel.name}-")
                        and stale_name != peer_name
                        and stale.get("uuid")
                    ):
                        await client.delete_wireguard_client(str(stale["uuid"]))
                        changed = True

            if changed:
                await client.apply_wireguard()

    async def _apply_ipsec_endpoint(
        self,
        topology: SdwanTopology,
        tunnel: VpnTunnel,
        device: Device,
        peer_device: Device | None,
    ) -> None:
        config = tunnel.config or {}
        encrypted_psk = config.get("psk_encrypted")
        if not encrypted_psk:
            raise BadRequestError("IPsec tunnel is missing its pre-shared key")
        psk = decrypt_secret(str(encrypted_psk))
        local_wan = _device_wan(device)
        remote_wan = _device_wan(peer_device) or tunnel.endpoint_remote or ""
        local_lan = _lan_cidr(device)
        remote_lan = (
            _lan_cidr(peer_device) if peer_device is not None else ", ".join(tunnel.allowed_ips or [])
        )

        phase1 = {
            "enabled": "1",
            "descr": _descr(tunnel),
            "iketype": str(config.get("iketype", "ikev2")),
            "protocol": "esp",
            "interface": str(config.get("wan_interface", "wan")),
            "remote_gateway": remote_wan,
            "local_gateway": local_wan,
            "authentication_method": "pre_shared_key",
            "pre-shared-key": psk,
            "encryption": _as_list(config.get("encryption"), "aes256gcm16"),
            "hash": _as_list(config.get("hash"), "sha256"),
            "lifetime": str(config.get("lifetime", 28800)),
            "disabled": "0",
        }
        phase2 = {
            "enabled": "1",
            "descr": _descr(tunnel),
            "mode": "tunnel",
            "protocol": "esp",
            "local_net": local_lan,
            "remote_net": remote_lan,
            "encryption": _as_list(config.get("encryption"), "aes256gcm16"),
            "hash": _as_list(config.get("hash"), "sha256"),
            "pfs_group": str(config.get("pfs_group", 14)),
            "lifetime": str(config.get("lifetime", 3600)),
            "disabled": "0",
        }

        base_url, key, secret = await self.devices.credentials(device)
        async with client_for(base_url, key, secret) as client:
            changed = False
            phase1_uuid = None
            row = _find_managed(await client.search_ipsec_phase1(), "descr", _descr(tunnel))
            if row is not None and row.get("uuid"):
                phase1_uuid = str(row["uuid"])
                if needs_update(row, phase1):
                    await client.set_ipsec_phase1(phase1_uuid, phase1)
                    changed = True
            else:
                response = await client.add_ipsec_phase1(phase1)
                phase1_uuid = _response_ref(response, "uuid", "id")
                if phase1_uuid is None:
                    created = _find_managed(await client.search_ipsec_phase1(), "descr", _descr(tunnel))
                    phase1_uuid = str(created["uuid"]) if created and created.get("uuid") else None
                changed = True
            if not phase1_uuid:
                raise UpstreamError("Could not determine the IPsec phase1 identifier")

            phase2_payload = {**phase2, "phase1_uuid": phase1_uuid}
            existing_phase2 = _find_managed(await client.search_ipsec_phase2(), "descr", _descr(tunnel))
            if existing_phase2 is not None and existing_phase2.get("uuid"):
                if needs_update(existing_phase2, phase2_payload):
                    await client.set_ipsec_phase2(str(existing_phase2["uuid"]), phase2_payload)
                    changed = True
            else:
                await client.add_ipsec_phase2(phase2_payload)
                changed = True
            if changed:
                await client.apply_ipsec_phase1()
                await client.apply_ipsec()

    async def _apply_openvpn_endpoint(
        self,
        tunnel: VpnTunnel,
        device: Device,
        peer_device: Device | None,
        *,
        is_server: bool,
        ca: OpenVpnCa,
        certificate: OpenVpnCertificate,
    ) -> None:
        config = tunnel.config or {}
        port = int(config.get("openvpn_port", _DEFAULT_OPENVPN_PORT))
        network = str(config.get("openvpn_tunnel_network", _DEFAULT_OPENVPN_NETWORK))

        base_url, key, secret = await self.devices.credentials(device)
        async with client_for(base_url, key, secret) as client:
            ca_ref = await self._push_ca(client, ca)
            cert_ref = await self._push_certificate(client, certificate, ca_ref)
            if is_server:
                payload = {
                    "enabled": "1",
                    "role": "server",
                    "description": _descr(tunnel),
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
                    "keepalive_interval": str(tunnel.keepalive or 10),
                    "keepalive_timeout": "60",
                    "compression": "none",
                    "verb": "1",
                }
            else:
                remote_wan = _device_wan(peer_device) or tunnel.endpoint_remote or ""
                payload = {
                    "enabled": "1",
                    "role": "client",
                    "description": _descr(tunnel),
                    "dev": "tun",
                    "proto": "udp",
                    "remote": f"{remote_wan}:{port}",
                    "ca": ca_ref,
                    "cert": cert_ref,
                    "key": cert_ref,
                    "auth": "SHA256",
                    "cipher": "AES-256-GCM",
                    "digest": "SHA256",
                    "keepalive_interval": str(tunnel.keepalive or 10),
                    "keepalive_timeout": "60",
                    "compression": "none",
                    "verb": "1",
                }
            existing = await client.search_openvpn_instances()
            row = _find_managed(existing, "description", _descr(tunnel))
            if row is None:
                row = _find_managed(existing, "name", _descr(tunnel))
            if row is not None and row.get("uuid"):
                if needs_update(row, payload):
                    await client.set_openvpn_instance(str(row["uuid"]), payload)
                    await client.apply_openvpn()
            else:
                await client.add_openvpn_instance(payload)
                await client.apply_openvpn()

    async def _push_ca(self, client, ca: OpenVpnCa) -> str:
        row = _find_managed(await client.search_cas(), "descr", _ca_descr(ca))
        if row is not None:
            ref = str(row.get("refid") or row.get("uuid") or "")
            if ref:
                ca.ca_ref = ref
                return ref
        response = await client.add_ca(
            {
                "descr": _ca_descr(ca),
                "caref": ca.ca_ref or ca.id.hex[:8],
                "cert": ca.cert_pem,
                "prv": decrypt_secret(ca.key_encrypted),
            }
        )
        ref = _response_ref(response, "refid", "uuid", "caref")
        if ref and not response.get("refid"):
            row = _find_managed(await client.search_cas(), "descr", _ca_descr(ca))
            if row is not None:
                ref = str(row.get("refid") or ref)
        if not ref:
            raise UpstreamError("Could not determine the OpenVPN CA reference")
        ca.ca_ref = ref
        return ref

    async def _push_certificate(self, client, certificate: OpenVpnCertificate, ca_ref: str) -> str:
        row = _find_managed(await client.search_certificates(), "descr", _cert_descr(certificate))
        if row is not None:
            ref = str(row.get("refid") or row.get("uuid") or "")
            if ref:
                certificate.cert_ref = ref
                return ref
        response = await client.add_certificate(
            {
                "descr": _cert_descr(certificate),
                "caref": ca_ref,
                "cert": certificate.cert_pem,
                "prv": decrypt_secret(certificate.key_encrypted),
            }
        )
        ref = _response_ref(response, "refid", "uuid")
        if ref and not response.get("refid"):
            row = _find_managed(await client.search_certificates(), "descr", _cert_descr(certificate))
            if row is not None:
                ref = str(row.get("refid") or ref)
        if not ref:
            raise UpstreamError("Could not determine the OpenVPN certificate reference")
        certificate.cert_ref = ref
        return ref

    # ------------------------------------------------------------------ OpenVPN PKI
    async def _ensure_openvpn_ca(self, topology: SdwanTopology) -> OpenVpnCa:
        ca = await self.uow.openvpn_cas.for_topology(topology.id)
        if ca is not None:
            return ca
        common_name = f"OFME {topology.name} CA"
        cert_pem, key_pem = _generate_ca(common_name)
        ca = OpenVpnCa(
            tenant_id=self.tenant_id,
            topology_id=topology.id,
            common_name=common_name,
            cert_pem=cert_pem,
            key_encrypted=encrypt_secret(key_pem),
        )
        self.session.add(ca)
        await self.session.flush()
        return ca

    async def _ensure_openvpn_certificate(
        self, topology: SdwanTopology, ca: OpenVpnCa, device: Device
    ) -> OpenVpnCertificate:
        certificate = await self.uow.openvpn_certificates.for_device(topology.id, device.id)
        if certificate is not None:
            return certificate
        common_name = f"{_slug(device.name)}-{topology.id.hex[:6]}"
        cert_pem, key_pem = _generate_certificate(ca.cert_pem, decrypt_secret(ca.key_encrypted), common_name)
        certificate = OpenVpnCertificate(
            tenant_id=self.tenant_id,
            topology_id=topology.id,
            device_id=device.id,
            common_name=common_name,
            cert_pem=cert_pem,
            key_encrypted=encrypt_secret(key_pem),
            ca_ref=ca.ca_ref,
        )
        self.session.add(certificate)
        await self.session.flush()
        return certificate

    @staticmethod
    def _openvpn_server_device(
        topology: SdwanTopology, local_device: Device, remote_device: Device | None
    ) -> Device:
        if remote_device is None:
            return local_device
        hubs = {uuid.UUID(str(hub)) for hub in (topology.hub_device_ids or []) if hub}
        if remote_device.id in hubs:
            return remote_device
        if local_device.id in hubs:
            return local_device
        return min((local_device, remote_device), key=lambda device: str(device.id))


class VpnStatusService:
    """Poll VPN state from both ends of every tunnel in a topology."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.devices = DeviceService(session, tenant_id)

    async def refresh(self, topology_id: uuid.UUID) -> VpnStatusOut:
        topology = await self.uow.topologies.get_or_404(topology_id)
        tunnels = await self.uow.tunnels.for_topology(topology_id)
        device_ids: set[uuid.UUID] = set()
        for tunnel in tunnels:
            device_ids.add(tunnel.local_device_id)
            if tunnel.remote_device_id:
                device_ids.add(tunnel.remote_device_id)

        snapshots: dict[uuid.UUID, dict[str, Any]] = {}
        names: dict[uuid.UUID, str] = {}
        errors: list[str] = []
        for device_id in device_ids:
            device = await self.uow.devices.get(device_id)
            if device is None:
                continue
            names[device_id] = device.name
            try:
                base_url, key, secret = await self.devices.credentials(device)
                async with client_for(base_url, key, secret) as client:
                    snapshots[device_id] = {
                        "wireguard": await client.search_wireguard_servers(),
                        "openvpn": await client.search_openvpn_instances(),
                        "ipsec": await client.search_ipsec_phase1(),
                        "sessions": await client.ipsec_sessions(),
                    }
            except Exception as exc:  # noqa: BLE001 - status polling is best effort
                snapshots[device_id] = {"error": str(exc)}
                errors.append(f"{device.name}: {exc}")

        results: list[VpnTunnelStatus] = []
        for tunnel in tunnels:
            endpoints: list[VpnEndpointStatus] = []
            status = TunnelStatus.DOWN
            for device_id in (tunnel.local_device_id, tunnel.remote_device_id):
                if device_id is None:
                    continue
                snapshot = snapshots.get(device_id) or {"error": "device not polled"}
                endpoint = self._endpoint_status(tunnel, device_id, names.get(device_id), snapshot)
                endpoints.append(endpoint)
                if endpoint.state == TunnelStatus.ACTIVE.value:
                    status = TunnelStatus.ACTIVE
            tunnel.status = status
            tunnel.health_status = (
                HealthStatus.HEALTHY if status == TunnelStatus.ACTIVE else HealthStatus.UNHEALTHY
            )
            handshakes = [
                endpoint.last_handshake_at for endpoint in endpoints if endpoint.last_handshake_at is not None
            ]
            if handshakes:
                tunnel.last_handshake_at = max(handshakes)
            results.append(
                VpnTunnelStatus(
                    tunnel_id=tunnel.id,
                    name=tunnel.name,
                    protocol=tunnel.protocol,
                    status=status,
                    endpoints=endpoints,
                )
            )
        await self.session.flush()
        return VpnStatusOut(
            topology_id=topology.id,
            generated_at=datetime.now(UTC),
            tunnels=results,
            errors=errors,
        )

    def _endpoint_status(
        self,
        tunnel: VpnTunnel,
        device_id: uuid.UUID,
        device_name: str | None,
        snapshot: dict[str, Any],
    ) -> VpnEndpointStatus:
        if snapshot.get("error"):
            return VpnEndpointStatus(
                device_id=device_id,
                device=device_name,
                state="unreachable",
                details={"error": snapshot["error"]},
            )

        if tunnel.protocol == VpnProtocol.WIREGUARD:
            payload = snapshot.get("wireguard")
            row = _match_row(payload, "name", tunnel.interface_name)
            if row is None:
                row = _match_row(payload, "descr", _descr(tunnel))
            if row is None:
                return VpnEndpointStatus(device_id=device_id, device=device_name, state="not_configured")
            handshake = _latest_handshake(row)
            fresh = (
                handshake is not None
                and (datetime.now(UTC) - handshake).total_seconds() < _HANDSHAKE_FRESH_SECONDS
            )
            return VpnEndpointStatus(
                device_id=device_id,
                device=device_name,
                state=TunnelStatus.ACTIVE.value if fresh else TunnelStatus.DOWN.value,
                last_handshake_at=handshake,
                details={"name": row.get("name"), "enabled": row.get("enabled")},
            )

        if tunnel.protocol == VpnProtocol.OPENVPN:
            payload = snapshot.get("openvpn")
            row = _match_row(payload, "description", _descr(tunnel))
            if row is None:
                row = _match_row(payload, "name", _descr(tunnel))
            if row is None:
                return VpnEndpointStatus(device_id=device_id, device=device_name, state="not_configured")
            state = str(row.get("status") or row.get("state") or "").lower()
            active = state in {"up", "connected", "ok", "running", "1", "true"}
            return VpnEndpointStatus(
                device_id=device_id,
                device=device_name,
                state=TunnelStatus.ACTIVE.value if active else TunnelStatus.DOWN.value,
                details={"status": state or "unknown"},
            )

        payload = snapshot.get("ipsec")
        row = _match_row(payload, "descr", _descr(tunnel))
        if row is None:
            return VpnEndpointStatus(device_id=device_id, device=device_name, state="not_configured")
        sessions = snapshot.get("sessions")
        session = _match_row(sessions, "descr", _descr(tunnel))
        if session is None:
            session = _match_row(sessions, "name", _descr(tunnel))
        state = str((session or {}).get("status") or (session or {}).get("state") or "").lower()
        connected = state in {"up", "connected", "established", "installed", "1", "true"}
        return VpnEndpointStatus(
            device_id=device_id,
            device=device_name,
            state=TunnelStatus.ACTIVE.value if connected else TunnelStatus.DOWN.value,
            details={"phase1": row.get("descr"), "session": state or "unknown"},
        )


class RouteManager:
    """Maintains the SD-WAN route table and pushes it to devices."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.devices = DeviceService(session, tenant_id)

    async def sync_routes(self, topology_id: uuid.UUID, device_id: uuid.UUID) -> int:
        tunnels = await self.uow.tunnels.for_device(device_id)
        installed = 0
        for tunnel in tunnels:
            if tunnel.topology_id != topology_id:
                continue
            if tunnel.local_device_id == device_id:
                destinations = [str(cidr) for cidr in (tunnel.allowed_ips or [])]
            else:
                peer = await self.uow.devices.get(tunnel.local_device_id)
                destinations = [_lan_cidr(peer)] if peer is not None else []
            for cidr in destinations:
                existing = (
                    (
                        await self.session.execute(
                            select(SdwanRoute).where(
                                SdwanRoute.topology_id == topology_id,
                                SdwanRoute.device_id == device_id,
                                SdwanRoute.destination == str(cidr),
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if existing:
                    existing.tunnel_id = tunnel.id
                    existing.installed = tunnel.status == TunnelStatus.ACTIVE
                    existing.metric = 100
                else:
                    self.session.add(
                        SdwanRoute(
                            tenant_id=self.tenant_id,
                            topology_id=topology_id,
                            device_id=device_id,
                            destination=str(cidr),
                            next_hop=tunnel.endpoint_remote,
                            tunnel_id=tunnel.id,
                            metric=100,
                            protocol="static",
                            installed=tunnel.status == TunnelStatus.ACTIVE,
                            updated_at_dynamic=datetime.now(UTC),
                        )
                    )
                installed += 1
        await self.session.flush()
        return installed

    async def withdraw(self, tunnel_id: uuid.UUID) -> int:
        routes = (
            (await self.session.execute(select(SdwanRoute).where(SdwanRoute.tunnel_id == tunnel_id)))
            .scalars()
            .all()
        )
        for route in routes:
            route.installed = False
            route.tunnel_id = None
        await self.session.flush()
        return len(routes)


class SteeringService:
    """SLA-driven path selection with automatic failover."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)

    async def select_best_link(self, topology_id: uuid.UUID, strategy: SteeringStrategy) -> SdwanLink | None:
        links = await self.uow.links.eligible_for_steering(topology_id)
        healthy = [link for link in links if self._meets_sla(link)]
        if not healthy:
            return None
        if strategy == SteeringStrategy.LOWEST_LATENCY:
            return min(healthy, key=lambda link: link.latency_ms or 9999)
        if strategy == SteeringStrategy.LOWEST_LOSS:
            return min(healthy, key=lambda link: link.loss_pct or 100)
        if strategy == SteeringStrategy.LOWEST_COST:
            return min(healthy, key=lambda link: (link.cost, link.latency_ms or 9999))
        if strategy == SteeringStrategy.WEIGHTED:
            return max(healthy, key=lambda link: (link.bandwidth_mbps or 0) / max(link.cost, 1))
        return min(healthy, key=lambda link: (link.priority, link.latency_ms or 9999))

    @staticmethod
    def _meets_sla(link: SdwanLink) -> bool:
        if link.status != TunnelStatus.ACTIVE:
            return False
        if link.latency_ms is not None and link.latency_ms > link.sla_latency_ms:
            return False
        return link.loss_pct is None or link.loss_pct <= link.sla_loss_pct

    async def evaluate_failover(self, topology_id: uuid.UUID) -> list[dict]:
        policies = (
            (
                await self.session.execute(
                    select(TrafficPolicy).where(
                        TrafficPolicy.topology_id == topology_id, TrafficPolicy.enabled.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        events: list[dict] = []
        for policy in policies:
            best = await self.select_best_link(topology_id, policy.strategy)
            if best is None:
                continue
            preferred = policy.preferred_link_ids or []
            if preferred and str(best.id) not in {str(p) for p in preferred}:
                if str(preferred[0]) not in {str(p) for p in preferred if p}:
                    continue
                events.append(
                    {
                        "policy_id": str(policy.id),
                        "previous_link_id": str(preferred[0]),
                        "selected_link_id": str(best.id),
                        "reason": "sla_violation",
                    }
                )
        return events


class SdwanHealthService:
    """Ingest link telemetry, update status, emit events, trigger failover."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.steering = SteeringService(session, tenant_id)

    async def record(
        self,
        link_id: uuid.UUID,
        *,
        latency_ms: float | None = None,
        jitter_ms: float | None = None,
        loss_pct: float | None = None,
        bandwidth_mbps: float | None = None,
        status: TunnelStatus | None = None,
    ) -> SdwanLink:
        link = await self.uow.links.get_or_404(link_id)
        previous_status = link.status
        if latency_ms is not None:
            link.latency_ms = latency_ms
        if jitter_ms is not None:
            link.jitter_ms = jitter_ms
        if loss_pct is not None:
            link.loss_pct = loss_pct
        if bandwidth_mbps is not None:
            link.bandwidth_mbps = bandwidth_mbps
        if status is not None:
            link.status = status
        link.measured_at = datetime.now(UTC)

        if link.tunnel_id:
            tunnel = await self.uow.tunnels.get(link.tunnel_id)
            if tunnel:
                tunnel.health_status = self._health(link)
                if link.status != previous_status:
                    tunnel.status = link.status
                    await event_bus.publish(
                        TunnelStateChanged(
                            tunnel_id=str(tunnel.id),
                            tenant_id=str(self.tenant_id),
                            status=link.status.value,
                            topology_id=str(tunnel.topology_id),
                        )
                    )
        await self.session.flush()
        return link

    @staticmethod
    def _health(link: SdwanLink) -> HealthStatus:
        if link.status != TunnelStatus.ACTIVE:
            return HealthStatus.UNHEALTHY
        latency_ok = link.latency_ms is None or link.latency_ms <= link.sla_latency_ms
        loss_ok = link.loss_pct is None or link.loss_pct <= link.sla_loss_pct
        if latency_ok and loss_ok:
            return HealthStatus.HEALTHY
        return HealthStatus.DEGRADED
