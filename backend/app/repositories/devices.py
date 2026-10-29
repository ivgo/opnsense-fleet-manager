from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.models.enums import ConnectionStatus, DeviceStatus
from app.models.topology import Device, DeviceCertificate, DeviceGroup, Site
from app.repositories.base import BaseRepository


class SiteRepository(BaseRepository[Site]):
    model = Site


class DeviceGroupRepository(BaseRepository[DeviceGroup]):
    model = DeviceGroup

    async def children(self, parent_id: uuid.UUID) -> list[DeviceGroup]:
        stmt = self.query().where(DeviceGroup.parent_id == parent_id)
        return list((await self.session.execute(stmt)).scalars().all())


class DeviceRepository(BaseRepository[Device]):
    model = Device

    async def get_by_name(self, name: str) -> Device | None:
        return await self.find_one(name=name)

    async def get_by_serial(self, serial: str) -> Device | None:
        stmt = self.query().where(Device.serial_number == serial)
        return (await self.session.execute(stmt)).scalars().first()

    async def by_status_counts(self) -> dict[str, int]:
        stmt = (
            select(Device.status, func.count())
            .where(Device.tenant_id == self.tenant_id, Device.deleted_at.is_(None))
            .group_by(Device.status)
        )
        rows = (await self.session.execute(stmt)).all()
        return {status.value: 0 for status in DeviceStatus} | {
            str(row[0].value if hasattr(row[0], "value") else row[0]): row[1] for row in rows
        }

    async def stale(self, offline_after_seconds: int) -> list[Device]:
        cutoff = datetime.utcnow() - timedelta(seconds=offline_after_seconds)
        stmt = self.query().where(
            Device.status.in_([DeviceStatus.ONLINE, DeviceStatus.REGISTERED]),
            Device.last_heartbeat_at.is_not(None),
            Device.last_heartbeat_at < cutoff,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def mark_offline(self, offline_after_seconds: int) -> int:
        devices = await self.stale(offline_after_seconds)
        for device in devices:
            device.status = DeviceStatus.OFFLINE
            device.connection_status = ConnectionStatus.DISCONNECTED
        await self.session.flush()
        return len(devices)

    async def record_heartbeat(
        self,
        device_id: uuid.UUID,
        *,
        firmware_version: str | None = None,
        hostname: str | None = None,
        uptime_seconds: int | None = None,
        agent_version: str | None = None,
    ) -> Device:
        device = await self.get_or_404(device_id)
        now = datetime.utcnow()
        device.last_heartbeat_at = now
        device.last_seen_at = now
        device.status = DeviceStatus.ONLINE
        device.connection_status = ConnectionStatus.CONNECTED
        if firmware_version:
            device.firmware_version = firmware_version
        if hostname:
            device.hostname = hostname
        if uptime_seconds is not None:
            device.uptime_seconds = uptime_seconds
        if agent_version:
            device.agent_version = agent_version
        await self.session.flush()
        return device

    async def search(self, term: str, limit: int = 20) -> list[Device]:
        stmt = (
            self.query()
            .where(
                Device.name.ilike(f"%{term}%")
                | Device.hostname.ilike(f"%{term}%")
                | Device.ip_address.ilike(f"%{term}%")
                | Device.serial_number.ilike(f"%{term}%")
            )
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class DeviceCertificateRepository(BaseRepository[DeviceCertificate]):
    model = DeviceCertificate
    soft_delete = False

    async def active_for_device(self, device_id: uuid.UUID) -> DeviceCertificate | None:
        stmt = (
            self.query()
            .where(DeviceCertificate.device_id == device_id, DeviceCertificate.status == "active")
            .order_by(DeviceCertificate.valid_to.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def expiring_before(self, when: datetime) -> list[DeviceCertificate]:
        stmt = self.query().where(DeviceCertificate.valid_to <= when, DeviceCertificate.status == "active")
        return list((await self.session.execute(stmt)).scalars().all())
