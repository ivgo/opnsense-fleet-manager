"""Password, JWT, TOTP, API-key and envelope-encryption unit tests."""

from __future__ import annotations

import time
import uuid

import pyotp
import pytest

from app.core.exceptions import AuthenticationError, ValidationError
from app.core.security import (
    constant_time_equals,
    create_access_token,
    create_refresh_token,
    create_scoped_token,
    decode_token,
    decrypt_bytes,
    decrypt_secret,
    encrypt_bytes,
    encrypt_secret,
    enforce_password_policy,
    generate_api_key,
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_code,
    hash_password,
    password_needs_rehash,
    sign_payload,
    token_fingerprint,
    totp_provisioning_uri,
    verify_password,
    verify_signature,
    verify_totp,
)


def test_password_hash_roundtrip() -> None:
    digest = hash_password("S3cure-Passw0rd!")
    assert digest != "S3cure-Passw0rd!"
    assert digest.startswith("$argon2id$")
    assert verify_password("S3cure-Passw0rd!", digest) is True
    assert verify_password("wrong", digest) is False


def test_password_hash_rejects_missing_and_garbage() -> None:
    assert verify_password("anything", None) is False
    assert verify_password("anything", "not-a-hash") is False
    assert password_needs_rehash("not-a-hash") is True


def test_password_hash_uses_fresh_salt() -> None:
    assert hash_password("Same-Passw0rd!") != hash_password("Same-Passw0rd!")


@pytest.mark.parametrize(
    "password",
    ["short", "alllowercase1!", "ALLUPPERCASE1!", "NoDigitsHere!", "NoSymbols1234"],
)
def test_password_policy_rejects_weak_passwords(password: str) -> None:
    with pytest.raises(ValidationError):
        enforce_password_policy(password)


def test_password_policy_accepts_strong_password() -> None:
    enforce_password_policy("Correct-Horse-9-Battery!")


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        roles=["Admin"],
        permissions=["device:read"],
    )
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == str(user_id)
    assert payload["tid"] == str(tenant_id)
    assert payload["roles"] == ["Admin"]
    assert payload["perms"] == ["device:read"]
    assert payload["sa"] is False
    assert payload["iss"] == "OPNsense Fleet Manager Enterprise"


def test_access_token_type_enforced() -> None:
    token = create_access_token(user_id=uuid.uuid4(), tenant_id=None, roles=[], permissions=[])
    with pytest.raises(AuthenticationError):
        decode_token(token, expected_type="refresh")


def test_expired_token_rejected() -> None:
    token = create_access_token(
        user_id=uuid.uuid4(),
        tenant_id=None,
        roles=[],
        permissions=[],
        expires_minutes=-1,
    )
    time.sleep(0.01)
    with pytest.raises(AuthenticationError):
        decode_token(token, expected_type="access")


def test_tampered_token_rejected() -> None:
    token = create_access_token(user_id=uuid.uuid4(), tenant_id=None, roles=[], permissions=[])
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload[:-2]}xx.{signature}"
    with pytest.raises(AuthenticationError):
        decode_token(tampered)


def test_refresh_token_contains_jti() -> None:
    user_id = uuid.uuid4()
    token, jti, expires_at = create_refresh_token(user_id=user_id, tenant_id=None)
    payload = decode_token(token, expected_type="refresh")
    assert payload["jti"] == jti
    assert payload["sub"] == str(user_id)
    assert expires_at.timestamp() > time.time()


def test_scoped_token_extra_claims() -> None:
    token = create_scoped_token(
        subject="device:42",
        token_type="enrollment",
        tenant_id=None,
        ttl_seconds=60,
        extra={"scope": "enroll"},
    )
    payload = decode_token(token, expected_type="enrollment")
    assert payload["sub"] == "device:42"
    assert payload["scope"] == "enroll"


def test_totp_enrolment_and_verification() -> None:
    secret = generate_totp_secret()
    uri = totp_provisioning_uri(secret, "admin@example.test")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=OFME" in uri
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code) is True
    assert verify_totp(secret, "000000") is False
    assert verify_totp("", code) is False


def test_backup_codes_are_unique_and_hashed() -> None:
    codes = generate_backup_codes(10)
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(len(hash_backup_code(code)) == 64 for code in codes)


def test_api_key_shape() -> None:
    plaintext, prefix, digest = generate_api_key()
    assert plaintext.startswith("ofme_")
    assert len(prefix) == 12
    assert prefix == plaintext[:12]
    assert digest == token_fingerprint(plaintext)


def test_envelope_encryption_roundtrip() -> None:
    secret = "postgres://user:pass@db/ofme"
    blob = encrypt_secret(secret)
    assert blob != secret
    assert decrypt_secret(blob) == secret


def test_envelope_encryption_detects_tampering() -> None:
    blob = encrypt_secret("value")
    tampered = blob[:-4] + ("AAAA" if blob[-4:] != "AAAA" else "BBBB")
    with pytest.raises(Exception):  # noqa: B017 - AES-GCM raises InvalidTag
        decrypt_secret(tampered)


def test_binary_encryption_roundtrip_and_tamper_detection() -> None:
    payload = b"<opnsense>binary\x00payload</opnsense>" * 32
    blob = encrypt_bytes(payload)
    assert blob != payload
    assert decrypt_bytes(blob) == payload

    tampered = blob[:-1] + bytes([blob[-1] ^ 0x01])
    with pytest.raises(Exception):  # noqa: B017 - AES-GCM raises InvalidTag
        decrypt_bytes(tampered)

    with pytest.raises(ValueError):
        decrypt_bytes(b"short")


def test_hmac_signature_roundtrip() -> None:
    payload = b'{"backup":"checksum"}'
    signature = sign_payload(payload)
    assert verify_signature(payload, signature) is True
    assert verify_signature(payload + b" ", signature) is False
    assert constant_time_equals(signature, signature) is True
    assert constant_time_equals(signature, signature[:-1] + "0") is False
