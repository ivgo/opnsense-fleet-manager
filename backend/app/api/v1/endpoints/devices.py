"""Device inventory: registration, lifecycle, heartbeats, discovery and certificates."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentPrincipal,
    DeviceDep,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import NotFoundError
from app.cqrs.bus import command_bus
from app.cqrs.commands import CreateDevice, DeleteDevice, SetMaintenanceMode, UpdateDevice
from app.models.enums import CertificateStatus, DeviceStatus
from app.models.topology import DeviceCertificate
from app.pki.ca import ca
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.topology import (
    CertificateIssueResponse,
    CertificateOut,
    DeviceCommandOut,
    DeviceCommandRequest,
    DeviceCommandStatus,
    DeviceCreate,
    DeviceOut,
    DeviceSearchResult,
    DeviceSummary,
    DeviceUpdate,
    HeartbeatPayload,
    HeartbeatResponse,
    RevokeRequest,
)
from app.services.devices import (
    CertificateService,
    DeviceCommandService,
    DeviceDiscoveryService,
    DeviceMonitorService,
    DeviceService,
    HeartbeatService,
)

router = APIRouter(prefix="/devices", tags=["Devices"])
certificates_router = APIRouter(prefix="/certificates", tags=["Certificates"])


class MaintenanceRequest(BaseModel):
    enabled: bool = True


class CertificateRequestBody(BaseModel):
    common_name: str | None = Field(None, max_length=255)
    validity_days: int | None = Field(None, ge=1, le=3650)


class DiscoveryRequest(BaseModel):
    cidr: str = Field(min_length=9, max_length=43, examples=["192.168.10.0/24"])
    port: int = Field(443, ge=1, le=65535)
    timeout: float = Field(2.0, ge=0.2, le=10.0)


class DiscoveryResult(BaseModel):
    ip_address: str
    port: int
    hostname: str | None
    firmware_version: str | None
    serial_number: str | None
    reachable: bool
    already_managed: bool


def _certificate_out(certificate: DeviceCertificate) -> CertificateOut:
    return CertificateOut.model_validate(certificate)


# --------------------------------------------------------------------------- collection
@router.get(
    "",
    response_model=PageResponse[DeviceOut],
    dependencies=[Depends(require_permissions(P.DEVICE_READ))],
    summary="List devices",
)
async def list_devices(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    search: str | None = Query(None, max_length=128),
    status_filter: DeviceStatus | None = Query(None, alias="status"),
    site_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
) -> PageResponse[DeviceOut]:
    devices, total = await DeviceService(session, tenant_id).list(
        page=pagination.page,
        size=pagination.size,
        search=search,
        status=status_filter.value if status_filter else None,
        site_id=site_id,
        group_id=group_id,
        sort=pagination.sort or "created_at",
        order=pagination.order,
    )
    return paginate(devices, total, pagination, DeviceOut)


@router.get(
    "/summary",
    response_model=DeviceSummary,
    dependencies=[Depends(require_permissions(P.DEVICE_READ))],
    summary="Device counters by status",
)
async def device_summary(session: SessionDep, tenant_id: TenantDep) -> DeviceSummary:
    return DeviceSummary(**await DeviceService(session, tenant_id).summary())


@router.get(
    "/search",
    response_model=list[DeviceSearchResult],
    dependencies=[Depends(require_permissions(P.DEVICE_READ))],
    summary="Quick device search",
)
async def search_devices(
    session: SessionDep,
    tenant_id: TenantDep,
    q: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(20, ge=1, le=100),
) -> list[DeviceSearchResult]:
    devices = await UnitOfWork(session, tenant_id).devices.search(q, limit=limit)
    return [
        DeviceSearchResult(
            id=device.id,
            name=device.name,
            hostname=device.hostname,
            ip_address=device.ip_address,
            status=device.status,
        )
        for device in devices
    ]


@router.post(
    "/discover",
    response_model=list[DiscoveryResult],
    dependencies=[Depends(require_permissions(P.DEVICE_ENROLL))],
    summary="Sweep a CIDR for OPNsense management endpoints",
)
async def discover_devices(
    payload: DiscoveryRequest, session: SessionDep, tenant_id: TenantDep
) -> list[DiscoveryResult]:
    candidates = await DeviceDiscoveryService(session, tenant_id).discover(
        payload.cidr, port=payload.port, timeout=payload.timeout
    )
    return [DiscoveryResult(**asdict(candidate)) for candidate in candidates]


@router.post(
    "",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.DEVICE_WRITE))],
    summary="Register a device",
)
async def create_device(
    payload: DeviceCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DeviceOut:
    device = await command_bus.dispatch(
        CreateDevice(
            session=session,
            tenant_id=tenant_id,
            actor_id=principal.user_id,
            payload=payload,
        )
    )
    await session.commit()
    return DeviceOut.model_validate(device)


# --------------------------------------------------------------------------- single device
@router.get(
    "/{device_id}",
    response_model=DeviceOut,
    dependencies=[Depends(require_permissions(P.DEVICE_READ))],
    summary="Get a device",
)
async def get_device(device: DeviceDep) -> DeviceOut:
    return DeviceOut.model_validate(device)


@router.patch(
    "/{device_id}",
    response_model=DeviceOut,
    dependencies=[Depends(require_permissions(P.DEVICE_WRITE))],
    summary="Update a device",
)
async def update_device(
    device_id: uuid.UUID,
    payload: DeviceUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DeviceOut:
    device = await command_bus.dispatch(
        UpdateDevice(
            session=session,
            tenant_id=tenant_id,
            actor_id=principal.user_id,
            device_id=device_id,
            payload=payload,
        )
    )
    await session.commit()
    return DeviceOut.model_validate(device)


@router.delete(
    "/{device_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.DEVICE_DELETE))],
    summary="Delete a device",
)
async def delete_device(
    device_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await command_bus.dispatch(
        DeleteDevice(
            session=session,
            tenant_id=tenant_id,
            actor_id=principal.user_id,
            device_id=device_id,
        )
    )
    await session.commit()
    return Message(message="Device deleted")


@router.post(
    "/{device_id}/maintenance",
    response_model=DeviceOut,
    dependencies=[Depends(require_permissions(P.DEVICE_WRITE))],
    summary="Enter or leave maintenance mode",
)
async def set_maintenance(
    device_id: uuid.UUID,
    payload: MaintenanceRequest,
    session: SessionDep,
    tenant_id: TenantDep,
) -> DeviceOut:
    device = await command_bus.dispatch(
        SetMaintenanceMode(
            session=session,
            tenant_id=tenant_id,
            device_id=device_id,
            enabled=payload.enabled,
        )
    )
    await session.commit()
    return DeviceOut.model_validate(device)


@router.post(
    "/{device_id}/heartbeat",
    response_model=HeartbeatResponse,
    dependencies=[Depends(require_permissions(P.DEVICE_EXEC))],
    summary="Submit a heartbeat on behalf of a device",
)
async def heartbeat(
    payload: HeartbeatPayload,
    device: DeviceDep,
    session: SessionDep,
    tenant_id: TenantDep,
) -> HeartbeatResponse:
    updated = await HeartbeatService(session, tenant_id).ingest(device.id, payload)
    commands = list((updated.metadata_ or {}).get("pending_commands") or [])
    return HeartbeatResponse(
        accepted=True,
        device_id=updated.id,
        server_time=datetime.now(UTC),
        commands=commands,
        command_results_accepted=len(payload.command_results),
    )


@router.post(
    "/{device_id}/commands",
    response_model=DeviceCommandOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.DEVICE_EXEC))],
    summary="Queue a whitelisted command for a device",
)
async def dispatch_device_command(
    device_id: uuid.UUID,
    payload: DeviceCommandRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> DeviceCommandOut:
    result = await DeviceCommandService(
        session,
        tenant_id,
        actor_id=principal.user_id,
        actor=principal.username,
    ).dispatch(device_id, payload.action, payload.payload)
    await session.commit()
    command = result["command"]
    return DeviceCommandOut(
        id=command["id"],
        action=command["action"],
        payload=command["payload"],
        requested_at=command["requested_at"],
        requested_by=command.get("requested_by"),
        pending_count=result["pending_count"],
    )


@router.get(
    "/{device_id}/commands",
    response_model=DeviceCommandStatus,
    dependencies=[Depends(require_permissions(P.DEVICE_READ))],
    summary="Pending commands and recent command results for a device",
)
async def list_device_commands(
    device_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
) -> DeviceCommandStatus:
    result = await DeviceCommandService(session, tenant_id).status(device_id)
    return DeviceCommandStatus(**result)


@router.post(
    "/{device_id}/probe",
    response_model=DeviceOut,
    dependencies=[Depends(require_permissions(P.DEVICE_EXEC))],
    summary="Poll the device through its OPNsense API",
)
async def probe_device(device: DeviceDep, session: SessionDep, tenant_id: TenantDep) -> DeviceOut:
    await DeviceMonitorService(session, tenant_id).poll_device(device.id)
    refreshed = await session.get(type(device), device.id)
    if refreshed is None:
        raise NotFoundError("Device not found")
    return DeviceOut.model_validate(refreshed)


# --------------------------------------------------------------------------- firmware
class FirmwareStatusOut(BaseModel):
    device_id: UUID
    device_name: str
    reachable: bool
    product_version: str | None = None
    product_name: str | None = None
    product_series: str | None = None
    current_version: str | None = None
    latest_release: str | None = None
    needs_upgrade: bool = False
    upgrade_available: bool = False
    raw_firmware: dict = Field(default_factory=dict)
    raw_info: dict = Field(default_factory=dict)


class FirmwareUpgradeRequest(BaseModel):
    package: str | None = Field(None, max_length=128)


class FirmwareActionOut(BaseModel):
    device_id: UUID
    device_name: str
    package: str | None = None
    status: str
    response: dict | None = None
    initiated_at: datetime


@router.get(
    "/{device_id}/firmware/status",
    response_model=FirmwareStatusOut,
    dependencies=[Depends(require_permissions(P.FIRMWARE_READ))],
    summary="Read firmware status and available releases from the OPNsense host",
)
async def firmware_status(device: DeviceDep, session: SessionDep, tenant_id: TenantDep) -> FirmwareStatusOut:
    from app.services.upgrade import FirmwareUpgradeService

    payload = await FirmwareUpgradeService(session, tenant_id).status(device.id)
    return FirmwareStatusOut(**payload)


@router.post(
    "/{device_id}/firmware/upgrade",
    response_model=FirmwareActionOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions(P.FIRMWARE_UPGRADE))],
    summary="Trigger an in-place OPNsense firmware upgrade",
)
async def firmware_upgrade(
    device_id: uuid.UUID,
    payload: FirmwareUpgradeRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> FirmwareActionOut:
    from app.services.upgrade import FirmwareUpgradeService

    result = await FirmwareUpgradeService(session, tenant_id, actor_id=principal.user_id).upgrade(
        device_id, package=payload.package
    )
    await session.commit()
    return FirmwareActionOut(**result)


@router.post(
    "/{device_id}/firmware/reboot",
    response_model=FirmwareActionOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions(P.FIRMWARE_REBOOT))],
    summary="Trigger an OPNsense reboot (used after an upgrade or restore)",
)
async def firmware_reboot(
    device_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> FirmwareActionOut:
    from app.services.upgrade import FirmwareUpgradeService

    result = await FirmwareUpgradeService(session, tenant_id, actor_id=principal.user_id).reboot(device_id)
    await session.commit()
    return FirmwareActionOut(**result)


# --------------------------------------------------------------------------- certificates
@router.get(
    "/{device_id}/certificates",
    response_model=list[CertificateOut],
    dependencies=[Depends(require_permissions(P.CERT_READ))],
    summary="Certificates issued to a device",
)
async def device_certificates(
    device: DeviceDep, session: SessionDep, tenant_id: TenantDep
) -> list[CertificateOut]:
    rows, _ = await UnitOfWork(session, tenant_id).certificates.list(
        filters={"device_id": device.id}, size=200, sort="created_at", order="desc"
    )
    return [_certificate_out(row) for row in rows]


@router.post(
    "/{device_id}/certificates",
    response_model=CertificateIssueResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.CERT_WRITE))],
    summary="Issue a device certificate",
)
async def issue_certificate(
    device: DeviceDep,
    payload: CertificateRequestBody,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> CertificateIssueResponse:
    record = await CertificateService(session, tenant_id, principal.user_id).issue(
        device_id=device.id,
        common_name=payload.common_name,
        validity_days=payload.validity_days,
    )
    await session.commit()
    return CertificateIssueResponse(
        serial_number=record.serial_number,
        certificate_pem=record.certificate_pem,
        ca_pem=ca.ca_pem,
        valid_to=record.valid_to,
    )


@certificates_router.get(
    "",
    response_model=PageResponse[CertificateOut],
    dependencies=[Depends(require_permissions(P.CERT_READ))],
    summary="List certificates",
)
async def list_certificates(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    status_filter: CertificateStatus | None = Query(None, alias="status"),
    device_id: uuid.UUID | None = None,
) -> PageResponse[CertificateOut]:
    filters: dict[str, object] = {"device_id": device_id}
    if status_filter is not None:
        filters["status"] = status_filter
    rows, total = await UnitOfWork(session, tenant_id).certificates.list(
        filters=filters,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "created_at",
        order=pagination.order,
    )
    return paginate([_certificate_out(row) for row in rows], total, pagination, CertificateOut)


@certificates_router.delete(
    "/{certificate_id}",
    response_model=CertificateOut,
    dependencies=[Depends(require_permissions(P.CERT_WRITE))],
    summary="Revoke a certificate",
)
async def revoke_certificate(
    certificate_id: uuid.UUID,
    payload: RevokeRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> CertificateOut:
    record = await CertificateService(session, tenant_id, principal.user_id).revoke(
        certificate_id, reason=payload.reason
    )
    await session.commit()
    return _certificate_out(record)


@certificates_router.get("/crl", summary="Download the device CRL (PEM)")
async def certificate_crl(session: SessionDep, tenant_id: TenantDep) -> dict[str, str]:
    # CRL retrieval is authenticated but intentionally available to read-only operators:
    # OPNsense needs it to validate peers during TLS handshakes.
    pem = await CertificateService(session, tenant_id).crl()
    return {"crl_pem": pem}
