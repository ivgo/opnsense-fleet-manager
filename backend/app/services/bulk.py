"""Bulk device operations and CSV import/export."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.enums import MaintenanceTarget
from app.repositories import UnitOfWork
from app.schemas.operations import (
    BulkDeviceAction,
    BulkDeviceResponse,
    BulkDeviceResult,
    CsvImportError,
    CsvImportResult,
    MaintenanceWindowCreate,
)
from app.schemas.topology import DeviceCreate
from app.services.audit import AuditService
from app.services.backup import BackupService
from app.services.devices import DeviceCommandService, DeviceService
from app.services.maintenance import MaintenanceWindowService
from app.workers.dispatch import (
    TASK_FIRMWARE_REBOOT,
    TASK_FIRMWARE_UPGRADE,
    enqueue,
)

log = get_logger("ofme.bulk")

CSV_COLUMNS = (
    "name",
    "hostname",
    "description",
    "ip_address",
    "api_port",
    "serial_number",
    "model",
    "tags",
    "site",
)


class BulkDeviceService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.audit = AuditService(session)

    async def run(self, payload: BulkDeviceAction) -> BulkDeviceResponse:
        results: list[BulkDeviceResult] = []
        if payload.action in ("maintenance_on", "maintenance_off"):
            results = await self._maintenance(payload)
        elif payload.action == "command":
            results = await self._command(payload)
        elif payload.action == "backup":
            results = await self._backup(payload)
        elif payload.action in ("firmware_upgrade", "reboot"):
            results = await self._firmware(payload)
        else:  # pragma: no cover - schema Literal guards this
            raise NotFoundError(f"Unsupported bulk action '{payload.action}'")

        succeeded = sum(1 for item in results if item.status == "ok")
        failed = sum(1 for item in results if item.status == "failed")
        await self.audit.record(
            action=f"device.bulk.{payload.action}",
            resource_type="Device",
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "action": payload.action,
                "device_ids": [str(item) for item in payload.device_ids],
                "succeeded": succeeded,
                "failed": failed,
            },
        )
        await self.session.commit()
        return BulkDeviceResponse(
            action=payload.action,
            total=len(results),
            succeeded=succeeded,
            failed=failed,
            results=results,
        )

    # ------------------------------------------------------------------ actions
    async def _devices(self, device_ids: list[uuid.UUID]) -> list[Any]:
        found: list[Any] = []
        for device_id in device_ids:
            device = await self.uow.devices.get(device_id)
            if device is not None:
                found.append(device)
        return found

    async def _maintenance(self, payload: BulkDeviceAction) -> list[BulkDeviceResult]:
        devices = await self._devices(payload.device_ids)
        known = {device.id for device in devices}
        results = [
            BulkDeviceResult(
                device_id=device_id,
                name=str(device_id),
                status="skipped",
                message="Device not found",
            )
            for device_id in payload.device_ids
            if device_id not in known
        ]

        if payload.action == "maintenance_on":
            minutes = int(payload.params.get("duration_minutes") or 60)
            now = datetime.now(UTC)
            window = await MaintenanceWindowService(
                self.session, self.tenant_id, self.actor_id
            ).create(
                MaintenanceWindowCreate(
                    name=payload.params.get("name")
                    or f"Bulk maintenance {now:%Y-%m-%d %H:%M}",
                    description=payload.params.get("description"),
                    starts_at=now,
                    ends_at=now + timedelta(minutes=minutes),
                    target_type=MaintenanceTarget.DEVICE,
                    target_ids=[device.id for device in devices],
                )
            )
            results.extend(
                BulkDeviceResult(
                    device_id=device.id,
                    name=device.name,
                    status="ok",
                    message=f"Maintenance window '{window.name}' until {window.ends_at:%Y-%m-%d %H:%M} UTC",
                )
                for device in devices
            )
            return results

        # maintenance_off: disable every active window covering these devices.
        now = datetime.now(UTC)
        windows = await self.uow.maintenance.active_at(now)
        target_ids = {str(device.id) for device in devices}
        disabled: set[str] = set()
        for window in windows:
            window_ids = {str(item) for item in (window.target_ids or [])}
            if window.target_type == MaintenanceTarget.FLEET or window_ids & target_ids:
                window.enabled = False
                disabled.add(str(window.id))
        await self.session.flush()
        message = (
            f"Disabled {len(disabled)} maintenance window(s)" if disabled else "No active window"
        )
        results.extend(
            BulkDeviceResult(
                device_id=device.id,
                name=device.name,
                status="ok" if disabled else "skipped",
                message=message,
            )
            for device in devices
        )
        return results

    async def _command(self, payload: BulkDeviceAction) -> list[BulkDeviceResult]:
        action = str(payload.params.get("action") or "collect_diagnostics")
        command_payload = payload.params.get("payload")
        if not isinstance(command_payload, dict):
            command_payload = {}
        service = DeviceCommandService(self.session, self.tenant_id, self.actor_id)
        results: list[BulkDeviceResult] = []
        for device_id in payload.device_ids:
            try:
                outcome = await service.dispatch(device_id, action, command_payload)
            except (NotFoundError, ConflictError, ValueError) as exc:
                results.append(
                    BulkDeviceResult(
                        device_id=device_id, name=str(device_id), status="failed", message=str(exc)
                    )
                )
                continue
            device = await self.uow.devices.get(device_id)
            results.append(
                BulkDeviceResult(
                    device_id=device_id,
                    name=device.name if device else str(device_id),
                    status="ok",
                    message=f"Queued command {outcome['command']['id']}",
                )
            )
        await self.session.flush()
        return results

    async def _backup(self, payload: BulkDeviceAction) -> list[BulkDeviceResult]:
        service = BackupService(self.session, self.tenant_id, self.actor_id)
        results: list[BulkDeviceResult] = []
        for device_id in payload.device_ids:
            device = await self.uow.devices.get(device_id)
            if device is None:
                results.append(
                    BulkDeviceResult(
                        device_id=device_id,
                        name=str(device_id),
                        status="skipped",
                        message="Device not found",
                    )
                )
                continue
            try:
                backup = await service.create_backup(device_id, notes="Bulk backup")
            except Exception as exc:  # noqa: BLE001 - report per device, keep the batch going
                results.append(
                    BulkDeviceResult(
                        device_id=device_id, name=device.name, status="failed", message=str(exc)
                    )
                )
                continue
            results.append(
                BulkDeviceResult(
                    device_id=device_id,
                    name=device.name,
                    status="ok",
                    message=f"Backup {backup.id} ({backup.size_bytes or 0} bytes)",
                )
            )
        return results

    async def _firmware(self, payload: BulkDeviceAction) -> list[BulkDeviceResult]:
        devices = await self._devices(payload.device_ids)
        known = {device.id for device in devices}
        results = [
            BulkDeviceResult(
                device_id=device_id,
                name=str(device_id),
                status="skipped",
                message="Device not found",
            )
            for device_id in payload.device_ids
            if device_id not in known
        ]
        if not devices:
            return results
        task = TASK_FIRMWARE_UPGRADE if payload.action == "firmware_upgrade" else TASK_FIRMWARE_REBOOT
        params: dict[str, Any] = {"device_ids": [str(device.id) for device in devices]}
        if payload.params.get("package"):
            params["package"] = payload.params["package"]
        job = await enqueue(
            self.session,
            tenant_id=self.tenant_id,
            task_name=task,
            params=params,
            actor_id=self.actor_id,
        )
        results.extend(
            BulkDeviceResult(
                device_id=device.id,
                name=device.name,
                status="ok",
                message=f"Queued job {job.id}",
            )
            for device in devices
        )
        return results

    # --------------------------------------------------------------------- CSV
    async def export_csv(self) -> str:
        devices, _ = await self.uow.devices.list(size=1000, sort="name", order="asc")
        sites, _ = await self.uow.sites.list(size=1000)
        site_names = {site.id: site.name for site in sites}
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for device in devices:
            writer.writerow(
                {
                    "name": device.name,
                    "hostname": device.hostname or "",
                    "description": device.description or "",
                    "ip_address": device.ip_address or "",
                    "api_port": device.api_port,
                    "serial_number": device.serial_number or "",
                    "model": device.model or "",
                    "tags": ";".join(device.tags or []),
                    "site": site_names.get(device.site_id, "") if device.site_id else "",
                }
            )
        return buffer.getvalue()

    async def import_csv(self, data: bytes) -> CsvImportResult:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        reader = csv.DictReader(io.StringIO(text))
        missing = [column for column in ("name",) if column not in (reader.fieldnames or [])]
        if missing:
            raise ConflictError(f"CSV is missing required column(s): {', '.join(missing)}")

        sites, _ = await self.uow.sites.list(size=1000)
        site_by_name = {site.name.lower(): site.id for site in sites}
        site_by_code = {
            str(site.code).lower(): site.id for site in sites if getattr(site, "code", None)
        }
        service = DeviceService(self.session, self.tenant_id, self.actor_id)
        created = skipped = 0
        errors: list[CsvImportError] = []
        devices: list[dict[str, Any]] = []

        for row_number, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            if not name:
                errors.append(CsvImportError(row=row_number, error="Missing device name"))
                continue
            site_name = (row.get("site") or "").strip().lower()
            site_id = site_by_name.get(site_name) or site_by_code.get(site_name)
            tags = [tag.strip() for tag in (row.get("tags") or "").split(";") if tag.strip()]
            try:
                port = int((row.get("api_port") or "443").strip() or 443)
                device = await service.create(
                    DeviceCreate(
                        name=name,
                        hostname=(row.get("hostname") or "").strip() or None,
                        description=(row.get("description") or "").strip() or None,
                        ip_address=(row.get("ip_address") or "").strip() or None,
                        api_port=port,
                        serial_number=(row.get("serial_number") or "").strip() or None,
                        model=(row.get("model") or "").strip() or None,
                        tags=tags,
                        site_id=site_id,
                    )
                )
            except ConflictError:
                skipped += 1
                continue
            except Exception as exc:  # noqa: BLE001 - report the row and continue
                errors.append(CsvImportError(row=row_number, error=str(exc)))
                continue
            created += 1
            devices.append({"id": str(device.id), "name": device.name})

        return CsvImportResult(created=created, skipped=skipped, errors=errors, devices=devices)


__all__ = ["BulkDeviceService", "CSV_COLUMNS"]
