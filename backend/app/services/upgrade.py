"""OPNsense firmware lifecycle: status probe, in-place upgrade and reboot.

The service talks to the device through the typed OPNsense REST client and never
executes shell on the operator host. All side effects are audited.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, UpstreamError
from app.core.logging import get_logger
from app.models.topology import Device
from app.repositories import UnitOfWork
from app.services.audit import AuditService

log = get_logger("ofme.upgrade")


class FirmwareUpgradeService:
    """Read firmware status and trigger upgrades/reboots on a managed host."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ helpers
    async def _device(self, device_id: uuid.UUID) -> Device:
        return await self.uow.devices.get_or_404(device_id)

    @asynccontextmanager
    async def _client_for(self, device: Device) -> AsyncIterator[Any]:
        """Yield an OPNsense API client bound to the device's stored credentials."""
        from app.integrations.opnsense.client import client_for
        from app.services.devices import DeviceService

        base_url, key, secret = await DeviceService(self.session, self.tenant_id).credentials(device)
        async with client_for(base_url, key, secret) as client:
            yield client

    # ------------------------------------------------------------------ reads
    async def status(self, device_id: uuid.UUID) -> dict[str, Any]:
        device = await self._device(device_id)
        async with self._client_for(device) as client:
            firmware = await client.firmware_status()
            info = await client.firmware_info()

        if firmware is None and info is None:
            raise UpstreamError(
                f"Device '{device.name}' does not expose /api/core/firmware/status",
                details={"device_id": str(device_id)},
            )

        product = firmware.get("product", {}) if isinstance(firmware, dict) else {}
        running = None
        if isinstance(firmware, dict):
            running = (
                firmware.get("product_version") or product.get("product_version") or firmware.get("version")
            )
        latest = (info or {}).get("latest") if isinstance(info, dict) else None
        needs_upgrade = bool(latest and running and latest != running)
        upgrade_available = needs_upgrade
        if isinstance(info, dict):
            upgrade_available = upgrade_available or bool(info.get("upgrade_available"))
        payload: dict[str, Any] = {
            "device_id": str(device.id),
            "device_name": device.name,
            "reachable": True,
            "product_version": running,
            "product_name": product.get("name") if isinstance(product, dict) else None,
            "product_series": product.get("series") if isinstance(product, dict) else None,
            "current_version": device.firmware_version,
            "latest_release": latest,
            "needs_upgrade": needs_upgrade,
            "upgrade_available": upgrade_available,
            "raw_firmware": firmware or {},
            "raw_info": info or {},
        }
        return payload

    # ------------------------------------------------------------------ writes
    async def upgrade(self, device_id: uuid.UUID, *, package: str | None = None) -> dict[str, Any]:
        device = await self._device(device_id)
        if not package and not device.firmware_version:
            raise BadRequestError(
                f"Cannot upgrade '{device.name}': no package given and no recorded firmware version"
            )

        async with self._client_for(device) as client:
            response = await client.upgrade_firmware(package=package)

        device.firmware_version = None  # version unknown until the host reboots
        await self.session.flush()
        await self.audit.record(
            action="firmware.upgrade",
            resource_type="Device",
            resource_id=device.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"package": package, "response": str(response)[:500]},
        )
        return {
            "device_id": str(device.id),
            "device_name": device.name,
            "package": package,
            "status": "initiated",
            "response": response,
            "initiated_at": datetime.now(UTC).isoformat(),
        }

    async def reboot(self, device_id: uuid.UUID) -> dict[str, Any]:
        device = await self._device(device_id)
        async with self._client_for(device) as client:
            response = await client.reboot()

        await self.audit.record(
            action="firmware.reboot",
            resource_type="Device",
            resource_id=device.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"response": str(response)[:500]},
        )
        return {
            "device_id": str(device.id),
            "device_name": device.name,
            "status": "initiated",
            "response": response,
            "initiated_at": datetime.now(UTC).isoformat(),
        }


async def firmware_status(
    device_id: uuid.UUID, session: AsyncSession, tenant_id: uuid.UUID
) -> dict[str, Any]:
    return await FirmwareUpgradeService(session, tenant_id).status(device_id)


async def firmware_upgrade(
    device_id: uuid.UUID,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    package: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    service = FirmwareUpgradeService(session, tenant_id, actor_id=actor_id)
    return await service.upgrade(device_id, package=package)


async def firmware_reboot(
    device_id: uuid.UUID,
    session: AsyncSession,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return await FirmwareUpgradeService(session, tenant_id, actor_id=actor_id).reboot(device_id)
