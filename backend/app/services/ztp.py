"""Zero-Touch Provisioning: tokens, enrollment, PKI binding, bootstrap packages."""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import DeviceRegistered, event_bus
from app.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    LicenseLimitError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.core.security import encrypt_secret
from app.models.config import Template
from app.models.enums import CertificateStatus, DeviceStatus, ZtpStatus
from app.models.identity import Tenant
from app.models.policy import Policy
from app.models.sdwan import VpnTunnel
from app.models.topology import Device, DeviceCertificate, DeviceGroup, Site
from app.models.ztp import ZtpEnrollment
from app.pki.ca import ca
from app.repositories import UnitOfWork
from app.schemas.ztp import (
    BootstrapPackage,
    DiscoveryInfo,
    EnrollmentRequest,
    EnrollmentResponse,
    EnrollmentTokenCreate,
)
from app.services.audit import AuditService

log = get_logger("ofme.ztp")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")[:64] or "device"


class EnrollmentService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ tokens
    async def create_token(self, payload: EnrollmentTokenCreate) -> tuple[ZtpEnrollment, str]:
        token = secrets.token_urlsafe(32)
        enrollment = ZtpEnrollment(
            tenant_id=self.tenant_id,
            site_id=payload.site_id,
            template_id=payload.template_id,
            group_id=payload.group_id,
            device_serial=payload.device_serial,
            device_mac=payload.device_mac.upper() if payload.device_mac else None,
            hostname=payload.hostname,
            token_hash=_hash_token(token),
            token_hint=token[:8],
            discovery_method=payload.discovery_method,
            expires_at=datetime.now(UTC) + timedelta(minutes=payload.ttl_minutes),
            status=ZtpStatus.PENDING,
        )
        self.session.add(enrollment)
        await self.session.flush()
        await self.audit.record(
            action="ztp.token_created",
            resource_type="ZtpEnrollment",
            resource_id=enrollment.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "site_id": str(payload.site_id) if payload.site_id else None,
                "serial": payload.device_serial,
            },
        )
        return enrollment, token

    async def list(
        self, *, page: int = 1, size: int = 50, status: str | None = None
    ) -> tuple[list[ZtpEnrollment], int]:
        return await self.uow.ztp.list(filters={"status": status} if status else None, page=page, size=size)

    async def revoke(self, enrollment_id: uuid.UUID) -> ZtpEnrollment:
        enrollment = await self.uow.ztp.get_or_404(enrollment_id)
        enrollment.status = ZtpStatus.REVOKED
        await self.session.flush()
        await self.audit.record(
            action="ztp.revoked",
            resource_type="ZtpEnrollment",
            resource_id=enrollment.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
        )
        return enrollment

    # ------------------------------------------------------------------ enrollment
    async def enroll(self, payload: EnrollmentRequest, *, source_ip: str | None = None) -> EnrollmentResponse:
        enrollment = await self.uow.ztp.by_token_hash(_hash_token(payload.token))
        if enrollment is None or enrollment.tenant_id != self.tenant_id:
            raise AuthenticationError("Invalid enrollment token")
        if enrollment.status not in {ZtpStatus.PENDING}:
            raise ConflictError(f"Enrollment is {enrollment.status.value}")
        if enrollment.expires_at <= datetime.now(UTC):
            enrollment.status = ZtpStatus.EXPIRED
            await self.session.commit()
            raise AuthenticationError("Enrollment token expired")
        if enrollment.device_serial and payload.serial_number != enrollment.device_serial:
            raise AuthenticationError("Serial number does not match the pre-registered device")
        if (
            enrollment.device_mac
            and payload.mac_address
            and payload.mac_address.upper() != enrollment.device_mac
        ):
            raise AuthenticationError("MAC address does not match the pre-registered device")

        tenant = await self.session.get(Tenant, self.tenant_id)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        device_count = await self.uow.devices.count()
        if device_count >= tenant.device_limit:
            raise LicenseLimitError("Tenant device limit reached")

        existing = await self.uow.devices.get_by_serial(payload.serial_number)
        if existing is not None:
            raise ConflictError("A device with this serial number is already registered")

        site, group, template = await self._resolve_assignment(enrollment, payload)
        device_name = self._device_name(site, payload)

        device = Device(
            tenant_id=self.tenant_id,
            site_id=site.id if site else enrollment.site_id,
            group_id=group.id if group else enrollment.group_id,
            name=device_name,
            hostname=payload.hostname or device_name,
            serial_number=payload.serial_number,
            model=payload.model,
            firmware_version=payload.firmware_version,
            ip_address=source_ip,
            status=DeviceStatus.REGISTERED,
            enrolled_at=datetime.now(UTC),
            metadata_={
                "hardware": payload.hardware_profile,
                "enrollment_id": str(enrollment.id),
                "discovery": enrollment.discovery_method.value,
            },
            tags=["ztp"],
        )
        self.session.add(device)
        await self.session.flush()

        issued = ca.issue(
            common_name=f"device-{payload.serial_number}",
            tenant_id=self.tenant_id,
            csr_pem=payload.csr_pem,
            san_dns=[payload.hostname] if payload.hostname else None,
            san_ips=[source_ip] if source_ip else None,
        )
        certificate = DeviceCertificate(
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
        self.session.add(certificate)
        device.certificate_serial = issued.serial_number

        enrollment.status = ZtpStatus.COMPLETED
        enrollment.device_id = device.id
        enrollment.enrolled_at = datetime.now(UTC)
        enrollment.provisioned_at = datetime.now(UTC)
        enrollment.certificate_serial = issued.serial_number
        enrollment.hardware_profile = payload.hardware_profile
        enrollment.metadata_ = {"enrolled_from": source_ip, "model": payload.model}
        await self.session.flush()

        bootstrap = await self._build_bootstrap(device, template, site, group)
        await self.audit.record(
            action="ztp.enrolled",
            resource_type="Device",
            resource_id=device.id,
            tenant_id=self.tenant_id,
            actor=f"ztp:{payload.serial_number}",
            after={"device": device.name, "site_id": str(device.site_id) if device.site_id else None},
        )
        await event_bus.publish(
            DeviceRegistered(
                device_id=str(device.id),
                tenant_id=str(self.tenant_id),
                name=device.name,
                serial_number=device.serial_number,
            )
        )
        await self.session.commit()

        return EnrollmentResponse(
            status="accepted",
            device_id=device.id,
            device_name=device.name,
            certificate_pem=issued.certificate_pem,
            ca_pem=issued.ca_pem,
            certificate_serial=issued.serial_number,
            valid_to=issued.valid_to,
            bootstrap=bootstrap,
            heartbeat_url=f"{settings.API_V1_PREFIX}/agent/heartbeat",
            heartbeat_interval_seconds=settings.HEARTBEAT_INTERVAL_SECONDS,
        )

    async def _resolve_assignment(
        self, enrollment: ZtpEnrollment, payload: EnrollmentRequest
    ) -> tuple[Site | None, DeviceGroup | None, Template | None]:
        site = await self.uow.sites.get(enrollment.site_id) if enrollment.site_id else None
        group = await self.uow.groups.get(enrollment.group_id) if enrollment.group_id else None
        template = await self.uow.templates.get(enrollment.template_id) if enrollment.template_id else None

        if site is None:
            # Location-based provisioning: pick the site whose contact metadata declares a matching subnet.
            sites, _ = await self.uow.sites.list(size=200)
            import ipaddress

            if payload.hostname:
                for candidate in sites:
                    subnets = (candidate.metadata_ or {}).get("subnets") or []
                    if not subnets:
                        continue
                    source = payload.hardware_profile.get("management_ip") or ""
                    try:
                        address = ipaddress.ip_address(source)
                    except ValueError:
                        continue
                    if any(address in ipaddress.ip_network(str(net), strict=False) for net in subnets):
                        site = candidate
                        break
            if site is None and sites:
                site = sites[0]

        if group is None and site is not None:
            group = (
                (
                    await self.session.execute(
                        select(DeviceGroup).where(
                            DeviceGroup.tenant_id == self.tenant_id,
                            DeviceGroup.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .first()
            )

        if template is None and group is not None and group.template_id:
            template = await self.uow.templates.get(group.template_id)
        if template is None:
            template = (
                (
                    await self.session.execute(
                        select(Template).where(
                            Template.tenant_id == self.tenant_id,
                            Template.is_active.is_(True),
                        )
                    )
                )
                .scalars()
                .first()
            )
        return site, group, template

    @staticmethod
    def _device_name(site: Site | None, payload: EnrollmentRequest) -> str:
        prefix = _slug(site.code) if site else "site"
        suffix = _slug(payload.serial_number[-8:]) if payload.serial_number else secrets.token_hex(3)
        name = f"{prefix}-{suffix}"
        if len(name) > 80:
            name = name[:80]
        return name

    async def _build_bootstrap(
        self,
        device: Device,
        template: Template | None,
        site: Site | None,
        group: DeviceGroup | None,
    ) -> BootstrapPackage:
        policies = (
            (
                await self.session.execute(
                    select(Policy).where(
                        Policy.tenant_id == self.tenant_id,
                        Policy.status == "deployed",
                    )
                )
            )
            .scalars()
            .all()
        )
        tunnels = (
            (
                await self.session.execute(
                    select(VpnTunnel).where(
                        VpnTunnel.tenant_id == self.tenant_id,
                        VpnTunnel.local_device_id == device.id,
                    )
                )
            )
            .scalars()
            .all()
        )

        return BootstrapPackage(
            enrollment_id=uuid.UUID(str((device.metadata_ or {}).get("enrollment_id", uuid.uuid4()))),
            device_name=device.name,
            site_id=device.site_id,
            template=(
                {
                    "id": str(template.id),
                    "name": template.name,
                    "body": template.body,
                    "variables": template.variables,
                }
                if template
                else None
            ),
            policies=[
                {
                    "id": str(policy.id),
                    "name": policy.name,
                    "kind": policy.kind.value,
                    "environment": policy.environment.value,
                    "content": policy.content,
                }
                for policy in policies
            ],
            vpn=[
                {
                    "name": tunnel.name,
                    "protocol": tunnel.protocol.value,
                    "interface": tunnel.interface_name,
                    "allowed_ips": tunnel.allowed_ips,
                    "keepalive": tunnel.keepalive,
                    "mtu": tunnel.mtu,
                }
                for tunnel in tunnels
            ],
            monitoring={
                "heartbeat_interval_seconds": settings.HEARTBEAT_INTERVAL_SECONDS,
                "metric_retention_days": settings.METRIC_RETENTION_DAYS,
            },
            platform={
                "api_version": "v1",
                "tenant_id": str(self.tenant_id),
                "site": site.name if site else None,
                "group": group.name if group else None,
                "ca_fingerprint": ca.fingerprint,
            },
        )


class EnrollmentAgentService:
    """Public-facing bootstrap helpers used by unauthenticated devices."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def discovery(self, *, base_url: str) -> DiscoveryInfo:
        return DiscoveryInfo(
            platform_url=base_url.rstrip("/"),
            bootstrap_endpoint=f"{settings.API_V1_PREFIX}/ztp/bootstrap",
            enrollment_endpoint=f"{settings.API_V1_PREFIX}/ztp/enroll",
            ca_fingerprint=ca.fingerprint,
        )

    async def bootstrap_package(self, token: str) -> BootstrapPackage:
        enrollment = (
            (
                await self.session.execute(
                    select(ZtpEnrollment).where(ZtpEnrollment.token_hash == _hash_token(token))
                )
            )
            .scalars()
            .first()
        )
        if enrollment is None:
            raise AuthenticationError("Invalid enrollment token")
        if enrollment.expires_at <= datetime.now(UTC):
            raise AuthenticationError("Enrollment token expired")
        if enrollment.status not in {ZtpStatus.PENDING, ZtpStatus.ENROLLED}:
            raise BadRequestError(f"Enrollment already {enrollment.status.value}")

        tenant = await self.session.get(Tenant, enrollment.tenant_id)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        template = (
            await self.session.get(Template, enrollment.template_id) if enrollment.template_id else None
        )
        site = await self.session.get(Site, enrollment.site_id) if enrollment.site_id else None
        return BootstrapPackage(
            enrollment_id=enrollment.id,
            device_name=enrollment.hostname or f"ztp-{enrollment.token_hint}",
            site_id=enrollment.site_id,
            template=(
                {"id": str(template.id), "name": template.name, "body": template.body} if template else None
            ),
            monitoring={
                "heartbeat_interval_seconds": settings.HEARTBEAT_INTERVAL_SECONDS,
            },
            platform={
                "api_version": "v1",
                "tenant_id": str(enrollment.tenant_id),
                "tenant_slug": tenant.slug,
                "site": site.name if site else None,
                "ca_fingerprint": ca.fingerprint,
            },
        )
