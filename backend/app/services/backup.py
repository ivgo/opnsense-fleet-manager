"""Backup & restore: signed, checksummed configuration snapshots in object storage."""

from __future__ import annotations

import gzip
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.exceptions import InvalidTag
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError, UpstreamError
from app.core.logging import get_logger
from app.core.security import (
    decrypt_bytes,
    encrypt_bytes,
    sign_payload,
    verify_signature,
)
from app.integrations.opnsense.client import client_for
from app.integrations.storage import ObjectStorage, get_storage
from app.models.enums import BackupType
from app.models.operations import Backup
from app.repositories import UnitOfWork
from app.services.audit import AuditService
from app.services.devices import DeviceService

log = get_logger("ofme.backup")


@dataclass(slots=True)
class BackupVerification:
    backup_id: uuid.UUID
    checksum_ok: bool
    signature_ok: bool
    stored_checksum: str
    computed_checksum: str
    size_bytes: int

    @property
    def valid(self) -> bool:
        return self.checksum_ok and self.signature_ok


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _coerce_type(value: BackupType | str) -> BackupType:
    if isinstance(value, BackupType):
        return value
    try:
        return BackupType(str(value))
    except ValueError as exc:
        raise BadRequestError(f"Unknown backup type '{value}'") from exc


class BackupService:
    """Creates, verifies, downloads and prunes device configuration backups.

    Every artifact is gzip-compressed and stored with a SHA-256 checksum plus an
    HMAC-SHA256 signature derived from the platform key material. Both are
    verified before a restore is permitted.
    """

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        storage: ObjectStorage | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.devices = DeviceService(session, tenant_id, actor_id)
        self.audit = AuditService(session)
        self.storage = storage or get_storage()
        self.restore_service = RestoreService(session, tenant_id, actor_id, storage=self.storage)

    # ------------------------------------------------------------------ create
    async def create_backup(
        self,
        device_id: uuid.UUID,
        *,
        backup_type: BackupType | str = BackupType.MANUAL,
        notes: str | None = None,
    ) -> Backup:
        kind = _coerce_type(backup_type)
        device = await self.devices.get(device_id)
        base_url, key, secret = await self.devices.credentials(device)

        async with client_for(base_url, key, secret) as client:
            raw = await client.download_config()
        if not raw:
            raise UpstreamError(f"OPNsense returned an empty configuration for '{device.name}'")

        compressed = gzip.compress(raw, compresslevel=6)
        # Encrypt before the artifact leaves the process: the signing key and the
        # encryption key are derived from the platform secret, and the object
        # store only ever sees ciphertext. This keeps backups confidential even
        # on a MinIO/S3 deployment without server-side encryption.
        encrypted = encrypt_bytes(compressed)
        checksum = _sha256(raw)
        signature = sign_payload(raw)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        storage_key = f"{self.tenant_id}/devices/{device.id}/{stamp}-{kind.value}-{checksum[:12]}.xml.gz.enc"

        stored = await self.storage.aput_bytes(
            storage_key,
            encrypted,
            bucket=self.storage.buckets["backups"],
            content_type="application/octet-stream",
            metadata={
                "device_id": str(device.id),
                "device_name": device.name[:120],
                "tenant_id": str(self.tenant_id),
                "backup_type": kind.value,
                "checksum": checksum,
                "encryption": "aes-256-gcm",
            },
        )

        backup = Backup(
            tenant_id=self.tenant_id,
            device_id=device.id,
            type=kind,
            storage_key=stored.key,
            checksum_sha256=checksum,
            signature=signature,
            size_bytes=len(raw),
            firmware_version=device.firmware_version,
            config_version=device.config_version,
            notes=notes,
            is_encrypted=True,
            created_by=self.actor_id,
        )
        self.session.add(backup)
        await self.session.flush()
        await self.audit.record(
            action="backup.created",
            resource_type="Backup",
            resource_id=backup.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "device_id": str(device.id),
                "type": kind.value,
                "size_bytes": backup.size_bytes,
                "checksum": checksum,
            },
        )
        await self.session.commit()
        log.info("backup.created", device=device.name, size=len(raw), type=kind.value)
        return backup

    async def create_for_all(
        self, *, backup_type: BackupType | str = BackupType.SCHEDULED, limit: int = 500
    ) -> dict[str, int]:
        devices, _ = await self.devices.list(size=limit)
        ok = failed = 0
        for device in devices:
            if device.status == "maintenance":
                continue
            try:
                await self.create_backup(device.id, backup_type=backup_type)
                ok += 1
            except Exception as exc:  # noqa: BLE001 - per-device failures must not abort the sweep
                failed += 1
                log.warning("backup.device_failed", device=device.name, error=str(exc))
        return {"ok": ok, "failed": failed}

    # ------------------------------------------------------------------ read
    async def get(self, backup_id: uuid.UUID) -> Backup:
        backup = await self.uow.backups.get(backup_id)
        if backup is None:
            raise NotFoundError("Backup not found")
        return backup

    async def list_for_device(self, device_id: uuid.UUID, limit: int = 50) -> list[Backup]:
        return await self.uow.backups.for_device(device_id, limit=limit)

    async def list(
        self,
        *,
        page: int = 1,
        size: int = 50,
        device_id: uuid.UUID | None = None,
        backup_type: str | None = None,
    ) -> tuple[list[Backup], int]:
        filters: dict[str, Any] = {"device_id": device_id, "type": backup_type}
        return await self.uow.backups.list(
            filters=filters, page=page, size=size, sort="created_at", order="desc"
        )

    async def storage_usage(self) -> int:
        return await self.uow.backups.storage_usage()

    async def download(self, backup_id: uuid.UUID) -> tuple[Backup, bytes]:
        """Return the decrypted snapshot and record the access in the audit trail."""
        backup = await self.get(backup_id)
        payload = await self.read_payload(backup_id)
        await self.audit.record(
            action="backup.downloaded",
            resource_type="Backup",
            resource_id=backup.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"device_id": str(backup.device_id), "size_bytes": len(payload)},
        )
        await self.session.commit()
        return backup, payload

    async def read_payload(self, backup_id: uuid.UUID) -> bytes:
        backup = await self.get(backup_id)
        stored = await self.storage.aget_bytes(backup.storage_key, bucket=self.storage.buckets["backups"])
        try:
            return gzip.decompress(decrypt_bytes(stored))
        except (InvalidTag, ValueError, OSError) as exc:
            raise UpstreamError(
                "Backup artifact is corrupted, tampered with, or encrypted with another key"
            ) from exc

    # ------------------------------------------------------------------ verify
    async def verify(self, backup_id: uuid.UUID) -> BackupVerification:
        backup = await self.get(backup_id)
        try:
            payload = await self.read_payload(backup_id)
        except UpstreamError:
            # Report the failure instead of returning 502: /verify exists to tell
            # an operator that the artifact is unusable.
            return BackupVerification(
                backup_id=backup.id,
                checksum_ok=False,
                signature_ok=False,
                stored_checksum=backup.checksum_sha256,
                computed_checksum="",
                size_bytes=0,
            )
        computed = _sha256(payload)
        return BackupVerification(
            backup_id=backup.id,
            checksum_ok=computed == backup.checksum_sha256,
            signature_ok=bool(backup.signature) and verify_signature(payload, backup.signature or ""),
            stored_checksum=backup.checksum_sha256,
            computed_checksum=computed,
            size_bytes=len(payload),
        )

    # ------------------------------------------------------------------ restore
    async def restore(
        self, backup_id: uuid.UUID, *, dry_run: bool = False, reboot: bool = False
    ) -> dict[str, Any]:
        return await self.restore_service.restore(backup_id, dry_run=dry_run, reboot=reboot)

    # ------------------------------------------------------------------ lifecycle
    async def delete(self, backup_id: uuid.UUID, *, purge_object: bool = True) -> None:
        backup = await self.get(backup_id)
        if purge_object:
            try:
                self.storage.delete(backup.storage_key, bucket=self.storage.buckets["backups"])
            except UpstreamError:
                log.warning("backup.object_delete_failed", key=backup.storage_key)
        await self.session.delete(backup)
        await self.audit.record(
            action="backup.deleted",
            resource_type="Backup",
            resource_id=backup.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before={"device_id": str(backup.device_id), "key": backup.storage_key},
        )
        await self.session.commit()

    async def apply_retention(
        self,
        *,
        retention_days: int | None = None,
        keep_per_device: int = 30,
    ) -> dict[str, int]:
        """Delete backups older than the retention window, keeping N per device."""
        cutoff = datetime.now(UTC) - timedelta(days=retention_days or settings.METRIC_RETENTION_DAYS)
        stmt = (
            select(Backup)
            .where(Backup.tenant_id == self.tenant_id)
            .order_by(Backup.device_id, Backup.created_at.desc())
        )
        rows = list((await self.session.execute(stmt)).scalars().all())

        per_device: dict[uuid.UUID, int] = {}
        deleted = kept = 0
        for backup in rows:
            index = per_device.get(backup.device_id, 0)
            per_device[backup.device_id] = index + 1
            expired = backup.created_at.replace(tzinfo=backup.created_at.tzinfo or UTC) < cutoff
            if index < keep_per_device or not expired:
                kept += 1
                continue
            try:
                self.storage.delete(backup.storage_key, bucket=self.storage.buckets["backups"])
            except UpstreamError:
                log.warning("backup.retention_object_missing", key=backup.storage_key)
            await self.session.delete(backup)
            deleted += 1

        await self.session.flush()
        if deleted:
            await self.audit.record(
                action="backup.retention_applied",
                resource_type="Backup",
                tenant_id=self.tenant_id,
                user_id=self.actor_id,
                after={"deleted": deleted, "kept": kept, "cutoff": cutoff.isoformat()},
            )
        await self.session.commit()
        return {"deleted": deleted, "kept": kept}


class RestoreService:
    """Restores a verified artifact to its originating device."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        storage: ObjectStorage | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.devices = DeviceService(session, tenant_id, actor_id)
        self.audit = AuditService(session)
        self.storage = storage or get_storage()

    async def _load(self, backup_id: uuid.UUID) -> tuple[Backup, bytes]:
        backup = await self.uow.backups.get(backup_id)
        if backup is None:
            raise NotFoundError("Backup not found")
        stored = await self.storage.aget_bytes(backup.storage_key, bucket=self.storage.buckets["backups"])
        try:
            payload = gzip.decompress(decrypt_bytes(stored))
        except (InvalidTag, ValueError, OSError) as exc:
            raise BadRequestError("Backup artifact failed authentication - restore aborted") from exc
        return backup, payload

    async def restore(
        self, backup_id: uuid.UUID, *, dry_run: bool = False, reboot: bool = False
    ) -> dict[str, Any]:
        backup, payload = await self._load(backup_id)
        checksum = _sha256(payload)
        if checksum != backup.checksum_sha256:
            raise BadRequestError("Backup checksum mismatch - restore aborted")
        if backup.signature and not verify_signature(payload, backup.signature):
            raise BadRequestError("Backup signature invalid - restore aborted")

        device = await self.devices.get(backup.device_id)
        result: dict[str, Any] = {
            "backup_id": str(backup.id),
            "device_id": str(device.id),
            "device_name": device.name,
            "dry_run": dry_run,
            "size_bytes": len(payload),
            "checksum": checksum,
        }
        if dry_run:
            result["status"] = "validated"
            return result

        base_url, key, secret = await self.devices.credentials(device)
        async with client_for(base_url, key, secret) as client:
            response = await client.upload_config(payload)
            if reboot:
                await client.reboot()

        backup.notes = (
            (backup.notes or "") + f"\nrestored at {datetime.now(UTC).isoformat()} on {device.name}"
        ).strip()
        device.provisioned_at = datetime.now(UTC)
        await self.session.flush()
        await self.audit.record(
            action="backup.restored",
            resource_type="Device",
            resource_id=device.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "backup_id": str(backup.id),
                "checksum": checksum,
                "reboot": reboot,
                "response": str(response)[:500],
            },
        )
        await self.session.commit()
        result["status"] = "restored"
        result["response"] = response
        log.info("backup.restored", device=device.name, backup=str(backup.id))
        return result


class BackupScheduler:
    """Entry point used by Celery beat for scheduled / pre-change snapshots."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def run_scheduled(self) -> dict[str, int]:
        return await BackupService(self.session, self.tenant_id).create_for_all(
            backup_type=BackupType.SCHEDULED
        )

    async def run_pre_change(self, device_id: uuid.UUID) -> Backup:
        return await BackupService(self.session, self.tenant_id).create_backup(
            device_id, backup_type=BackupType.PRE_CHANGE, notes="Automatic pre-change snapshot"
        )
