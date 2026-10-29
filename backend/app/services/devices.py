"""Device registry, discovery, heartbeat ingest, monitoring and certificate lifecycle."""

from __future__ import annotations

import asyncio
import ipaddress
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import DeviceRegistered, DeviceStatusChanged, event_bus
from app.core.exceptions import BadRequestError, ConflictError, LicenseLimitError, NotFoundError
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret
from app.models.enums import (
    CertificateStatus,
    ConnectionStatus,
    DeviceStatus,
    MetricType,
)
from app.models.identity import Tenant
from app.models.metrics import DeviceMetric, DeviceTelemetrySnapshot
from app.models.topology import Device, DeviceCertificate
from app.repositories import UnitOfWork
from app.schemas.topology import CommandResultPayload, DeviceCreate, DeviceUpdate, HeartbeatPayload
from app.services.audit import AuditService
from app.services.notifications import NotificationService
from app.services.traffic import normalise_counters, rate_points

log = get_logger("ofme.devices")


@dataclass(slots=True)
class DiscoveryCandidate:
    ip_address: str
    port: int
    hostname: str | None
    firmware_version: str | None
    serial_number: str | None
    reachable: bool
    already_managed: bool = False


COMMAND_ACTIONS: frozenset[str] = frozenset(
    {
        "noop",
        "ping",
        "sync_config",
        "renew_certificate",
        "restart_agent",
        "collect_diagnostics",
        "reload_firewall",
        "update_telemetry",
        "firmware_upgrade",
        "firmware_reboot",
    }
)
MAX_PENDING_COMMANDS = 50
MAX_COMMAND_HISTORY = 200


def _merge_command_results(device: Device, results: list[CommandResultPayload], received_at: datetime) -> int:
    """Merge command results into device metadata and clear matching pending commands."""
    if not results:
        return 0

    metadata = dict(device.metadata_ or {})
    pending = [item for item in (metadata.get("pending_commands") or []) if isinstance(item, dict)]
    history = [item for item in (metadata.get("command_history") or []) if isinstance(item, dict)]

    completed: set[str] = set()
    positions = {str(entry.get("id")): index for index, entry in enumerate(history)}
    for result in results:
        identifier = str(result.id)
        completed.add(identifier)
        entry = result.model_dump(mode="json", exclude_none=True)
        entry["received_at"] = received_at.isoformat()
        if identifier in positions:
            history[positions[identifier]] = entry
        else:
            positions[identifier] = len(history)
            history.append(entry)

    metadata["pending_commands"] = [item for item in pending if str(item.get("id")) not in completed]
    metadata["command_history"] = history[-MAX_COMMAND_HISTORY:]
    metadata["last_command_result_at"] = received_at.isoformat()
    device.metadata_ = metadata
    return len(results)


class DeviceService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session, tenant_id)

    async def create(self, payload: DeviceCreate) -> Device:
        if await self.uow.devices.get_by_name(payload.name):
            raise ConflictError(f"Device '{payload.name}' already exists")
        await self._enforce_device_limit()

        device = Device(
            tenant_id=self.tenant_id,
            name=payload.name,
            site_id=payload.site_id,
            group_id=payload.group_id,
            hostname=payload.hostname,
            description=payload.description,
            ip_address=payload.ip_address,
            api_port=payload.api_port,
            serial_number=payload.serial_number,
            model=payload.model,
            is_ha=payload.is_ha,
            ha_role=payload.ha_role,
            tags=payload.tags,
            status=DeviceStatus.REGISTERED,
        )
        if payload.api_key:
            device.api_key_encrypted = encrypt_secret(payload.api_key)
        if payload.api_secret:
            device.api_secret_encrypted = encrypt_secret(payload.api_secret)
        if payload.api_key and payload.api_secret:
            device.connection_status = ConnectionStatus.UNKNOWN
        self.session.add(device)
        await self.session.flush()

        await self.audit.record(
            action="device.created",
            resource_type="Device",
            resource_id=device.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": device.name, "site_id": str(device.site_id) if device.site_id else None},
        )
        await event_bus.publish(
            DeviceRegistered(
                device_id=str(device.id),
                tenant_id=str(self.tenant_id),
                name=device.name,
                serial_number=device.serial_number,
            )
        )
        return device

    async def _enforce_device_limit(self) -> None:
        tenant = await self.session.get(Tenant, self.tenant_id)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        count = await self.uow.devices.count()
        if count >= tenant.device_limit:
            raise LicenseLimitError(
                f"Device limit reached ({tenant.device_limit}). Upgrade the tenant licence to add devices."
            )

    async def update(self, device_id: uuid.UUID, payload: DeviceUpdate) -> Device:
        device = await self.uow.devices.get_or_404(device_id)
        before = {
            "name": device.name,
            "site_id": str(device.site_id) if device.site_id else None,
            "tags": list(device.tags or []),
        }
        data = payload.model_dump(exclude_unset=True)
        api_key = data.pop("api_key", None)
        api_secret = data.pop("api_secret", None)
        for field, value in data.items():
            setattr(device, field, value)
        if api_key:
            device.api_key_encrypted = encrypt_secret(api_key)
        if api_secret:
            device.api_secret_encrypted = encrypt_secret(api_secret)

        await self.session.flush()
        await self.audit.record(
            action="device.updated",
            resource_type="Device",
            resource_id=device.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before=before,
            after={k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in data.items()},
        )
        return device

    async def delete(self, device_id: uuid.UUID) -> None:
        device = await self.uow.devices.get_or_404(device_id)
        await self.uow.devices.delete(device)
        await self.audit.record(
            action="device.deleted",
            resource_type="Device",
            resource_id=device.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before={"name": device.name, "serial": device.serial_number},
        )

    async def get(self, device_id: uuid.UUID) -> Device:
        device = await self.uow.devices.get(device_id)
        if device is None:
            raise NotFoundError("Device not found")
        return device

    async def list(
        self,
        *,
        page: int = 1,
        size: int = 50,
        search: str | None = None,
        site_id: uuid.UUID | None = None,
        group_id: uuid.UUID | None = None,
        status: str | None = None,
        sort: str = "created_at",
        order: str = "desc",
    ) -> tuple[list[Device], int]:
        filters = {"site_id": site_id, "group_id": group_id}
        if status:
            filters["status"] = status
        return await self.uow.devices.list(
            filters=filters,
            search=search,
            search_fields=("name", "hostname", "ip_address", "serial_number"),
            page=page,
            size=size,
            sort=sort,
            order=order,
        )

    async def credentials(self, device: Device) -> tuple[str, str, str]:
        if not device.ip_address or not device.api_key_encrypted or not device.api_secret_encrypted:
            raise BadRequestError(f"Device '{device.name}' has no OPNsense API credentials configured")
        base_url = f"https://{device.ip_address}:{device.api_port}"
        return base_url, decrypt_secret(device.api_key_encrypted), decrypt_secret(device.api_secret_encrypted)

    async def summary(self) -> dict[str, int]:
        counts = await self.uow.devices.by_status_counts()
        total = sum(counts.values())
        return {
            "total": total,
            "online": counts.get(DeviceStatus.ONLINE.value, 0),
            "offline": counts.get(DeviceStatus.OFFLINE.value, 0),
            "error": counts.get(DeviceStatus.ERROR.value, 0),
            "maintenance": counts.get(DeviceStatus.MAINTENANCE.value, 0),
            "unregistered": counts.get(DeviceStatus.UNREGISTERED.value, 0),
        }

    async def mark_maintenance(self, device_id: uuid.UUID, enabled: bool) -> Device:
        device = await self.uow.devices.get_or_404(device_id)
        previous = device.status
        device.status = DeviceStatus.MAINTENANCE if enabled else DeviceStatus.REGISTERED
        await self.session.flush()
        await event_bus.publish(
            DeviceStatusChanged(
                device_id=str(device.id),
                tenant_id=str(self.tenant_id),
                status=device.status.value,
                previous=previous.value,
            )
        )
        return device


class HeartbeatService:
    """Ingest agent heartbeats idempotently and fan out telemetry."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)

    async def ingest(self, device_id: uuid.UUID, payload: HeartbeatPayload) -> Device:
        device = await self.uow.devices.record_heartbeat(
            device_id,
            firmware_version=payload.firmware_version,
            hostname=payload.hostname,
            uptime_seconds=payload.uptime_seconds,
            agent_version=payload.agent_version,
        )
        now = datetime.now(UTC)

        snapshot = await self.uow.snapshots.for_device(device.id)
        if snapshot is None:
            snapshot = DeviceTelemetrySnapshot(tenant_id=self.tenant_id, device_id=device.id)
            self.session.add(snapshot)

        traffic_sample = normalise_counters(
            payload.traffic.model_dump() if payload.traffic is not None else None
        )
        traffic_rates = rate_points(snapshot.traffic, snapshot.traffic_at, traffic_sample, now)

        snapshot.cpu_pct = payload.cpu_pct
        snapshot.memory_pct = payload.memory_pct
        snapshot.disk_pct = payload.disk_pct
        snapshot.load_1m = payload.load_1m
        snapshot.sessions = payload.sessions
        snapshot.uptime_seconds = payload.uptime_seconds
        snapshot.vpn_up = payload.vpn_up
        snapshot.vpn_total = payload.vpn_total
        snapshot.gateways_up = payload.gateways_up
        snapshot.gateways_total = payload.gateways_total
        snapshot.carp_status = payload.carp_status
        snapshot.interfaces = payload.interfaces
        if traffic_sample is not None:
            # Keep the last good counters when a heartbeat omits traffic, so the
            # next sample still has a baseline.
            snapshot.traffic = traffic_sample
            snapshot.traffic_at = now
        snapshot.recorded_at = now

        if payload.command_results:
            _merge_command_results(device, payload.command_results, now)

        metric_rows = [
            (MetricType.CPU, payload.cpu_pct, "%"),
            (MetricType.MEMORY, payload.memory_pct, "%"),
            (MetricType.DISK, payload.disk_pct, "%"),
            (MetricType.LOAD, payload.load_1m, None),
            (MetricType.SESSIONS, float(payload.sessions) if payload.sessions is not None else None, "count"),
            (
                MetricType.UPTIME,
                float(payload.uptime_seconds) if payload.uptime_seconds is not None else None,
                "s",
            ),
            (MetricType.VPN, float(payload.vpn_up) if payload.vpn_up is not None else None, "tunnels"),
            (
                MetricType.GATEWAY,
                float(payload.gateways_up) if payload.gateways_up is not None else None,
                "gateways",
            ),
        ]
        for metric_type, value, unit in metric_rows:
            if value is None:
                continue
            self.session.add(
                DeviceMetric(
                    tenant_id=self.tenant_id,
                    device_id=device.id,
                    metric_type=metric_type,
                    value=float(value),
                    unit=unit,
                    labels={"hostname": device.hostname or device.name},
                    recorded_at=now,
                )
            )

        for rate in traffic_rates:
            self.session.add(
                DeviceMetric(
                    tenant_id=self.tenant_id,
                    device_id=device.id,
                    metric_type=MetricType.TRAFFIC,
                    value=rate["bps"],
                    unit="bps",
                    labels={
                        "hostname": device.hostname or device.name,
                        "interface": rate["interface"],
                        "name": rate["name"],
                        "direction": rate["direction"],
                    },
                    recorded_at=now,
                )
            )

        # Ingest inventory data (ARP/DHCP/LLDP) if present
        if payload.arp or payload.dhcp_leases or payload.lldp:
            from app.services.inventory import InventoryIngestService

            ingest_service = InventoryIngestService(self.session, self.tenant_id)
            await ingest_service.ingest(
                device_id=device.id,
                arp_data=payload.arp,
                dhcp_data=payload.dhcp_leases,
                lldp_data=payload.lldp,
            )

        await self.session.flush()
        from app.services.monitoring import AlertEvaluator

        await AlertEvaluator(self.session, self.tenant_id).evaluate_device(device, payload)
        await self.session.commit()
        return device


class DeviceCommandService:
    """Queue and inspect whitelisted operational commands for a device."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        actor: str | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.actor = actor
        self.uow = UnitOfWork(session, tenant_id)

    async def dispatch(
        self,
        device_id: uuid.UUID,
        action: str,
        payload: dict | None = None,
    ) -> dict:
        if action not in COMMAND_ACTIONS:
            raise BadRequestError(f"Unsupported device command: {action}")

        device = await self.uow.devices.get_or_404(device_id)
        metadata = dict(device.metadata_ or {})
        pending = [item for item in (metadata.get("pending_commands") or []) if isinstance(item, dict)]
        if len(pending) >= MAX_PENDING_COMMANDS:
            raise BadRequestError(f"The device already has {MAX_PENDING_COMMANDS} pending commands")

        now = datetime.now(UTC)
        command = {
            "id": str(uuid.uuid4()),
            "action": action,
            "payload": payload or {},
            "requested_at": now.isoformat(),
            "requested_by": str(self.actor_id) if self.actor_id else None,
        }
        pending.append(command)
        metadata["pending_commands"] = pending
        device.metadata_ = metadata

        await AuditService(self.session).record(
            action="device.command.dispatch",
            resource_type="device",
            resource_id=device.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            actor=self.actor,
            after={
                "command_id": command["id"],
                "action": action,
                "payload": command["payload"],
            },
        )
        await self.session.flush()
        return {"command": command, "pending_count": len(pending)}

    async def status(self, device_id: uuid.UUID) -> dict:
        device = await self.uow.devices.get_or_404(device_id)
        metadata = dict(device.metadata_ or {})
        pending = [item for item in (metadata.get("pending_commands") or []) if isinstance(item, dict)]
        history = [item for item in (metadata.get("command_history") or []) if isinstance(item, dict)]
        return {
            "device_id": device.id,
            "pending": pending,
            "history": list(reversed(history))[:100],
            "pending_count": len(pending),
            "last_result_at": metadata.get("last_command_result_at"),
        }


class DeviceDiscoveryService:
    """Active subnet sweep for OPNsense management endpoints (SSRF-safe, CIDR-bounded)."""

    MAX_HOSTS = 1024
    CONCURRENCY = 64

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)

    async def discover(self, cidr: str, *, port: int = 443, timeout: float = 2.0) -> list[DiscoveryCandidate]:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise BadRequestError(f"Invalid CIDR: {cidr}") from exc
        if network.num_addresses > self.MAX_HOSTS:
            raise BadRequestError(f"CIDR too large; maximum {self.MAX_HOSTS} addresses per sweep")
        if network.is_global and settings.is_production:
            raise BadRequestError("Refusing to scan public address space from production")

        hosts = [str(host) for host in network.hosts()] or [str(network.network_address)]
        semaphore = asyncio.Semaphore(self.CONCURRENCY)
        existing = {
            device.ip_address for device in (await self.uow.devices.list(size=500))[0] if device.ip_address
        }

        async def probe(host: str) -> DiscoveryCandidate | None:
            async with semaphore:
                return await self._probe(host, port, timeout, host in existing)

        results = await asyncio.gather(*(probe(host) for host in hosts), return_exceptions=True)
        return [r for r in results if isinstance(r, DiscoveryCandidate) and r.reachable]

    async def _probe(self, host: str, port: int, timeout: float, managed: bool) -> DiscoveryCandidate | None:
        url = f"https://{host}:{port}/api/core/firmware/status"
        try:
            async with httpx.AsyncClient(verify=True, timeout=timeout) as client:
                response = await client.get(url)
        except httpx.HTTPError:
            return None

        server = response.headers.get("server", "").lower()
        body = response.text[:2000].lower()
        looks_like_opnsense = "opnsense" in server or "opnsense" in body or response.status_code == 401
        if not looks_like_opnsense:
            return None

        firmware = None
        hostname = None
        serial = None
        if response.status_code == 200:
            try:
                payload = response.json()
                firmware = payload.get("product_version") or payload.get("version")
                hostname = payload.get("hostname")
            except ValueError:
                pass
        return DiscoveryCandidate(
            ip_address=host,
            port=port,
            hostname=hostname,
            firmware_version=firmware,
            serial_number=serial,
            reachable=True,
            already_managed=managed,
        )


class CertificateService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.audit = AuditService(session)

    async def issue(
        self,
        *,
        device_id: uuid.UUID,
        common_name: str | None = None,
        csr_pem: str | None = None,
        validity_days: int | None = None,
        revoke_existing: bool = True,
    ) -> DeviceCertificate:
        from app.pki.ca import ca

        device = await self.uow.devices.get_or_404(device_id)
        cn = common_name or f"device-{device.serial_number or device.name}"
        issued = ca.issue(
            common_name=cn,
            tenant_id=self.tenant_id,
            csr_pem=csr_pem,
            validity_days=validity_days,
            san_dns=[device.hostname] if device.hostname else None,
            san_ips=[device.ip_address] if device.ip_address else None,
        )

        if revoke_existing:
            existing = await self.session.execute(
                select(DeviceCertificate).where(
                    DeviceCertificate.device_id == device.id,
                    DeviceCertificate.status == CertificateStatus.ACTIVE,
                )
            )
            for cert in existing.scalars().all():
                cert.status = CertificateStatus.REVOKED
                cert.revoked_at = datetime.now(UTC)
                cert.revoked_reason = "superseded"

        record = DeviceCertificate(
            device_id=device.id,
            tenant_id=self.tenant_id,
            serial_number=issued.serial_number,
            certificate_pem=issued.certificate_pem,
            private_key_encrypted=encrypt_secret(issued.private_key_pem) if issued.private_key_pem else "",
            subject_cn=issued.subject_cn,
            issuer_cn="OFME Device CA",
            fingerprint_sha256=issued.fingerprint_sha256,
            valid_from=issued.valid_from,
            valid_to=issued.valid_to,
            status=CertificateStatus.ACTIVE,
        )
        self.session.add(record)
        device.certificate_serial = issued.serial_number
        await self.session.flush()
        await self.audit.record(
            action="certificate.issued",
            resource_type="DeviceCertificate",
            resource_id=record.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"serial": record.serial_number, "device_id": str(device.id)},
        )
        return record

    async def revoke(self, certificate_id: uuid.UUID, reason: str = "unspecified") -> DeviceCertificate:
        certificate = await self.uow.certificates.get_or_404(certificate_id)
        certificate.status = CertificateStatus.REVOKED
        certificate.revoked_at = datetime.now(UTC)
        certificate.revoked_reason = reason
        await self.session.flush()
        await self.audit.record(
            action="certificate.revoked",
            resource_type="DeviceCertificate",
            resource_id=certificate.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"reason": reason},
        )
        return certificate

    async def rotate_expiring(self) -> int:
        cutoff = datetime.now(UTC) + timedelta(days=settings.PKI_RENEW_BEFORE_DAYS)
        certificates = await self.uow.certificates.expiring_before(cutoff)
        rotated = 0
        for certificate in certificates:
            device = await self.uow.devices.get(certificate.device_id)
            if device is None:
                continue
            await self.issue(
                device_id=device.id,
                common_name=certificate.subject_cn,
                revoke_existing=False,
            )
            rotated += 1
        return rotated

    async def revoke_superseded(self, device_id: uuid.UUID, current_fingerprint: str) -> int:
        """Revoke older active certificates once the device demonstrably uses a newer one.

        Renewal deliberately creates the replacement certificate before revoking the
        old one. The old certificate is only revoked after a request authenticated
        with the new fingerprint has been observed, which prevents a failed
        installation from locking the device out of the control plane.
        """
        normalised = current_fingerprint.replace(":", "").replace(" ", "").strip().lower()
        if not normalised:
            return 0

        current = (
            (
                await self.session.execute(
                    select(DeviceCertificate).where(
                        DeviceCertificate.device_id == device_id,
                        DeviceCertificate.fingerprint_sha256 == normalised,
                        DeviceCertificate.status == CertificateStatus.ACTIVE,
                    )
                )
            )
            .scalars()
            .first()
        )
        if current is None:
            return 0

        now = datetime.now(UTC)
        others = (
            (
                await self.session.execute(
                    select(DeviceCertificate).where(
                        DeviceCertificate.device_id == device_id,
                        DeviceCertificate.status == CertificateStatus.ACTIVE,
                        DeviceCertificate.id != current.id,
                    )
                )
            )
            .scalars()
            .all()
        )

        revoked = 0
        for certificate in others:
            if certificate.valid_to > now:
                if (
                    certificate.created_at is not None
                    and current.created_at is not None
                    and certificate.created_at >= current.created_at
                ):
                    continue
                certificate.status = CertificateStatus.REVOKED
                certificate.revoked_at = now
                certificate.revoked_reason = "superseded"
            else:
                certificate.status = CertificateStatus.REVOKED
                certificate.revoked_at = now
                certificate.revoked_reason = "expired"
            revoked += 1

        if revoked:
            await self.session.flush()
            await self.audit.record(
                action="certificate.superseded",
                resource_type="DeviceCertificate",
                resource_id=current.id,
                tenant_id=self.tenant_id,
                user_id=self.actor_id,
                after={"device_id": str(device_id), "revoked": revoked},
            )
        return revoked

    async def crl(self) -> str:
        from app.pki.ca import ca

        stmt = select(DeviceCertificate).where(DeviceCertificate.status == CertificateStatus.REVOKED)
        revoked = [
            (cert.serial_number, cert.revoked_at or datetime.now(UTC), cert.revoked_reason or "unspecified")
            for cert in (await self.session.execute(stmt)).scalars().all()
        ]
        return ca.build_crl(revoked)


class DeviceMonitorService:
    """Pull-based health probe for devices that do not run the agent."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.devices = DeviceService(session, tenant_id)

    async def poll_device(self, device_id: uuid.UUID) -> bool:
        from app.integrations.opnsense.client import client_for

        device = await self.devices.get(device_id)
        base_url, key, secret = await self.devices.credentials(device)
        async with client_for(base_url, key, secret) as client:
            snapshot = await client.healthcheck()

        if not snapshot.reachable:
            previous = device.status
            device.status = DeviceStatus.ERROR
            device.connection_status = ConnectionStatus.ERROR
            await self.session.commit()
            await event_bus.publish(
                DeviceStatusChanged(
                    device_id=str(device.id),
                    tenant_id=str(self.tenant_id),
                    status=DeviceStatus.ERROR.value,
                    previous=previous.value,
                )
            )
            return False

        payload = HeartbeatPayload(**snapshot.as_heartbeat())
        await HeartbeatService(self.session, self.tenant_id).ingest(device.id, payload)
        return True

    async def poll_all(self, limit: int = 200) -> dict[str, int]:
        devices, _ = await self.devices.list(size=limit)
        ok = failed = 0
        semaphore = asyncio.Semaphore(16)

        async def run(device: Device) -> bool:
            async with semaphore:
                try:
                    return await self.poll_device(device.id)
                except Exception as exc:  # noqa: BLE001 - one device must not stop the sweep
                    log.warning("monitor.poll_failed", device=device.name, error=str(exc))
                    return False

        for result in await asyncio.gather(*(run(d) for d in devices)):
            if result:
                ok += 1
            else:
                failed += 1
        return {"ok": ok, "failed": failed}
