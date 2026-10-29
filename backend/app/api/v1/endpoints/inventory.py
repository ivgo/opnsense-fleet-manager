"""Inventory endpoints: client devices discovered via ARP/DHCP/LLDP."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import SessionDep, TenantDep, require_permissions
from app.models.inventory import ClientDevice, ClientSource, ClientStatus
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.operations import ClientDeviceBlock, ClientDeviceOut, ClientDevicePause, Message, VendorInfo
from app.services.inventory import InventoryService

router = APIRouter(prefix="/inventory", tags=["Inventory"])

# Simple OUI mapping – in production, use mac-vendor-lookup package
OUI_MAP = {
    "00:00:00": "Xerox",
    "00:00:5E": "IANA",
    "00:0C:29": "VMware",
    "00:15:5D": "Microsoft Hyper-V",
    "00:1A:2B": "QEMU",
    "00:50:56": "VMware",
    "08:00:27": "VirtualBox",
    "52:54:00": "QEMU/KVM",
    "AA:AA:AA": "AA:AA:AA:AA:AA:AA",
}


def _oui_lookup(mac: str) -> str | None:
    """Quick OUI lookup from MAC prefix."""
    prefix = mac.upper().replace("-", ":")[:8]
    return OUI_MAP.get(prefix)


@router.get(
    "/clients",
    response_model=list[ClientDeviceOut],
    dependencies=[Depends(require_permissions(P.INVENTORY_READ))],
    summary="List client devices",
)
async def list_clients(
    session: SessionDep,
    tenant_id: TenantDep,
    status: ClientStatus | None = Query(None),
    source: ClientSource | None = Query(None),
    search: str | None = Query(None, max_length=64),
    limit: int = Query(200, ge=1, le=1000),
) -> list[ClientDeviceOut]:
    """List client devices discovered via ARP/DHCP/LLDP."""
    uow = UnitOfWork(session, tenant_id)
    stmt = select(ClientDevice).where(ClientDevice.tenant_id == tenant_id)

    if status:
        stmt = stmt.where(ClientDevice.status == status)
    if source:
        stmt = stmt.where(ClientDevice.source == source)
    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            (ClientDevice.mac_address.ilike(search_term))
            | (ClientDevice.ip_address.ilike(search_term))
            | (ClientDevice.hostname.ilike(search_term))
        )

    stmt = stmt.order_by(ClientDevice.last_seen.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()

    return [
        ClientDeviceOut(
            id=str(row.id),
            mac_address=row.mac_address,
            ip_address=row.ip_address,
            hostname=row.hostname,
            vendor=row.vendor,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            source=row.source.value,
            status=row.status.value,
            paused_until=row.paused_until,
        )
        for row in rows
    ]


@router.get(
    "/clients/{mac}",
    response_model=ClientDeviceOut,
    dependencies=[Depends(require_permissions(P.INVENTORY_READ))],
    summary="Get client device by MAC",
)
async def get_client(
    mac: str,
    session: SessionDep,
    tenant_id: TenantDep,
) -> ClientDeviceOut:
    """Get a single client device by MAC address."""
    uow = UnitOfWork(session, tenant_id)
    stmt = select(ClientDevice).where(
        ClientDevice.tenant_id == tenant_id,
        ClientDevice.mac_address == mac.upper().replace("-", ":"),
    )
    row = (await session.execute(stmt)).scalars().first()

    if not row:
        raise HTTPException(status_code=404, detail="Client not found")

    return ClientDeviceOut(
        id=str(row.id),
        mac_address=row.mac_address,
        ip_address=row.ip_address,
        hostname=row.hostname,
        vendor=row.vendor,
        first_seen=row.first_seen,
        last_seen=row.last_seen,
        source=row.source.value,
        status=row.status.value,
        paused_until=row.paused_until,
    )


@router.post(
    "/clients/{mac}/block",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.INVENTORY_WRITE))],
    summary="Block a client device",
)
async def block_client(
    mac: str,
    session: SessionDep,
    tenant_id: TenantDep,
    payload: ClientDeviceBlock,
) -> Message:
    """Block a client device by adding it to the BLOCKED_CLIENTS firewall alias."""
    service = InventoryService(session, tenant_id)
    success = await service.block_client(mac, payload.reason)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to block client")

    return Message(message=f"Client {mac} blocked successfully")


@router.post(
    "/clients/{mac}/pause",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.INVENTORY_WRITE))],
    summary="Pause a client device",
)
async def pause_client(
    mac: str,
    session: SessionDep,
    tenant_id: TenantDep,
    payload: ClientDevicePause,
) -> Message:
    """Pause a client device for N minutes (temporary block)."""
    service = InventoryService(session, tenant_id)
    success = await service.pause_client(mac, payload.minutes, payload.reason)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to pause client")

    return Message(message=f"Client {mac} paused for {payload.minutes} minutes")


@router.post(
    "/clients/{mac}/unblock",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.INVENTORY_WRITE))],
    summary="Unblock a client device",
)
async def unblock_client(
    mac: str,
    session: SessionDep,
    tenant_id: TenantDep,
) -> Message:
    """Unblock a client device by removing it from the BLOCKED_CLIENTS alias."""
    service = InventoryService(session, tenant_id)
    success = await service.unblock_client(mac)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to unblock client")

    return Message(message=f"Client {mac} unblocked successfully")


@router.post(
    "/vendors",
    response_model=list[VendorInfo],
    dependencies=[Depends(require_permissions(P.INVENTORY_READ))],
    summary="Lookup vendor info for MAC addresses",
)
async def vendor_lookup(
    session: SessionDep,
    tenant_id: TenantDep,
    macs: list[str],
) -> list[VendorInfo]:
    """Lookup vendor information for MAC address prefixes."""
    results = []
    for mac in macs:
        prefix = mac.upper().replace("-", ":")[:8]
        vendor = _oui_lookup(prefix)
        if vendor:
            results.append(
                VendorInfo(
                    mac_prefix=prefix,
                    vendor_name=vendor,
                )
            )

    return results