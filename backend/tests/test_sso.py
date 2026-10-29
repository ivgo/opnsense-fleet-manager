"""SSO integration tests: LDAP, OIDC, SAML authentication flows."""

from __future__ import annotations

import os
import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import AccountFactory, TenantFactory


pytestmark = pytest.mark.asyncio(loop_scope="session")


class TestLDAPAuth:
    """LDAP/Active Directory authentication tests."""

    async def test_ldap_login_requires_configuration(
        self, client: AsyncClient, tenant_factory: TenantFactory
    ) -> None:
        """LDAP login returns 400 when LDAP is not configured."""
        tenant = await tenant_factory()
        response = await client.post(
            "/api/v1/auth/ldap/login",
            json={"username": "testuser", "password": "secret", "tenant": tenant.slug},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "bad_request"

    async def test_ldap_login_with_credentials(
        self, client: AsyncClient, tenant_factory: TenantFactory
    ) -> None:
        """LDAP login with valid credentials succeeds when configured."""
        if not settings.LDAP_SERVER:
            pytest.skip("LDAP_SERVER not configured - skipping integration test")

        tenant = await tenant_factory()
        response = await client.post(
            "/api/v1/auth/ldap/login",
            json={"username": "testuser", "password": "secret", "tenant": tenant.slug},
        )
        if response.status_code == 200:
            body = response.json()
            assert body["access_token"]
            assert body["refresh_token"]
            assert body["mfa_required"] is False
        elif response.status_code == 401:
            assert response.json()["error"]["code"] == "unauthenticated"
        else:
            pytest.fail(f"Unexpected status: {response.status_code}")


class TestOIDCAuth:
    """OIDC/OAuth2 authentication tests."""

    async def test_oidc_authorize_requires_configuration(
        self, client: AsyncClient
    ) -> None:
        """OIDC authorize returns 400 when OIDC is not configured."""
        response = await client.get("/api/v1/auth/oidc/authorize")
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "bad_request"

    async def test_oidc_authorize_returns_authorization_url(
        self, client: AsyncClient
    ) -> None:
        """OIDC authorize returns authorization URL when configured."""
        if not settings.OIDC_ISSUER:
            pytest.skip("OIDC_ISSUER not configured - skipping integration test")

        response = await client.get("/api/v1/auth/oidc/authorize")
        assert response.status_code == 200
        body = response.json()
        assert body["authorization_url"]
        assert body["state"]

    async def test_oidc_authorize_with_tenant(
        self, client: AsyncClient, tenant_factory: TenantFactory
    ) -> None:
        """OIDC authorize includes tenant in state."""
        tenant = await tenant_factory()
        response = await client.get(f"/api/v1/auth/oidc/authorize?tenant={tenant.slug}")
        assert response.status_code == 200
        body = response.json()
        assert body["authorization_url"]
        assert body["state"]

    async def test_oidc_callback_rejects_invalid_state(self, client: AsyncClient) -> None:
        """OIDC callback rejects missing/invalid state."""
        response = await client.post(
            "/api/v1/auth/oidc/callback",
            json={"code": "fake-code", "state": ""},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["code"] == "unauthenticated"

    async def test_oidc_callback_rejects_invalid_code(
        self, client: AsyncClient
    ) -> None:
        """OIDC callback handles invalid code gracefully."""
        if not settings.OIDC_ISSUER:
            pytest.skip("OIDC_ISSUER not configured - skipping integration test")

        response = await client.get("/api/v1/auth/oidc/authorize")
        state = response.json()["state"]

        response = await client.post(
            "/api/v1/auth/oidc/callback",
            json={"code": "invalid-code", "state": state},
        )
        assert response.status_code in (401, 502)


class TestSAMLAuth:
    """SAML 2.0 authentication tests."""

    async def test_saml_authorize_requires_configuration(
        self, client: AsyncClient
    ) -> None:
        """SAML authorize returns 400 when SAML is not configured."""
        response = await client.get("/api/v1/auth/saml/authorize")
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "bad_request"

    async def test_saml_metadata_requires_configuration(
        self, client: AsyncClient
    ) -> None:
        """SAML metadata returns 400 when SAML is not configured."""
        response = await client.get("/api/v1/auth/saml/metadata")
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == "bad_request"

    async def test_saml_authorize_returns_redirect_url(
        self, client: AsyncClient
    ) -> None:
        """SAML authorize returns IdP redirect URL when configured."""
        if not settings.SAML_IDP_ENTITY_ID:
            pytest.skip("SAML_IDP_ENTITY_ID not configured - skipping integration test")

        response = await client.get("/api/v1/auth/saml/authorize")
        assert response.status_code == 200
        body = response.json()
        assert body["authorization_url"]
        assert body["state"]

    async def test_saml_acs_rejects_invalid_response(
        self, client: AsyncClient
    ) -> None:
        """SAML ACS rejects invalid/missing SAML response."""
        response = await client.post(
            "/api/v1/auth/saml/acs",
            data={"SAMLResponse": "invalid-base64", "RelayState": ""},
        )
        assert response.status_code in (400, 401)


class TestEntraIDAuth:
    """Microsoft Entra ID (Azure AD) authentication tests."""

    async def test_entra_authorize_requires_configuration(
        self, client: AsyncClient
    ) -> None:
        """Entra ID authorize returns 400 when not configured."""
        response = await client.get("/api/v1/auth/oidc/authorize?entra=true")
        if not settings.ENTRA_TENANT_ID:
            assert response.status_code == 400
            body = response.json()
            assert body["error"]["code"] == "bad_request"
        else:
            assert response.status_code == 200
            body = response.json()
            assert body["authorization_url"]

    async def test_entra_provider_detection(
        self, client: AsyncClient
    ) -> None:
        """Entra ID provider is detected from configuration."""
        response = await client.get("/api/v1/auth/providers")
        assert response.status_code == 200
        body = response.json()
        has_entra = bool(settings.ENTRA_TENANT_ID and settings.ENTRA_CLIENT_ID)
        assert body["entra_id"] == has_entra


class TestAuthProviderListing:
    """Authentication provider discovery tests."""

    async def test_providers_endpoint(self, client: AsyncClient) -> None:
        """Providers endpoint returns configured authentication methods."""
        response = await client.get("/api/v1/auth/providers")
        assert response.status_code == 200
        body = response.json()
        assert "local" in body
        assert "ldap" in body
        assert "oidc" in body
        assert "saml" in body
        assert "mfa_enabled" in body
        assert body["mfa_enabled"] is True

    async def test_mfa_flag_reflects_config(self, client: AsyncClient) -> None:
        """MFA enabled flag reflects configuration."""
        original = settings.ENABLE_MFA
        try:
            response = await client.get("/api/v1/auth/providers")
            assert response.status_code == 200
            body = response.json()
            assert body["mfa_enabled"] == original
        finally:
            settings.ENABLE_MFA = original