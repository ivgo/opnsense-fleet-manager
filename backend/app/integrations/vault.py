"""HashiCorp Vault KV v2 secret backend with transparent fallback to AES-GCM envelopes."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret

log = get_logger("ofme.vault")


class SecretBackend:
    """Interface used by services for credential material."""

    async def put(self, path: str, values: dict[str, str]) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def get(self, path: str) -> dict[str, str] | None:  # pragma: no cover - interface
        raise NotImplementedError

    async def delete(self, path: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def seal(self, plaintext: str) -> str:
        return encrypt_secret(plaintext)

    def open(self, sealed: str) -> str:
        return decrypt_secret(sealed)


class VaultSecretBackend(SecretBackend):
    def __init__(self, addr: str, token: str, mount: str = "secret") -> None:
        self.addr = addr.rstrip("/")
        self.token = token
        self.mount = mount
        self._client = httpx.AsyncClient(
            base_url=self.addr,
            timeout=10.0,
            headers={"X-Vault-Token": token, "X-Vault-Request": "true"},
        )

    async def put(self, path: str, values: dict[str, str]) -> None:
        response = await self._client.post(f"/v1/{self.mount}/data/{path}", json={"data": values})
        if response.status_code >= 400:
            log.error("vault.write_failed", path=path, status=response.status_code)
            raise RuntimeError(f"Vault write failed: {response.status_code}")

    async def get(self, path: str) -> dict[str, str] | None:
        response = await self._client.get(f"/v1/{self.mount}/data/{path}")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise RuntimeError(f"Vault read failed: {response.status_code}")
        data: dict[str, Any] = response.json().get("data", {})
        return data.get("data", {})

    async def delete(self, path: str) -> None:
        await self._client.delete(f"/v1/{self.mount}/metadata/{path}")

    async def close(self) -> None:
        await self._client.aclose()


class LocalSecretBackend(SecretBackend):
    """AES-256-GCM envelope encryption keyed from SECRET_KEY (default for self-hosting)."""

    async def put(self, path: str, values: dict[str, str]) -> None:
        log.debug("vault.local_put", path=path)

    async def get(self, path: str) -> dict[str, str] | None:
        return None

    async def delete(self, path: str) -> None:
        return None


def get_secret_backend() -> SecretBackend:
    if settings.VAULT_ENABLED and settings.VAULT_ADDR and settings.VAULT_TOKEN:
        return VaultSecretBackend(settings.VAULT_ADDR, settings.VAULT_TOKEN, settings.VAULT_MOUNT_POINT)
    return LocalSecretBackend()


secret_backend = get_secret_backend()


async def rotate_secret(sealed_value: str, *, path: str | None = None) -> str:
    """Re-encrypt a value under the current key material."""
    plaintext = decrypt_secret(sealed_value)
    if path and isinstance(secret_backend, VaultSecretBackend):
        await secret_backend.put(path, {"value": plaintext})
        return f"vault:{path}"
    return await asyncio.to_thread(encrypt_secret, plaintext)
