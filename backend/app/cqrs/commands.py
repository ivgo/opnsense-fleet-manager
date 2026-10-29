"""CQRS messages and handler registration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.cqrs.bus import Command, Query, command_bus, query_bus
from app.models.enums import BackupType, ComplianceFramework, DeviceStatus
from app.schemas.topology import DeviceCreate, DeviceUpdate
from app.services.backup import BackupService
from app.services.compliance import ComplianceService
from app.services.devices import DeviceService
from app.services.monitoring import DashboardService


# --------------------------------------------------------------------------- commands
@dataclass(slots=True)
class CreateDevice(Command[Any]):
    session: AsyncSession
    tenant_id: uuid.UUID
    actor_id: uuid.UUID | None
    payload: DeviceCreate


@dataclass(slots=True)
class UpdateDevice(Command[Any]):
    session: AsyncSession
    tenant_id: uuid.UUID
    actor_id: uuid.UUID | None
    device_id: uuid.UUID
    payload: DeviceUpdate


@dataclass(slots=True)
class DeleteDevice(Command[None]):
    session: AsyncSession
    tenant_id: uuid.UUID
    actor_id: uuid.UUID | None
    device_id: uuid.UUID


@dataclass(slots=True)
class SetMaintenanceMode(Command[Any]):
    session: AsyncSession
    tenant_id: uuid.UUID
    device_id: uuid.UUID
    enabled: bool


@dataclass(slots=True)
class CreateBackup(Command[Any]):
    session: AsyncSession
    tenant_id: uuid.UUID
    actor_id: uuid.UUID | None
    device_id: uuid.UUID
    backup_type: BackupType = BackupType.MANUAL
    notes: str | None = None


@dataclass(slots=True)
class RunCompliance(Command[Any]):
    session: AsyncSession
    tenant_id: uuid.UUID
    actor_id: uuid.UUID | None
    framework: ComplianceFramework
    device_ids: list[uuid.UUID]


# --------------------------------------------------------------------------- queries
@dataclass(slots=True)
class DashboardSummary(Query[dict[str, Any]]):
    session: AsyncSession
    tenant_id: uuid.UUID


@dataclass(slots=True)
class ListDevices(Query[Any]):
    session: AsyncSession
    tenant_id: uuid.UUID
    page: int = 1
    size: int = 50
    search: str | None = None
    status: DeviceStatus | None = None
    site_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- handlers
async def _create_device(command: CreateDevice) -> Any:
    return await DeviceService(command.session, command.tenant_id, command.actor_id).create(command.payload)


async def _update_device(command: UpdateDevice) -> Any:
    return await DeviceService(command.session, command.tenant_id, command.actor_id).update(
        command.device_id, command.payload
    )


async def _delete_device(command: DeleteDevice) -> None:
    await DeviceService(command.session, command.tenant_id, command.actor_id).delete(command.device_id)


async def _set_maintenance(command: SetMaintenanceMode) -> Any:
    return await DeviceService(command.session, command.tenant_id).mark_maintenance(
        command.device_id, command.enabled
    )


async def _create_backup(command: CreateBackup) -> Any:
    return await BackupService(command.session, command.tenant_id, command.actor_id).create_backup(
        command.device_id, backup_type=command.backup_type, notes=command.notes
    )


async def _run_compliance(command: RunCompliance) -> Any:
    return await ComplianceService(command.session, command.tenant_id, command.actor_id).run(
        command.framework, command.device_ids
    )


async def _dashboard_summary(query: DashboardSummary) -> dict[str, Any]:
    return await DashboardService(query.session, query.tenant_id).summary()


async def _list_devices(query: ListDevices) -> Any:
    devices, total = await DeviceService(query.session, query.tenant_id).list(
        page=query.page,
        size=query.size,
        search=query.search,
        status=query.status.value if query.status else None,
        site_id=query.site_id,
        group_id=query.group_id,
    )
    return devices, total


def register_handlers() -> None:
    command_bus.register(CreateDevice, _create_device)
    command_bus.register(UpdateDevice, _update_device)
    command_bus.register(DeleteDevice, _delete_device)
    command_bus.register(SetMaintenanceMode, _set_maintenance)
    command_bus.register(CreateBackup, _create_backup)
    command_bus.register(RunCompliance, _run_compliance)

    query_bus.register(DashboardSummary, _dashboard_summary)
    query_bus.register(ListDevices, _list_devices)
