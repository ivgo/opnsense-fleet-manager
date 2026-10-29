"""Device-facing agent API: bootstrap, heartbeat, desired configuration and PKI renewal.

The agent authenticates with the X.509 certificate issued during enrollment. TLS is
terminated at the ingress, which forwards the verified client-certificate SHA-256
fingerprint in ``X-Device-Cert-Fingerprint``. The serial fallback is only accepted in
development/testing environments.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.exceptions import AuthenticationError, BadRequestError, NotFoundError
from app.models.config import Alias, FirewallRule, InterfaceConfig, NatRule, RouteConfig, VlanConfig
from app.models.enums import CertificateStatus, PolicyStatus
from app.models.policy import Policy
from app.models.sdwan import SdwanRoute, VpnTunnel
from app.models.topology import Device, DeviceCertificate
from app.repositories import UnitOfWork
from app.schemas.topology import HeartbeatPayload, HeartbeatResponse
from app.schemas.ztp import BootstrapPackage, EnrollmentRequest, EnrollmentResponse
from app.services.devices import CertificateService, HeartbeatService
from app.services.ztp import EnrollmentAgentService, EnrollmentService, _hash_token

router = APIRouter(prefix="/agent", tags=["Device agent"])

DeviceIDHeader = Annotated[uuid.UUID, Header(alias="X-Device-Id")]
FingerprintHeader = Annotated[str | None, Header(alias="X-Device-Cert-Fingerprint")]
ClientFingerprintHeader = Annotated[str | None, Header(alias="X-Client-Cert-Fingerprint")]
SerialHeader = Annotated[str | None, Header(alias="X-Device-Serial")]


def _normalise_fingerprint(value: str) -> str:
    return value.replace(":", "").replace(" ", "").strip().lower()


async def get_agent_device(
    session: SessionDep,
    x_device_id: DeviceIDHeader,
    x_device_cert_fingerprint: FingerprintHeader = None,
    x_client_cert_fingerprint: ClientFingerprintHeader = None,
    x_device_serial: SerialHeader = None,
) -> Device:
    device = await session.get(Device, x_device_id)
    if device is None or device.deleted_at is not None:
        raise AuthenticationError("Unknown device")

    fingerprint = x_device_cert_fingerprint or x_client_cert_fingerprint
    if fingerprint:
        normalised = _normalise_fingerprint(fingerprint)
        certificate = (
            (
                await session.execute(
                    select(DeviceCertificate).where(
                        DeviceCertificate.device_id == device.id,
                        DeviceCertificate.fingerprint_sha256 == normalised,
                        DeviceCertificate.status == CertificateStatus.ACTIVE,
                    )
                )
            )
            .scalars()
            .first()
        )
        if certificate is None or certificate.valid_to <= datetime.now(UTC):
            raise AuthenticationError("Device certificate is not valid")
        return device

    if (
        settings.ENVIRONMENT in {"development", "testing"}
        and x_device_serial
        and device.serial_number
        and x_device_serial == device.serial_number
    ):
        return device

    raise AuthenticationError("Client certificate verification is required")


AgentDevice = Annotated[Device, Depends(get_agent_device)]


class CertificateRenewRequest(BaseModel):
    csr_pem: str = Field(min_length=64)
    validity_days: int | None = Field(None, ge=1, le=3650)


class CertificateRenewResponse(BaseModel):
    serial_number: str
    certificate_pem: str
    ca_pem: str
    valid_to: datetime


class CommandBatch(BaseModel):
    commands: list[dict[str, Any]] = Field(default_factory=list)
    config_version: str | None = None
    server_time: datetime


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _rule_payload(rule: FirewallRule) -> dict[str, Any]:
    return {
        "name": rule.name,
        "action": rule.action.value,
        "direction": rule.direction.value,
        "interface": rule.interface,
        "protocol": rule.protocol,
        "source": rule.source,
        "destination": rule.destination,
        "source_port": rule.source_port,
        "destination_port": rule.destination_port,
        "gateway": rule.gateway,
        "log": rule.log,
        "enabled": rule.enabled,
        "order_index": rule.order_index,
        "description": rule.description,
        "version": rule.version,
    }


def _alias_payload(alias: Alias) -> dict[str, Any]:
    return {
        "name": alias.name,
        "type": alias.type.value,
        "content": list(alias.content or []),
        "description": alias.description,
        "enabled": alias.enabled,
    }


def _nat_payload(rule: NatRule) -> dict[str, Any]:
    return {
        "name": rule.name,
        "type": rule.type.value,
        "interface": rule.interface,
        "protocol": rule.protocol,
        "source": rule.source,
        "destination": rule.destination,
        "destination_port": rule.destination_port,
        "target": rule.target,
        "target_port": rule.target_port,
        "enabled": rule.enabled,
        "order_index": rule.order_index,
    }


def _interface_payload(row: InterfaceConfig) -> dict[str, Any]:
    return {
        "name": row.name,
        "description": row.description,
        "physical_if": row.physical_if,
        "ip_address": row.ip_address,
        "subnet_bits": row.subnet_bits,
        "gateway": row.gateway,
        "dhcp": row.dhcp,
        "enabled": row.enabled,
    }


def _route_payload(row: RouteConfig) -> dict[str, Any]:
    return {
        "network": row.network,
        "gateway": row.gateway,
        "interface": row.interface,
        "metric": row.metric,
        "description": row.description,
        "managed_by_sdwan": row.managed_by_sdwan,
    }


def _vlan_payload(row: VlanConfig) -> dict[str, Any]:
    return {
        "vlan_id": row.vlan_id,
        "parent_interface": row.parent_interface,
        "description": row.description,
        "enabled": row.enabled,
    }


def _tunnel_payload(tunnel: VpnTunnel) -> dict[str, Any]:
    return {
        "name": tunnel.name,
        "protocol": tunnel.protocol.value,
        "interface": tunnel.interface_name,
        "public_key": tunnel.public_key,
        "endpoint_local": tunnel.endpoint_local,
        "endpoint_remote": tunnel.endpoint_remote,
        "allowed_ips": list(tunnel.allowed_ips or []),
        "keepalive": tunnel.keepalive,
        "mtu": tunnel.mtu,
        "status": tunnel.status.value,
    }


def _sdwan_route_payload(row: SdwanRoute) -> dict[str, Any]:
    return {
        "destination": row.destination,
        "next_hop": row.next_hop,
        "tunnel_id": str(row.tunnel_id) if row.tunnel_id else None,
        "metric": row.metric,
        "protocol": row.protocol,
        "installed": row.installed,
    }


# --------------------------------------------------------------------------- public
@router.get("/health", response_model=dict, summary="Agent-facing liveness probe")
async def agent_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "api_version": settings.APP_VERSION,
        "heartbeat_interval_seconds": settings.HEARTBEAT_INTERVAL_SECONDS,
        "server_time": datetime.now(UTC),
    }


@router.get(
    "/bootstrap",
    response_model=BootstrapPackage,
    summary="Fetch the bootstrap package for an enrollment token",
)
async def agent_bootstrap(session: SessionDep, token: str = Query(..., min_length=16)) -> BootstrapPackage:
    return await EnrollmentAgentService(session).bootstrap_package(token)


@router.post(
    "/enroll",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a device (public, token-protected)",
)
async def agent_enroll(
    payload: EnrollmentRequest, request: Request, session: SessionDep
) -> EnrollmentResponse:
    enrollment = await UnitOfWork(session, None).ztp.by_token_hash(_hash_token(payload.token))
    if enrollment is None or enrollment.expires_at <= datetime.now(UTC):
        raise AuthenticationError("Invalid or expired enrollment token")
    client_ip = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    return await EnrollmentService(session, enrollment.tenant_id).enroll(payload, source_ip=client_ip)


# --------------------------------------------------------------------------- authenticated
@router.post(
    "/heartbeat",
    response_model=HeartbeatResponse,
    summary="Submit telemetry and receive pending commands",
)
async def agent_heartbeat(
    payload: HeartbeatPayload,
    device: AgentDevice,
    session: SessionDep,
    request: Request,
    x_device_cert_fingerprint: FingerprintHeader = None,
    x_client_cert_fingerprint: ClientFingerprintHeader = None,
) -> HeartbeatResponse:
    if payload.serial_number and device.serial_number and payload.serial_number != device.serial_number:
        raise BadRequestError("Serial number does not match the authenticated device")

    updated = await HeartbeatService(session, device.tenant_id).ingest(device.id, payload)
    fingerprint = x_device_cert_fingerprint or x_client_cert_fingerprint
    if fingerprint:
        await CertificateService(session, device.tenant_id).revoke_superseded(device.id, fingerprint)
        await session.commit()
    commands = list((updated.metadata_ or {}).get("pending_commands") or [])
    return HeartbeatResponse(
        accepted=True,
        device_id=updated.id,
        server_time=datetime.now(UTC),
        commands=commands,
        command_results_accepted=len(payload.command_results),
    )


@router.post(
    "/telemetry",
    response_model=HeartbeatResponse,
    summary="Alias of /agent/heartbeat for metric-only payloads",
)
async def agent_telemetry(
    payload: HeartbeatPayload,
    device: AgentDevice,
    session: SessionDep,
    request: Request,
) -> HeartbeatResponse:
    return await agent_heartbeat(payload, device, session, request)


@router.get(
    "/config",
    response_model=dict,
    summary="Current desired configuration for the device",
)
async def agent_config(device: AgentDevice, session: SessionDep) -> dict[str, Any]:
    tenant_id = device.tenant_id

    rules_stmt = select(FirewallRule).where(
        FirewallRule.tenant_id == tenant_id,
        FirewallRule.deleted_at.is_(None),
        or_(
            FirewallRule.device_id == device.id,
            FirewallRule.group_id == device.group_id if device.group_id else False,
        ),
    )
    rules = (await session.execute(rules_stmt.order_by(FirewallRule.order_index.asc()))).scalars().all()

    aliases = (
        (
            await session.execute(
                select(Alias).where(
                    Alias.tenant_id == tenant_id,
                    Alias.deleted_at.is_(None),
                    or_(Alias.device_id == device.id, Alias.device_id.is_(None)),
                )
            )
        )
        .scalars()
        .all()
    )
    nat_rules = (
        (
            await session.execute(
                select(NatRule).where(
                    NatRule.tenant_id == tenant_id,
                    NatRule.deleted_at.is_(None),
                    or_(NatRule.device_id == device.id, NatRule.device_id.is_(None)),
                )
            )
        )
        .scalars()
        .all()
    )
    interfaces = (
        (
            await session.execute(
                select(InterfaceConfig).where(
                    InterfaceConfig.tenant_id == tenant_id,
                    InterfaceConfig.device_id == device.id,
                    InterfaceConfig.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    routes = (
        (
            await session.execute(
                select(RouteConfig).where(
                    RouteConfig.tenant_id == tenant_id,
                    RouteConfig.device_id == device.id,
                    RouteConfig.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    vlans = (
        (
            await session.execute(
                select(VlanConfig).where(
                    VlanConfig.tenant_id == tenant_id,
                    VlanConfig.device_id == device.id,
                    VlanConfig.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    tunnels = (
        (
            await session.execute(
                select(VpnTunnel).where(
                    VpnTunnel.tenant_id == tenant_id,
                    VpnTunnel.local_device_id == device.id,
                )
            )
        )
        .scalars()
        .all()
    )
    sdwan_routes = (
        (
            await session.execute(
                select(SdwanRoute).where(
                    SdwanRoute.tenant_id == tenant_id,
                    SdwanRoute.device_id == device.id,
                )
            )
        )
        .scalars()
        .all()
    )
    policies = (
        (
            await session.execute(
                select(Policy).where(
                    Policy.tenant_id == tenant_id,
                    Policy.status == PolicyStatus.DEPLOYED,
                    Policy.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    payload: dict[str, Any] = {
        "device": {
            "id": str(device.id),
            "name": device.name,
            "hostname": device.hostname,
            "site_id": str(device.site_id) if device.site_id else None,
            "group_id": str(device.group_id) if device.group_id else None,
            "is_ha": device.is_ha,
            "ha_role": device.ha_role.value if device.ha_role else None,
        },
        "firewall_rules": [_rule_payload(rule) for rule in rules],
        "aliases": [_alias_payload(alias) for alias in aliases],
        "nat": [_nat_payload(rule) for rule in nat_rules],
        "interfaces": [_interface_payload(row) for row in interfaces],
        "routes": [_route_payload(row) for row in routes],
        "vlans": [_vlan_payload(row) for row in vlans],
        "vpn": [_tunnel_payload(tunnel) for tunnel in tunnels],
        "sdwan_routes": [_sdwan_route_payload(row) for row in sdwan_routes],
        "policies": [
            {
                "id": str(policy.id),
                "name": policy.name,
                "kind": policy.kind.value,
                "environment": policy.environment.value,
                "version": policy.version,
                "content": policy.content,
            }
            for policy in policies
        ],
        "agent": {
            "heartbeat_interval_seconds": settings.HEARTBEAT_INTERVAL_SECONDS,
            "metric_retention_days": settings.METRIC_RETENTION_DAYS,
            "api_version": "v1",
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    canonical = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    payload["config_hash"] = hashlib.sha256(canonical).hexdigest()
    return payload


@router.get(
    "/commands",
    response_model=CommandBatch,
    summary="Pull and acknowledge pending commands",
)
async def agent_commands(device: AgentDevice, session: SessionDep) -> CommandBatch:
    commands = list((device.metadata_ or {}).get("pending_commands") or [])
    if commands:
        device.metadata_ = {**(device.metadata_ or {}), "pending_commands": []}
        await session.commit()
    return CommandBatch(
        commands=commands,
        config_version=device.config_version,
        server_time=datetime.now(UTC),
    )


@router.post(
    "/certificate/renew",
    response_model=CertificateRenewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Renew the device certificate from a CSR",
)
async def renew_certificate(
    payload: CertificateRenewRequest,
    device: AgentDevice,
    session: SessionDep,
) -> CertificateRenewResponse:
    from app.pki.ca import ca

    record = await CertificateService(session, device.tenant_id).issue(
        device_id=device.id,
        common_name=f"device-{device.serial_number or device.name}",
        csr_pem=payload.csr_pem,
        validity_days=payload.validity_days,
        revoke_existing=False,
    )
    await session.commit()
    return CertificateRenewResponse(
        serial_number=record.serial_number,
        certificate_pem=record.certificate_pem,
        ca_pem=ca.ca_pem,
        valid_to=record.valid_to,
    )


@router.get(
    "/whoami",
    response_model=dict,
    summary="Identity asserted by the client certificate",
)
async def agent_whoami(device: AgentDevice) -> dict[str, Any]:
    return {
        "device_id": str(device.id),
        "name": device.name,
        "hostname": device.hostname,
        "serial_number": device.serial_number,
        "certificate_serial": device.certificate_serial,
        "last_heartbeat_at": _iso(device.last_heartbeat_at),
        "status": device.status.value if hasattr(device.status, "value") else str(device.status),
    }


__all__ = ["router", "get_agent_device", "NotFoundError"]
