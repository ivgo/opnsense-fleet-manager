"""HashiCorp Vault KV v2 secret backend with transparent fallback to AES-GCM envelopes.

Uses hvac (HashiCorp Vault Python client) for production deployments.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret

log = get_logger("ofme.vault")

# Lazy-loaded hvac client
_vault_client: Any | None = None


def _get_settings():
    """Get settings lazily to avoid circular imports."""
    from app.core.config import settings
    return settings


def _get_vault_client() -> Any | None:
    """Get hvac Vault client (lazy-loaded)."""
    global _vault_client
    if _vault_client is not None:
        return _vault_client

    s = _get_settings()
    if not s.VAULT_ENABLED or not s.VAULT_ADDR:
        return None

    try:
        import hvac
        s = _get_settings()
        _vault_client = hvac.Client(
            url=s.VAULT_ADDR,
            token=s.VAULT_TOKEN if s.VAULT_TOKEN else None,
        )
        log.info("vault.client_initialized", addr=s.VAULT_ADDR)
        return _vault_client
    except ImportError:
        log.warning("vault.hvac_not_installed", message="hvac package not installed - using local backend")
        return None


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
    """HashiCorp Vault KV v2 backend using hvac client."""

    def __init__(self, addr: str, token: str, mount: str = "secret") -> None:
        self.addr = addr.rstrip("/")
        self.token = token
        self.mount = mount
        self._client = _get_vault_client()
        self._http_client = httpx.AsyncClient(
            base_url=self.addr,
            timeout=10.0,
            headers={"X-Vault-Token": token, "X-Vault-Request": "true"},
        ) if not self._client else None

    async def put(self, path: str, values: dict[str, str]) -> None:
        """Write secret to Vault KV v2."""
        if self._client:
            try:
                self._client.secrets.kv.v2.create_or_update_secret(
                    path=path,
                    secret=values,
                    mount_point=self.mount,
                )
                log.info("vault.write_success", path=path)
                return
            except Exception as e:
                log.error("vault.write_failed", path=path, error=str(e))
                raise RuntimeError(f"Vault write failed: {e}")
        else:
            # Fallback to HTTP
            response = await self._http_client.post(f"/v1/{self.mount}/data/{path}", json={"data": values})
            if response.status_code >= 400:
                log.error("vault.write_failed", path=path, status=response.status_code)
                raise RuntimeError(f"Vault write failed: {response.status_code}")

    async def get(self, path: str) -> dict[str, str] | None:
        """Read secret from Vault KV v2."""
        if self._client:
            try:
                result = self._client.secrets.kv.v2.read_secret_version(
                    path=path,
                    mount_point=self.mount,
                )
                if result and "data" in result and "data" in result["data"]:
                    log.debug("vault.read_success", path=path)
                    return result["data"]["data"]
                return None
            except Exception as e:
                # Handle 404/NotFound and InvalidPath (secret deleted)
                if "No secret found" in str(e) or "404" in str(e) or isinstance(e, Exception) and type(e).__module__ == 'hvac.exceptions' and type(e).__name__ == 'InvalidPath':
                    return None
                log.error("vault.read_failed", path=path, error=str(e))
                raise RuntimeError(f"Vault read failed: {e}")
        else:
            # Fallback to HTTP
            response = await self._http_client.get(f"/v1/{self.mount}/data/{path}")
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                raise RuntimeError(f"Vault read failed: {response.status_code}")
            data: dict[str, Any] = response.json().get("data", {})
            return data.get("data", {})

    async def delete(self, path: str) -> None:
        """Delete secret from Vault."""
        if self._client:
            try:
                self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                    path=path,
                    mount_point=self.mount,
                )
                log.info("vault.delete_success", path=path)
                return
            except Exception as e:
                log.error("vault.delete_failed", path=path, error=str(e))
                raise RuntimeError(f"Vault delete failed: {e}")
        else:
            await self._http_client.delete(f"/v1/{self.mount}/metadata/{path}")

    async def close(self) -> None:
        """Close HTTP client if present."""
        if self._http_client:
            await self._http_client.aclose()

    def is_available(self) -> bool:
        """Check if Vault is connected and accessible."""
        if self._client:
            try:
                return self._client.is_authenticated()
            except Exception:
                return False
        return self._http_client is not None


class LocalSecretBackend(SecretBackend):
    """AES-256-GCM envelope encryption keyed from SECRET_KEY (default for self-hosting)."""

    async def put(self, path: str, values: dict[str, str]) -> None:
        log.debug("vault.local_put", path=path)

    async def get(self, path: str) -> dict[str, str] | None:
        return None

    async def delete(self, path: str) -> None:
        return None


_vault_backend: SecretBackend | None = None


def get_secret_backend() -> SecretBackend:
    """Get secret backend instance (Vault if configured, otherwise local)."""
    global _vault_backend
    if _vault_backend is None:
        s = _get_settings()
        if s.VAULT_ENABLED and s.VAULT_ADDR and s.VAULT_TOKEN:
            _vault_backend = VaultSecretBackend(s.VAULT_ADDR, s.VAULT_TOKEN, s.VAULT_MOUNT_POINT)
            log.info("vault.backend_initialized", backend="Vault")
        else:
            _vault_backend = LocalSecretBackend()
            log.info("vault.backend_initialized", backend="Local")
    return _vault_backend


def secret_backend() -> SecretBackend:
    """Get secret backend instance (lazy function to avoid circular imports)."""
    return get_secret_backend()


async def rotate_secret(sealed_value: str, *, path: str | None = None) -> str:
    """Re-encrypt a value under the current key material."""
    plaintext = decrypt_secret(sealed_value)
    backend = get_secret_backend()
    if path and isinstance(backend, VaultSecretBackend):
        await backend.put(path, {"value": plaintext})
        return f"vault:{path}"
    return await asyncio.to_thread(encrypt_secret, plaintext)


async def get_vault_secret(path: str, key: str | None = None) -> str | None:
    """Get a secret value from Vault.

    Args:
        path: Secret path in Vault (e.g., 'ofme/secret-key')
        key: Optional key name within the secret. If None, returns the first value.

    Returns:
        Secret value or None if not found
    """
    backend = get_secret_backend()
    if isinstance(backend, VaultSecretBackend):
        values = await backend.get(path)
        if values:
            if key:
                return values.get(key)
            # Return first value if no key specified
            return next(iter(values.values()), None)
    return None


async def put_vault_secret(path: str, values: dict[str, str]) -> None:
    """Store secret(s) in Vault.

    Args:
        path: Secret path in Vault (e.g., 'ofme/secret-key')
        values: Key-value pairs to store
    """
    backend = get_secret_backend()
    await backend.put(path, values)


async def check_vault_health() -> dict[str, Any]:
    """Check Vault connectivity and health.

    Returns:
        Health status dict with 'healthy', 'vault_connected', 'backend' keys
    """
    backend = get_secret_backend()
    result = {
        "healthy": False,
        "vault_connected": False,
        "backend": "local",
    }

    if isinstance(backend, VaultSecretBackend):
        result["backend"] = "vault"
        try:
            result["vault_connected"] = backend.is_available()
            result["healthy"] = result["vault_connected"]
        except Exception as e:
            result["error"] = str(e)
            result["healthy"] = False
    else:
        result["healthy"] = True  # Local backend is always "healthy"

    return result
