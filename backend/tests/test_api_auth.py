"""Authentication API integration tests (requires PostgreSQL)."""

from __future__ import annotations

import pyotp
import pytest
from httpx import AsyncClient

from app.core.security import encrypt_secret
from app.models.enums import RoleName
from tests.conftest import AccountFactory, TenantFactory


@pytest.mark.asyncio(loop_scope="session")
async def test_login_and_me(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password, "tenant": tenant.slug},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["mfa_required"] is False
    assert body["user"]["username"] == account.user.username
    assert "Admin" in body["user"]["roles"]
    assert "device:read" in body["user"]["permissions"]

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["tenant_id"] == str(tenant.id)


@pytest.mark.asyncio(loop_scope="session")
async def test_login_accepts_email_in_username_field(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.email, "password": account.password, "tenant": tenant.slug},
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["username"] == account.user.username


@pytest.mark.asyncio(loop_scope="session")
async def test_login_rejects_bad_credentials(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.asyncio(loop_scope="session")
async def test_login_rejects_unknown_user(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={"username": "nobody", "password": "whatever"})
    assert response.status_code == 401


@pytest.mark.asyncio(loop_scope="session")
async def test_refresh_rotates_and_rejects_reuse(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant)
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    original_refresh = login.json()["refresh_token"]

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["refresh_token"] != original_refresh
    assert rotated.json()["access_token"]

    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "unauthenticated"


@pytest.mark.asyncio(loop_scope="session")
async def test_sessions_and_revoke_all(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant)
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    sessions = await client.get("/api/v1/auth/sessions", headers=headers)
    assert sessions.status_code == 200
    assert len(sessions.json()) == 1

    revoked = await client.delete("/api/v1/auth/sessions", headers=headers)
    assert revoked.status_code == 200
    assert "Revoked" in revoked.json()["message"]

    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401


@pytest.mark.asyncio(loop_scope="session")
async def test_login_requires_mfa_and_accepts_totp(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    session_factory,
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant)
    secret = pyotp.random_base32()

    async with session_factory() as session:
        user = await session.get(type(account.user), account.user.id)
        assert user is not None
        user.mfa_enabled = True
        user.mfa_secret_encrypted = encrypt_secret(secret)
        await session.commit()

    challenge = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    assert challenge.status_code == 200
    assert challenge.json()["mfa_required"] is True
    assert challenge.json()["challenge_token"]

    verified = await client.post(
        "/api/v1/auth/mfa/verify",
        json={
            "challenge_token": challenge.json()["challenge_token"],
            "code": pyotp.TOTP(secret).now(),
        },
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["access_token"]
    assert verified.json()["mfa_required"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_mfa_rejects_invalid_code(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    session_factory,
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant)

    async with session_factory() as session:
        user = await session.get(type(account.user), account.user.id)
        assert user is not None
        user.mfa_enabled = True
        user.mfa_secret_encrypted = encrypt_secret(pyotp.random_base32())
        await session.commit()

    challenge = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    verified = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"challenge_token": challenge.json()["challenge_token"], "code": "000000"},
    )
    assert verified.status_code == 401


@pytest.mark.asyncio(loop_scope="session")
async def test_password_change_revokes_sessions_and_updates_hash(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant)
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    new_password = "Brand-New-Passw0rd!"
    changed = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": account.password, "new_password": new_password},
    )
    assert changed.status_code == 200, changed.text

    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401

    relogin = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": new_password},
    )
    assert relogin.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_password_change_rejects_weak_password(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant)
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    changed = await client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": account.password, "new_password": "weakpassword"},
    )
    assert changed.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_unauthenticated_request_is_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.asyncio(loop_scope="session")
async def test_inactive_user_cannot_login(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory, session_factory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant)

    from app.models.enums import UserStatus

    async with session_factory() as session:
        user = await session.get(type(account.user), account.user.id)
        assert user is not None
        user.status = UserStatus.INACTIVE
        await session.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    assert response.status_code == 401
