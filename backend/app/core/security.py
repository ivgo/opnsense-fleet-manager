"""Password hashing, JWT issuance, TOTP, API-key material and envelope encryption."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.core.exceptions import AuthenticationError

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

TokenType = Literal["access", "refresh", "enrollment", "mfa_challenge", "oidc_state", "ws"]


# --------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def enforce_password_policy(password: str) -> None:
    from app.core.exceptions import ValidationError

    problems: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"minimum length is {settings.PASSWORD_MIN_LENGTH}")
    if not any(c.isupper() for c in password):
        problems.append("must contain an uppercase letter")
    if not any(c.islower() for c in password):
        problems.append("must contain a lowercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("must contain a digit")
    if not any(not c.isalnum() for c in password):
        problems.append("must contain a symbol")
    if problems:
        raise ValidationError("Password does not satisfy policy", details=problems)


# --------------------------------------------------------------------------- JWT
def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(
    *,
    user_id: uuid.UUID | str,
    tenant_id: uuid.UUID | str | None,
    roles: list[str],
    permissions: list[str],
    is_superadmin: bool = False,
    expires_minutes: int | None = None,
) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id) if tenant_id else None,
        "roles": roles,
        "perms": permissions,
        "sa": is_superadmin,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
        "iss": settings.APP_NAME,
    }
    return _encode(payload)


def create_refresh_token(
    *, user_id: uuid.UUID | str, tenant_id: uuid.UUID | str | None, jti: str | None = None
) -> tuple[str, str, datetime]:
    now = datetime.now(UTC)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    token_id = jti or uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id) if tenant_id else None,
        "type": "refresh",
        "jti": token_id,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "iss": settings.APP_NAME,
    }
    return _encode(payload), token_id, expire


def create_scoped_token(
    *,
    subject: str,
    token_type: TokenType,
    tenant_id: uuid.UUID | str | None,
    ttl_seconds: int,
    extra: dict | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "tid": str(tenant_id) if tenant_id else None,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
        "iss": settings.APP_NAME,
        **(extra or {}),
    }
    return _encode(payload)


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.APP_NAME,
            options={"require": ["exp", "iat", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid token") from exc

    if expected_type and payload.get("type") != expected_type:
        raise AuthenticationError("Invalid token type")
    return payload


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- TOTP
def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=settings.MFA_ISSUER)


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=valid_window)


def generate_backup_codes(count: int = 10) -> list[str]:
    return [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(count)]


def hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- API keys
def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext, prefix, sha256 hash). Plaintext is shown exactly once."""
    raw = secrets.token_urlsafe(32)
    plaintext = f"{settings.API_KEY_PREFIX}_{raw}"
    prefix = plaintext[:12]
    return plaintext, prefix, hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# --------------------------------------------------------------------------- envelope encryption
def _derive_key() -> bytes:
    return hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()


def encrypt_secret(plaintext: str) -> str:
    """AES-256-GCM envelope encryption for credentials stored in PostgreSQL."""
    aes = AESGCM(_derive_key())
    nonce = secrets.token_bytes(12)
    ciphertext = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(blob: str) -> str:
    raw = base64.b64decode(blob.encode("ascii"))
    nonce, ciphertext = raw[:12], raw[12:]
    return AESGCM(_derive_key()).decrypt(nonce, ciphertext, None).decode("utf-8")


#: Associated data keeps backup ciphertexts from being confused with any other
#: AES-GCM payload produced with the same platform key.
BACKUP_AAD = b"ofme.backup.v1"


def encrypt_bytes(payload: bytes, *, aad: bytes = BACKUP_AAD) -> bytes:
    """AES-256-GCM encryption for binary artifacts (configuration backups).

    The nonce is prepended to the ciphertext; the tag is appended by AESGCM.
    """
    aes = AESGCM(_derive_key())
    nonce = secrets.token_bytes(12)
    return nonce + aes.encrypt(nonce, payload, aad)


def decrypt_bytes(blob: bytes, *, aad: bytes = BACKUP_AAD) -> bytes:
    """Inverse of :func:`encrypt_bytes`; raises ``InvalidTag`` when tampered."""
    if len(blob) < 13:
        raise ValueError("ciphertext is too short to contain a nonce and tag")
    return AESGCM(_derive_key()).decrypt(blob[:12], blob[12:], aad)


def sign_payload(payload: bytes) -> str:
    return hmac.new(_derive_key(), payload, hashlib.sha256).hexdigest()


def verify_signature(payload: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_payload(payload), signature)
