"""Backup pipeline tests: encryption, checksum, signature, tamper detection, restore.

The object store is replaced by an in-memory double and the two OPNsense calls by
a fake client, so the test exercises the real service code (gzip, AES-256-GCM,
SHA-256, HMAC-SHA256, audit records, DB rows) without network access.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import BadRequestError
from app.core.security import decrypt_bytes, encrypt_secret
from app.integrations.storage import StoredObject
from app.models.enums import BackupType
from app.models.topology import Device
from app.services import backup as backup_module
from app.services.backup import BackupService

XML = b"""<?xml version="1.0"?>
<opnsense><system><hostname>fw-test</hostname></system></opnsense>
"""


class MemoryStorage:
    buckets = {"backups": "ofme-backups", "artifacts": "ofme-artifacts"}

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def aput_bytes(
        self,
        key: str,
        data: bytes,
        *,
        bucket: str | None = None,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        self.objects[key] = data
        return StoredObject(
            key=key,
            bucket=bucket or self.buckets["backups"],
            size=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            etag=None,
        )

    async def aget_bytes(self, key: str, *, bucket: str | None = None) -> bytes:
        return self.objects[key]

    def delete(self, key: str, *, bucket: str | None = None) -> None:
        self.objects.pop(key, None)


class FakeClient:
    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def download_config(self) -> bytes:
        return XML

    async def upload_config(self, payload: bytes) -> dict[str, Any]:
        assert payload == XML
        return {"status": "ok"}

    async def reboot(self) -> dict[str, Any]:
        return {"status": "rebooting"}


@pytest.fixture
def fake_opnsense(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backup_module, "client_for", lambda *a, **k: FakeClient())


async def _device(session_factory: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID) -> uuid.UUID:
    async with session_factory() as session:
        device = Device(
            tenant_id=tenant_id,
            name="fw-backup-test",
            ip_address="10.0.0.10",
            api_key_encrypted=encrypt_secret("key"),
            api_secret_encrypted=encrypt_secret("secret"),
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)
        return device.id


@pytest.mark.asyncio(loop_scope="session")
async def test_backup_is_encrypted_signed_and_restorable(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    clean_database: None,
    fake_opnsense: None,
) -> None:
    tenant = await tenant_factory()
    device_id = await _device(session_factory, tenant.id)
    storage = MemoryStorage()

    async with session_factory() as session:
        service = BackupService(session, tenant.id, storage=storage)  # type: ignore[arg-type]
        backup = await service.create_backup(device_id, backup_type=BackupType.MANUAL, notes="test")
        assert backup.is_encrypted is True
        assert backup.size_bytes == len(XML)
        assert backup.storage_key.endswith(".xml.gz.enc")

        stored = storage.objects[backup.storage_key]
        assert stored != XML
        assert b"<opnsense>" not in stored
        # Ciphertext must not even be a valid gzip stream.
        with pytest.raises(InvalidTag):
            decrypt_bytes(stored[:-1] + bytes([stored[-1] ^ 0xFF]))

        verification = await service.verify(backup.id)
        assert verification.valid is True
        assert verification.checksum_ok is True
        assert verification.signature_ok is True
        assert verification.size_bytes == len(XML)

        assert await service.read_payload(backup.id) == XML

        dry = await service.restore(backup.id, dry_run=True)
        assert dry["status"] == "validated"

        restored = await service.restore(backup.id, dry_run=False)
        assert restored["status"] == "restored"
        assert restored["response"] == {"status": "ok"}

        # Corrupt one byte of the stored ciphertext: verify reports failure and
        # restore refuses to push anything to the device.
        storage.objects[backup.storage_key] = stored[:-1] + bytes([stored[-1] ^ 0xFF])
        broken = await service.verify(backup.id)
        assert broken.valid is False
        assert broken.checksum_ok is False
        with pytest.raises(BadRequestError):
            await service.restore(backup.id, dry_run=True)

        storage.objects[backup.storage_key] = stored
        assert (await service.verify(backup.id)).valid is True

        retention = await service.apply_retention(retention_days=3650, keep_per_device=30)
        assert retention == {"deleted": 0, "kept": 1}


@pytest.mark.asyncio(loop_scope="session")
async def test_backup_requires_device_credentials(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
    clean_database: None,
    fake_opnsense: None,
) -> None:
    tenant = await tenant_factory()
    async with session_factory() as session:
        device = Device(tenant_id=tenant.id, name="fw-no-creds", ip_address="10.0.0.11")
        session.add(device)
        await session.commit()
        await session.refresh(device)
        device_id = device.id

    async with session_factory() as session:
        service = BackupService(session, tenant.id, storage=MemoryStorage())  # type: ignore[arg-type]
        with pytest.raises(BadRequestError):
            await service.create_backup(device_id)
