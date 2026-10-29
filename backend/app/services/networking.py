"""DHCP scope/reservation and authoritative DNS record management.

All values are validated before they reach the database: a scope can only
describe a usable IPv4 pool inside its own subnet, a reservation must stay
inside the parent scope, and DNS records follow the per-type rules enforced by
BIND/Unbound. Every mutation is written to the immutable audit trail.
"""

from __future__ import annotations

import ipaddress
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.config import DhcpReservation, DhcpScope, DnsRecord
from app.models.enums import DnsRecordType
from app.repositories import UnitOfWork
from app.schemas.config import (
    DhcpReservationCreate,
    DhcpReservationUpdate,
    DhcpScopeCreate,
    DhcpScopeUpdate,
    DnsRecordCreate,
    DnsRecordUpdate,
)
from app.services.audit import AuditService

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?$")
_HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_HOSTNAME_TYPES = frozenset(
    {DnsRecordType.CNAME, DnsRecordType.MX, DnsRecordType.SRV, DnsRecordType.PTR, DnsRecordType.NS}
)


def _normalise_name(raw: str) -> str:
    """Lower-case a DNS owner name and reject labels Unbound cannot load."""
    candidate = raw.strip().rstrip(".")
    if candidate in {"", "@"}:
        return "@"
    wildcard = candidate.startswith("*.")
    if wildcard:
        candidate = candidate[2:]
    if not candidate or len(candidate) > 253:
        raise BadRequestError(f"Invalid DNS name '{raw}'")
    for label in candidate.split("."):
        if not _LABEL_RE.fullmatch(label):
            raise BadRequestError(f"Invalid DNS name '{raw}'")
    normalised = candidate.lower()
    return f"*.{normalised}" if wildcard else normalised


def _is_hostname(value: str) -> bool:
    candidate = value.strip().rstrip(".")
    if not candidate or len(candidate) > 253:
        return False
    return all(_HOST_LABEL_RE.fullmatch(label) for label in candidate.split("."))


def _normalise_mac(raw: str) -> str:
    if not _MAC_RE.fullmatch(raw.strip()):
        raise BadRequestError(f"Invalid MAC address '{raw}'")
    return raw.strip().lower().replace("-", ":")


def _validate_scope_values(
    *,
    subnet: str,
    pool_start: str,
    pool_end: str,
    gateway: str | None,
    dns_servers: list[str],
    domain_name: str | None,
) -> dict[str, object]:
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError as exc:
        raise BadRequestError(f"Invalid subnet '{subnet}'") from exc
    if network.version != 4:
        raise BadRequestError("DHCP scopes currently support IPv4 subnets only")
    if network.prefixlen > 30:
        raise BadRequestError("DHCP subnet must be /30 or larger to contain a usable pool")

    try:
        start = ipaddress.IPv4Address(pool_start)
        end = ipaddress.IPv4Address(pool_end)
    except ValueError as exc:
        raise BadRequestError("Lease pool bounds must be IPv4 addresses") from exc

    for address in (start, end):
        if address not in network:
            raise BadRequestError(f"Pool address {address} is outside {network}")
        if address in {network.network_address, network.broadcast_address}:
            raise BadRequestError(f"Pool address {address} is the network or broadcast address")
    if int(start) > int(end):
        raise BadRequestError("Pool start must not be greater than pool end")

    normalised_gateway: str | None = None
    if gateway:
        try:
            gateway_address = ipaddress.IPv4Address(gateway)
        except ValueError as exc:
            raise BadRequestError(f"Invalid gateway '{gateway}'") from exc
        if gateway_address not in network:
            raise BadRequestError(f"Gateway {gateway_address} is outside {network}")
        if int(start) <= int(gateway_address) <= int(end):
            raise BadRequestError("Gateway must not be inside the dynamic lease pool")
        normalised_gateway = str(gateway_address)

    for server in dns_servers:
        try:
            ipaddress.ip_address(server)
        except ValueError as exc:
            raise BadRequestError(f"Invalid DNS server address '{server}'") from exc

    if domain_name and not _is_hostname(domain_name):
        raise BadRequestError(f"Invalid domain name '{domain_name}'")

    return {
        "subnet": str(network),
        "pool_start": str(start),
        "pool_end": str(end),
        "gateway": normalised_gateway,
    }


def _validate_dns_record(
    record_type: DnsRecordType,
    value: str,
    priority: int | None,
    weight: int | None,
    port: int | None,
) -> tuple[str, int | None, int | None, int | None]:
    candidate = value.strip()
    if not candidate:
        raise BadRequestError("DNS record value must not be empty")

    if record_type == DnsRecordType.A:
        try:
            ipaddress.IPv4Address(candidate)
        except ValueError as exc:
            raise BadRequestError(f"'{candidate}' is not a valid IPv4 address") from exc
        return candidate, None, None, None
    if record_type == DnsRecordType.AAAA:
        try:
            ipaddress.IPv6Address(candidate)
        except ValueError as exc:
            raise BadRequestError(f"'{candidate}' is not a valid IPv6 address") from exc
        return candidate, None, None, None
    if record_type == DnsRecordType.TXT:
        if len(candidate) > 4096:
            raise BadRequestError("TXT record value exceeds 4096 characters")
        return candidate, None, None, None
    if record_type in _HOSTNAME_TYPES:
        if not _is_hostname(candidate):
            raise BadRequestError(f"'{candidate}' is not a valid host name")
        candidate = candidate.rstrip(".").lower()
    if record_type == DnsRecordType.MX:
        if priority is None:
            raise BadRequestError("MX records require a priority")
        return candidate, priority, None, None
    if record_type == DnsRecordType.SRV:
        if priority is None or weight is None or port is None:
            raise BadRequestError("SRV records require priority, weight and port")
        return candidate, priority, weight, port
    return candidate, None, None, None


class DhcpScopeService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, payload: DhcpScopeCreate) -> DhcpScope:
        await self._ensure_device(payload.device_id)
        values = payload.model_dump()
        values.update(
            _validate_scope_values(
                subnet=payload.subnet,
                pool_start=payload.pool_start,
                pool_end=payload.pool_end,
                gateway=payload.gateway,
                dns_servers=payload.dns_servers,
                domain_name=payload.domain_name,
            )
        )
        if await self.uow.dhcp_scopes.find_one(device_id=payload.device_id, name=payload.name):
            raise ConflictError(f"DHCP scope '{payload.name}' already exists on this device")
        if await self.uow.dhcp_scopes.find_one(device_id=payload.device_id, subnet=values["subnet"]):
            raise ConflictError(f"Subnet {values['subnet']} already has a DHCP scope on this device")

        scope = DhcpScope(tenant_id=self.tenant_id, created_by=self.actor_id, **values)
        self.session.add(scope)
        await self.session.flush()
        await self.audit.record(
            action="dhcp.scope.created",
            resource_type="DhcpScope",
            resource_id=scope.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "name": scope.name,
                "device_id": str(scope.device_id),
                "subnet": scope.subnet,
                "pool": f"{scope.pool_start}-{scope.pool_end}",
            },
        )
        return scope

    async def update(self, scope_id: uuid.UUID, payload: DhcpScopeUpdate) -> DhcpScope:
        scope = await self.uow.dhcp_scopes.get_or_404(scope_id)
        data = payload.model_dump(exclude_unset=True)
        for field in ("pool_start", "pool_end"):
            if field in data and data[field] is None:
                raise BadRequestError(f"{field} cannot be null")
        before = {
            "pool_start": scope.pool_start,
            "pool_end": scope.pool_end,
            "gateway": scope.gateway,
            "enabled": scope.enabled,
        }
        normalised = _validate_scope_values(
            subnet=scope.subnet,
            pool_start=data.get("pool_start", scope.pool_start),
            pool_end=data.get("pool_end", scope.pool_end),
            gateway=data.get("gateway", scope.gateway),
            dns_servers=data.get("dns_servers", scope.dns_servers),
            domain_name=data.get("domain_name", scope.domain_name),
        )
        data.update(normalised)
        for field, value in data.items():
            setattr(scope, field, value)
        await self.session.flush()
        await self.audit.record(
            action="dhcp.scope.updated",
            resource_type="DhcpScope",
            resource_id=scope.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before=before,
            after={
                "pool_start": scope.pool_start,
                "pool_end": scope.pool_end,
                "gateway": scope.gateway,
                "enabled": scope.enabled,
            },
        )
        return scope

    async def delete(self, scope_id: uuid.UUID) -> int:
        scope = await self.uow.dhcp_scopes.get_or_404(scope_id)
        reservations = await self.uow.dhcp_reservations.for_scope(scope.id)
        for reservation in reservations:
            await self.uow.dhcp_reservations.delete(reservation)
        await self.uow.dhcp_scopes.delete(scope)
        await self.audit.record(
            action="dhcp.scope.deleted",
            resource_type="DhcpScope",
            resource_id=scope.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before={"name": scope.name, "subnet": scope.subnet},
            after={"reservations_deleted": len(reservations)},
        )
        return len(reservations)

    async def _ensure_device(self, device_id: uuid.UUID) -> None:
        if await self.uow.devices.get(device_id) is None:
            raise NotFoundError("Device not found")


class DhcpReservationService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, payload: DhcpReservationCreate) -> DhcpReservation:
        scope = await self.uow.dhcp_scopes.get_or_404(payload.scope_id)
        ip_address = self._validate_ip(scope, payload.ip_address)
        mac_address = _normalise_mac(payload.mac_address)
        self._validate_hostname(payload.hostname)
        await self._assert_unique(scope.id, mac_address, ip_address)

        reservation = DhcpReservation(
            tenant_id=self.tenant_id,
            device_id=scope.device_id,
            scope_id=scope.id,
            hostname=payload.hostname.strip(),
            mac_address=mac_address,
            ip_address=ip_address,
            description=payload.description,
            enabled=payload.enabled,
            created_by=self.actor_id,
        )
        self.session.add(reservation)
        await self.session.flush()
        await self.audit.record(
            action="dhcp.reservation.created",
            resource_type="DhcpReservation",
            resource_id=reservation.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "scope_id": str(scope.id),
                "hostname": reservation.hostname,
                "mac_address": reservation.mac_address,
                "ip_address": reservation.ip_address,
            },
        )
        return reservation

    async def update(self, reservation_id: uuid.UUID, payload: DhcpReservationUpdate) -> DhcpReservation:
        reservation = await self.uow.dhcp_reservations.get_or_404(reservation_id)
        scope = await self.uow.dhcp_scopes.get_or_404(reservation.scope_id)
        data = payload.model_dump(exclude_unset=True)
        for field in ("hostname", "mac_address", "ip_address"):
            if field in data and data[field] is None:
                raise BadRequestError(f"{field} cannot be null")

        mac_address = (
            _normalise_mac(data["mac_address"]) if "mac_address" in data else reservation.mac_address
        )
        ip_address = (
            self._validate_ip(scope, data["ip_address"]) if "ip_address" in data else reservation.ip_address
        )
        hostname = data.get("hostname", reservation.hostname)
        self._validate_hostname(hostname)
        await self._assert_unique(scope.id, mac_address, ip_address, exclude_id=reservation.id)

        before = {
            "hostname": reservation.hostname,
            "mac_address": reservation.mac_address,
            "ip_address": reservation.ip_address,
            "enabled": reservation.enabled,
        }
        reservation.hostname = hostname.strip()
        reservation.mac_address = mac_address
        reservation.ip_address = ip_address
        if "description" in data:
            reservation.description = data["description"]
        if "enabled" in data:
            reservation.enabled = data["enabled"]
        await self.session.flush()
        await self.audit.record(
            action="dhcp.reservation.updated",
            resource_type="DhcpReservation",
            resource_id=reservation.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before=before,
            after={
                "hostname": reservation.hostname,
                "mac_address": reservation.mac_address,
                "ip_address": reservation.ip_address,
                "enabled": reservation.enabled,
            },
        )
        return reservation

    async def delete(self, reservation_id: uuid.UUID) -> None:
        reservation = await self.uow.dhcp_reservations.get_or_404(reservation_id)
        await self.uow.dhcp_reservations.delete(reservation)
        await self.audit.record(
            action="dhcp.reservation.deleted",
            resource_type="DhcpReservation",
            resource_id=reservation.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before={
                "hostname": reservation.hostname,
                "mac_address": reservation.mac_address,
                "ip_address": reservation.ip_address,
            },
        )

    async def _assert_unique(
        self,
        scope_id: uuid.UUID,
        mac_address: str,
        ip_address: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        for peer in await self.uow.dhcp_reservations.for_scope(scope_id):
            if peer.id == exclude_id:
                continue
            if peer.mac_address == mac_address:
                raise ConflictError(f"MAC address {mac_address} is already reserved in this scope")
            if peer.ip_address == ip_address:
                raise ConflictError(f"IP address {ip_address} is already reserved in this scope")

    @staticmethod
    def _validate_ip(scope: DhcpScope, raw: str) -> str:
        try:
            network = ipaddress.ip_network(scope.subnet, strict=False)
            address = ipaddress.IPv4Address(raw)
        except ValueError as exc:
            raise BadRequestError(f"Invalid reservation address '{raw}'") from exc
        if address not in network:
            raise BadRequestError(f"Reservation address {address} is outside {scope.subnet}")
        if address in {network.network_address, network.broadcast_address}:
            raise BadRequestError(f"Reservation address {address} is the network or broadcast address")
        if scope.gateway and str(address) == scope.gateway:
            raise BadRequestError("Reservation address must not equal the scope gateway")
        return str(address)

    @staticmethod
    def _validate_hostname(raw: str) -> None:
        hostname = raw.strip()
        if not hostname or len(hostname) > 253:
            raise BadRequestError("Reservation hostname must be 1-253 characters")
        if not all(_HOST_LABEL_RE.fullmatch(label) for label in hostname.rstrip(".").split(".")):
            raise BadRequestError(f"Invalid reservation hostname '{raw}'")


class DnsRecordService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, payload: DnsRecordCreate) -> DnsRecord:
        await self._ensure_device(payload.device_id)
        name = _normalise_name(payload.name)
        value, priority, weight, port = _validate_dns_record(
            payload.record_type, payload.value, payload.priority, payload.weight, payload.port
        )
        await self._assert_unique(payload.device_id, name, payload.record_type, value)
        await self._assert_cname_exclusive(payload.device_id, name, payload.record_type)

        record = DnsRecord(
            tenant_id=self.tenant_id,
            device_id=payload.device_id,
            name=name,
            record_type=payload.record_type,
            value=value,
            ttl=payload.ttl,
            priority=priority,
            weight=weight,
            port=port,
            description=payload.description,
            enabled=payload.enabled,
            created_by=self.actor_id,
        )
        self.session.add(record)
        await self.session.flush()
        await self.audit.record(
            action="dns.record.created",
            resource_type="DnsRecord",
            resource_id=record.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "device_id": str(record.device_id),
                "name": record.name,
                "record_type": record.record_type.value,
                "value": record.value,
            },
        )
        return record

    async def update(self, record_id: uuid.UUID, payload: DnsRecordUpdate) -> DnsRecord:
        record = await self.uow.dns_records.get_or_404(record_id)
        data = payload.model_dump(exclude_unset=True)
        if "value" in data and data["value"] is None:
            raise BadRequestError("value cannot be null")

        value, priority, weight, port = _validate_dns_record(
            record.record_type,
            data.get("value", record.value),
            data.get("priority", record.priority),
            data.get("weight", record.weight),
            data.get("port", record.port),
        )
        await self._assert_unique(
            record.device_id, record.name, record.record_type, value, exclude_id=record.id
        )
        await self._assert_cname_exclusive(
            record.device_id, record.name, record.record_type, exclude_id=record.id
        )

        before = {
            "value": record.value,
            "ttl": record.ttl,
            "priority": record.priority,
            "weight": record.weight,
            "port": record.port,
            "enabled": record.enabled,
        }
        record.value = value
        record.priority = priority
        record.weight = weight
        record.port = port
        if "ttl" in data:
            record.ttl = data["ttl"]
        if "description" in data:
            record.description = data["description"]
        if "enabled" in data:
            record.enabled = data["enabled"]
        await self.session.flush()
        await self.audit.record(
            action="dns.record.updated",
            resource_type="DnsRecord",
            resource_id=record.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before=before,
            after={
                "value": record.value,
                "ttl": record.ttl,
                "priority": record.priority,
                "weight": record.weight,
                "port": record.port,
                "enabled": record.enabled,
            },
        )
        return record

    async def delete(self, record_id: uuid.UUID) -> None:
        record = await self.uow.dns_records.get_or_404(record_id)
        await self.uow.dns_records.delete(record)
        await self.audit.record(
            action="dns.record.deleted",
            resource_type="DnsRecord",
            resource_id=record.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before={
                "name": record.name,
                "record_type": record.record_type.value,
                "value": record.value,
            },
        )

    async def _assert_unique(
        self,
        device_id: uuid.UUID,
        name: str,
        record_type: DnsRecordType,
        value: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        for peer in await self.uow.dns_records.for_name(device_id, name):
            if peer.id == exclude_id:
                continue
            if peer.record_type == record_type and peer.value == value:
                raise ConflictError(f"{record_type.value} record {name} -> {value} already exists")

    async def _assert_cname_exclusive(
        self,
        device_id: uuid.UUID,
        name: str,
        record_type: DnsRecordType,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        for peer in await self.uow.dns_records.for_name(device_id, name):
            if peer.id == exclude_id:
                continue
            if peer.record_type == DnsRecordType.CNAME or record_type == DnsRecordType.CNAME:
                raise ConflictError(f"CNAME {name} cannot coexist with other records for the same owner name")

    async def _ensure_device(self, device_id: uuid.UUID) -> None:
        if await self.uow.devices.get(device_id) is None:
            raise NotFoundError("Device not found")
