"""OIDC / Microsoft Entra ID authorization-code flow + JWKS ID-token validation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import settings
from app.core.exceptions import AuthenticationError, UpstreamError
from app.core.logging import get_logger

log = get_logger("ofme.oidc")


@dataclass(slots=True)
class OidcIdentity:
    subject: str
    email: str | None
    name: str | None
    username: str | None
    groups: list[str]
    claims: dict[str, Any]


class OidcProvider:
    def __init__(
        self,
        *,
        issuer: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        scopes: str | None = None,
    ) -> None:
        self.issuer = (issuer or settings.OIDC_ISSUER).rstrip("/")
        self.client_id = client_id or settings.OIDC_CLIENT_ID
        self.client_secret = client_secret or settings.OIDC_CLIENT_SECRET
        self.redirect_uri = redirect_uri or settings.OIDC_REDIRECT_URI
        self.scopes = scopes or settings.OIDC_SCOPES
        self._discovery: dict[str, Any] | None = None
        self._discovery_at = 0.0
        self._jwks: PyJWKClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.issuer and self.client_id)

    @classmethod
    def entra_id(
        cls, tenant_id: str | None = None, client_id: str | None = None, client_secret: str | None = None
    ) -> OidcProvider:
        tid = tenant_id or settings.ENTRA_TENANT_ID
        return cls(
            issuer=f"https://login.microsoftonline.com/{tid}/v2.0",
            client_id=client_id or settings.ENTRA_CLIENT_ID,
            client_secret=client_secret or settings.ENTRA_CLIENT_SECRET,
        )

    async def discovery(self) -> dict[str, Any]:
        if self._discovery and time.time() - self._discovery_at < 3600:
            return self._discovery
        if not self.enabled:
            raise AuthenticationError("OIDC is not configured")
        url = f"{self.issuer}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)
        if response.status_code != 200:
            raise UpstreamError(f"OIDC discovery failed: {response.status_code}")
        self._discovery = response.json()
        self._discovery_at = time.time()
        self._jwks = PyJWKClient(self._discovery["jwks_uri"])
        return self._discovery

    async def authorization_url(self, state: str, nonce: str) -> str:
        meta = await self.discovery()
        from urllib.parse import urlencode

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": self.scopes,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "nonce": nonce,
            "prompt": "select_account",
        }
        return f"{meta['authorization_endpoint']}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OidcIdentity:
        meta = await self.discovery()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(meta["token_endpoint"], data=data)
            if response.status_code != 200:
                raise AuthenticationError("OIDC code exchange failed")
            tokens = response.json()
            id_token = tokens.get("id_token")
            if not id_token:
                raise AuthenticationError("OIDC provider did not return an id_token")

            claims = self._decode_id_token(id_token)

            userinfo_endpoint = meta.get("userinfo_endpoint")
            if userinfo_endpoint and tokens.get("access_token"):
                ui = await client.get(
                    userinfo_endpoint, headers={"Authorization": f"Bearer {tokens['access_token']}"}
                )
                if ui.status_code == 200:
                    claims = {**claims, **ui.json()}

        groups = claims.get("groups") or claims.get("roles") or []
        return OidcIdentity(
            subject=str(claims.get("sub")),
            email=claims.get("email") or claims.get("preferred_username"),
            name=claims.get("name"),
            username=claims.get("preferred_username") or claims.get("email"),
            groups=[str(g) for g in groups] if isinstance(groups, list) else [],
            claims=claims,
        )

    def _decode_id_token(self, id_token: str) -> dict[str, Any]:
        if self._jwks is None:
            raise AuthenticationError("OIDC discovery not initialised")
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(id_token)
            return jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=self.client_id,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"Invalid ID token: {exc}") from exc


def oidc_provider() -> OidcProvider:
    return OidcProvider()
