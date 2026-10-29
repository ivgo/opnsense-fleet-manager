"""Maintenance windows (quiet hours) and their effect on alerting.

A window suppresses alert creation and/or external notifications for a fleet,
a set of devices, sites or groups. The matcher is pure so the semantics can be
unit-tested without a database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.models.enums import MaintenanceTarget
from app.models.operations import MaintenanceWindow
from app.models.topology import Device
from app.repositories import UnitOfWork
from app.schemas.operations import MaintenanceWindowCreate, MaintenanceWindowOut, MaintenanceWindowUpdate
from app.services.audit import AuditService


def window_matches(window: MaintenanceWindow, device: Device) -> bool:
    """Whether ``window`` covers ``device`` (the time range is checked elsewhere)."""
    target = window.target_type
    if isinstance(target, str):
        target = MaintenanceTarget(target)
    if target == MaintenanceTarget.FLEET:
        return True
    ids = {str(item) for item in (window.target_ids or [])}
    if target == MaintenanceTarget.DEVICE:
        return str(device.id) in ids
    if target == MaintenanceTarget.SITE:
        return device.site_id is not None and str(device.site_id) in ids
    if target == MaintenanceTarget.GROUP:
        return device.group_id is not None and str(device.group_id) in ids
    return False


def is_silenced(
    windows: list[MaintenanceWindow], device: Device, *, notifications: bool = False
) -> bool:
    """True when an active window suppresses alerts (or just notifications)."""
    for window in windows:
        if not window.enabled:
            continue
        if notifications and not window.silence_notifications:
            continue
        if not notifications and not window.silence_alerts:
            continue
        if window_matches(window, device):
            return True
    return False


def _as_out(window: MaintenanceWindow, now: datetime) -> MaintenanceWindowOut:
    data = MaintenanceWindowOut.model_validate(window)
    return data.model_copy(
        update={"active": window.enabled and window.starts_at <= now < window.ends_at}
    )


class MaintenanceWindowService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.audit = AuditService(session)

    async def list(self) -> list[MaintenanceWindowOut]:
        now = datetime.now(UTC)
        windows, _ = await self.uow.maintenance.list(sort="starts_at", order="desc")
        return [_as_out(window, now) for window in windows]

    async def active(self) -> list[MaintenanceWindowOut]:
        now = datetime.now(UTC)
        return [_as_out(window, now) for window in await self.uow.maintenance.active_at(now)]

    async def create(self, payload: MaintenanceWindowCreate) -> MaintenanceWindowOut:
        window = MaintenanceWindow(
            tenant_id=self.tenant_id,
            name=payload.name,
            description=payload.description,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            enabled=payload.enabled,
            target_type=payload.target_type,
            target_ids=[str(item) for item in payload.target_ids],
            silence_alerts=payload.silence_alerts,
            silence_notifications=payload.silence_notifications,
            created_by=self.actor_id,
        )
        self.session.add(window)
        await self.session.flush()
        await self.audit.record(
            action="maintenance_window.created",
            resource_type="MaintenanceWindow",
            resource_id=window.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "name": window.name,
                "starts_at": window.starts_at.isoformat(),
                "ends_at": window.ends_at.isoformat(),
                "target_type": window.target_type.value,
                "target_ids": window.target_ids,
            },
        )
        await self.session.commit()
        return _as_out(window, datetime.now(UTC))

    async def update(
        self, window_id: uuid.UUID, payload: MaintenanceWindowUpdate
    ) -> MaintenanceWindowOut:
        window = await self.uow.maintenance.get_or_404(window_id)
        data = payload.model_dump(exclude_unset=True)
        if "target_ids" in data and data["target_ids"] is not None:
            data["target_ids"] = [str(item) for item in data["target_ids"]]
        starts_at = data.get("starts_at", window.starts_at)
        ends_at = data.get("ends_at", window.ends_at)
        if ends_at <= starts_at:
            raise BadRequestError("ends_at must be after starts_at")
        target_type = data.get("target_type", window.target_type)
        target_ids = data.get("target_ids", window.target_ids)
        if target_type != MaintenanceTarget.FLEET and not target_ids:
            raise BadRequestError("target_ids is required for a device, site or group window")
        before = {
            "name": window.name,
            "starts_at": window.starts_at.isoformat(),
            "ends_at": window.ends_at.isoformat(),
            "enabled": window.enabled,
        }
        for key, value in data.items():
            setattr(window, key, value)
        await self.session.flush()
        await self.audit.record(
            action="maintenance_window.updated",
            resource_type="MaintenanceWindow",
            resource_id=window.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before=before,
            after={
                "name": window.name,
                "starts_at": window.starts_at.isoformat(),
                "ends_at": window.ends_at.isoformat(),
                "enabled": window.enabled,
            },
        )
        await self.session.commit()
        return _as_out(window, datetime.now(UTC))

    async def delete(self, window_id: uuid.UUID) -> None:
        window = await self.uow.maintenance.get_or_404(window_id)
        await self.session.delete(window)
        await self.audit.record(
            action="maintenance_window.deleted",
            resource_type="MaintenanceWindow",
            resource_id=window_id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before={"name": window.name},
        )
        await self.session.commit()

    async def silence_state(self, device: Device) -> tuple[bool, bool]:
        """Return ``(suppress_alerts, suppress_notifications)`` for a device."""
        now = datetime.now(UTC)
        windows = await self.uow.maintenance.active_at(now)
        return (
            is_silenced(windows, device),
            is_silenced(windows, device, notifications=True),
        )
