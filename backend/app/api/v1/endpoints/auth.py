"""Authentication endpoints: local/federated login, refresh, MFA, sessions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import (
    ClientIP,
    CurrentPrincipal,
    SessionDep,
    get_user_agent,
)
from app.core.config import settings
from app.core.exceptions import AuthenticationError, BadRequestError
from app.core.security import create_scoped_token, decode_token
from app.integrations.ldap import ldap_authenticator
from app.integrations.oidc import oidc_provider
from app.integrations.saml import saml_provider
from app.models.identity import RefreshToken
from app.schemas.auth import (
    AuthProviders,
    CurrentUser,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    MfaDisableRequest,
    MfaSetupResponse,
    MfaVerifyRequest,
    OidcAuthorizeResponse,
    OidcCallback,
    PasswordChange,
    RefreshRequest,
    SamlAuthorizeResponse,
    SessionInfo,
    TokenPair,
)
from app.schemas.common import Message
from app.services.auth import AuthService, LoginOutcome

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LdapLoginRequest(BaseModel):
    username: str
    password: str
    tenant: str | None = None


def _current_user(outcome: LoginOutcome) -> CurrentUser | None:
    if outcome.user is None:
        return None
    user = outcome.user
    return CurrentUser(
        id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        roles=outcome.roles,
        permissions=outcome.permissions,
        is_superadmin=user.is_superadmin,
        mfa_enabled=user.mfa_enabled,
        auth_provider=user.auth_provider,
        last_login_at=user.last_login_at,
    )


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str, expires_in: int) -> None:
    """Set HttpOnly Secure SameSite cookies for tokens."""
    cookie_settings = {
        "httponly": True,
        "secure": settings.ENVIRONMENT == "production",
        "samesite": "lax",  # Use lax for cross-site navigation during login
        "path": "/",
        "max_age": expires_in,
    }
    response.set_cookie(key="ofme_access_token", value=access_token, **cookie_settings)
    # Refresh token with longer expiry
    refresh_settings = {**cookie_settings, "max_age": settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400}
    response.set_cookie(key="ofme_refresh_token", value=refresh_token, **refresh_settings)


def _clear_auth_cookies(response: Response) -> None:
    """Clear auth cookies on logout."""
    cookie_settings = {
        "httponly": True,
        "secure": settings.ENVIRONMENT == "production",
        "samesite": "lax",
        "path": "/",
        "max_age": 0,
        "expires": 0,
    }
    response.delete_cookie(key="ofme_access_token", **cookie_settings)
    response.delete_cookie(key="ofme_refresh_token", **cookie_settings)


def _response(outcome: LoginOutcome, response: Response) -> LoginResponse:
    if outcome.challenge is not None:
        return LoginResponse(
            mfa_required=True,
            challenge_token=outcome.challenge.challenge_token,
            methods=outcome.challenge.methods,
        )
    assert outcome.tokens is not None
    _set_auth_cookies(response, outcome.tokens.access_token, outcome.tokens.refresh_token, outcome.tokens.expires_in)
    return LoginResponse(
        access_token=outcome.tokens.access_token,
        refresh_token=outcome.tokens.refresh_token,
        expires_in=outcome.tokens.expires_in,
        user=_current_user(outcome),
    )


@router.post("/login", response_model=LoginResponse, summary="Password login (with optional TOTP)")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    ip: ClientIP,
) -> LoginResponse:
    service = AuthService(session)
    outcome = await service.login(
        username=payload.username,
        password=payload.password,
        tenant_slug=payload.tenant,
        mfa_code=payload.mfa_code,
        ip=ip,
        user_agent=await get_user_agent(request),
    )
    return _response(outcome, response)


@router.post("/ldap/login", response_model=LoginResponse, summary="LDAP / Active Directory login")
async def ldap_login(
    payload: LdapLoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    ip: ClientIP,
) -> LoginResponse:
    outcome = await AuthService(session).login_ldap(
        username=payload.username,
        password=payload.password,
        tenant_slug=payload.tenant,
        ip=ip,
        user_agent=await get_user_agent(request),
    )
    return _response(outcome, response)


@router.post("/mfa/verify", response_model=LoginResponse, summary="Complete an MFA challenge")
async def verify_mfa(
    payload: MfaVerifyRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    ip: ClientIP,
    challenge_token: str = "",
) -> LoginResponse:
    token = payload.challenge_token or challenge_token or (request.headers.get("x-mfa-challenge") or "")
    if not token:
        raise AuthenticationError("Missing MFA challenge token")
    outcome = await AuthService(session).complete_mfa(
        challenge_token=token, code=payload.code, ip=ip, user_agent=await get_user_agent(request)
    )
    return _response(outcome, response)


@router.post("/refresh", response_model=TokenPair, summary="Rotate refresh token")
async def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    ip: ClientIP,
) -> TokenPair:
    # Try to get refresh token from cookie if not in body
    refresh_token = payload.refresh_token
    if not refresh_token:
        refresh_token = request.cookies.get("ofme_refresh_token")
    if not refresh_token:
        raise AuthenticationError("Missing refresh token")

    result = await AuthService(session).refresh(
        refresh_token, ip=ip, user_agent=await get_user_agent(request)
    )
    # Set new cookies with rotated tokens
    _set_auth_cookies(response, result.access_token, result.refresh_token, result.expires_in)
    return result


@router.post("/logout", response_model=Message, summary="Revoke session(s)")
async def logout(
    payload: LogoutRequest,
    principal: CurrentPrincipal,
    session: SessionDep,
    response: Response,
) -> Message:
    if principal.user_id is None:
        raise AuthenticationError("API keys cannot call logout")
    count = await AuthService(session, principal.tenant_id).logout(
        user_id=principal.user_id,
        refresh_token=payload.refresh_token,
        all_sessions=payload.all_sessions,
    )
    _clear_auth_cookies(response)
    return Message(message=f"Revoked {count} session(s)")


@router.get("/me", response_model=CurrentUser, summary="Current identity")
async def me(principal: CurrentPrincipal, session: SessionDep) -> CurrentUser:
    from app.models.identity import User

    if principal.user_id is None:
        return CurrentUser(
            id=principal.api_key_id or uuid.uuid4(),
            tenant_id=principal.tenant_id,
            username=principal.username,
            email=principal.email or "api-key@ofme.local",
            full_name="Service Account",
            roles=principal.roles,
            permissions=sorted(principal.permissions),
            is_superadmin=principal.is_superadmin,
            mfa_enabled=False,
            auth_provider="local",
        )
    user = await session.get(User, principal.user_id)
    if user is None:
        raise AuthenticationError("User no longer exists")
    return CurrentUser(
        id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        roles=principal.roles,
        permissions=sorted(principal.permissions),
        is_superadmin=user.is_superadmin,
        mfa_enabled=user.mfa_enabled,
        auth_provider=user.auth_provider,
        last_login_at=user.last_login_at,
    )


@router.post("/password", response_model=Message, summary="Change own password")
async def change_password(
    payload: PasswordChange, principal: CurrentPrincipal, session: SessionDep
) -> Message:
    if principal.user_id is None:
        raise BadRequestError("API keys have no password")
    await AuthService(session, principal.tenant_id).change_password(
        user_id=principal.user_id, current=payload.current_password, new=payload.new_password
    )
    return Message(message="Password updated; all sessions revoked")


@router.post("/mfa/setup", response_model=MfaSetupResponse, summary="Start TOTP enrolment")
async def setup_mfa(principal: CurrentPrincipal, session: SessionDep) -> MfaSetupResponse:
    if principal.user_id is None:
        raise BadRequestError("API keys cannot enrol MFA")
    secret, uri, codes = await AuthService(session, principal.tenant_id).setup_mfa(principal.user_id)
    return MfaSetupResponse(secret=secret, provisioning_uri=uri, backup_codes=codes)


@router.post("/mfa/verify-setup", response_model=Message, summary="Confirm TOTP enrolment")
async def verify_mfa_setup(
    payload: MfaVerifyRequest, principal: CurrentPrincipal, session: SessionDep
) -> Message:
    if principal.user_id is None:
        raise BadRequestError("API keys cannot enrol MFA")
    await AuthService(session, principal.tenant_id).verify_mfa_setup(principal.user_id, payload.code)
    return Message(message="MFA enabled")


@router.post("/mfa/disable", response_model=Message, summary="Disable TOTP")
async def disable_mfa(
    payload: MfaDisableRequest, principal: CurrentPrincipal, session: SessionDep
) -> Message:
    if principal.user_id is None:
        raise BadRequestError("API keys cannot change MFA")
    await AuthService(session, principal.tenant_id).disable_mfa(
        principal.user_id, password=payload.password, code=payload.code
    )
    return Message(message="MFA disabled")


@router.get("/sessions", response_model=list[SessionInfo], summary="Active refresh sessions")
async def sessions(principal: CurrentPrincipal, session: SessionDep) -> list[SessionInfo]:
    if principal.user_id is None:
        return []
    stmt = (
        select(RefreshToken)
        .where(
            RefreshToken.user_id == principal.user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(UTC),
        )
        .order_by(RefreshToken.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        SessionInfo(
            id=row.id,
            user_id=row.user_id,
            jti=row.jti,
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )
        for row in rows
    ]


@router.delete("/sessions", response_model=Message, summary="Revoke all sessions")
async def revoke_sessions(principal: CurrentPrincipal, session: SessionDep) -> Message:
    if principal.user_id is None:
        raise BadRequestError("API keys have no sessions")
    count = await AuthService(session, principal.tenant_id).logout(
        user_id=principal.user_id, refresh_token=None, all_sessions=True
    )
    return Message(message=f"Revoked {count} session(s)")


@router.get("/providers", response_model=AuthProviders, summary="Configured identity providers")
async def providers() -> AuthProviders:
    return AuthProviders(
        ldap=ldap_authenticator.enabled,
        oidc=oidc_provider().enabled,
        entra_id=bool(settings.ENTRA_TENANT_ID and settings.ENTRA_CLIENT_ID),
        saml=saml_provider().enabled,
        mfa_enabled=settings.ENABLE_MFA,
    )


@router.get(
    "/oidc/authorize", response_model=OidcAuthorizeResponse, summary="Begin OIDC authorization code flow"
)
async def oidc_authorize(tenant: str | None = None, entra: bool = False) -> OidcAuthorizeResponse:
    provider = oidc_provider()
    if not provider.enabled and not entra:
        raise BadRequestError("OIDC is not configured")
    if entra:
        provider = oidc_provider.__class__.entra_id()
    nonce = uuid.uuid4().hex
    state = create_scoped_token(
        subject=f"oidc:{tenant or '-'}",
        token_type="oidc_state",
        tenant_id=None,
        ttl_seconds=600,
        extra={"purpose": "oidc_state", "nonce": nonce, "tenant": tenant},
    )
    return OidcAuthorizeResponse(
        authorization_url=await provider.authorization_url(state, nonce), state=state
    )


@router.post("/oidc/callback", response_model=LoginResponse, summary="Complete OIDC authorization code flow")
async def oidc_callback(
    payload: OidcCallback,
    request: Request,
    session: SessionDep,
    ip: ClientIP,
) -> LoginResponse:
    state = payload.state or ""
    if not state:
        raise AuthenticationError("Missing OIDC state")
    claims = decode_token(state, expected_type="oidc_state")
    nonce = claims.get("nonce")
    tenant_slug = claims.get("tenant")
    provider = oidc_provider()
    identity = await provider.exchange_code(payload.code)
    if nonce and identity.claims.get("nonce") and identity.claims["nonce"] != nonce:
        raise AuthenticationError("OIDC nonce mismatch")

    service = AuthService(session)
    user = await service._provision_external_user(  # noqa: SLF001 - intentional reuse of provisioning
        username=(identity.username or identity.subject)[:100],
        email=identity.email or f"{identity.subject}@oidc.local",
        full_name=identity.name,
        provider=__import__("app.models.enums", fromlist=["AuthProvider"]).AuthProvider.OIDC,
        external_id=identity.subject,
        role_names=[],
        tenant_id=await service._resolve_tenant(tenant_slug),  # noqa: SLF001
    )
    outcome = await service._finish_external_login(  # noqa: SLF001
        user, ip=ip, user_agent=await get_user_agent(request), action="auth.login_oidc"
    )
    return _response(outcome)


# --------------------------------------------------------------------------- SAML
@router.get(
    "/saml/authorize",
    response_model=SamlAuthorizeResponse,
    summary="Begin SAML 2.0 web SSO",
)
async def saml_authorize(tenant: str | None = None) -> SamlAuthorizeResponse:
    provider = saml_provider()
    if not provider.enabled:
        raise BadRequestError("SAML is not configured")
    request_id = "_" + uuid.uuid4().hex
    state = create_scoped_token(
        subject=f"saml:{tenant or '-'}",
        token_type="saml_state",
        tenant_id=None,
        ttl_seconds=600,
        extra={"purpose": "saml_state", "tenant": tenant, "request_id": request_id},
    )
    return SamlAuthorizeResponse(
        authorization_url=provider.authorization_url(
            tenant_slug=tenant, relay_state=state, request_id=request_id
        ),
        state=state,
    )


@router.post("/saml/acs", summary="SAML assertion consumer service", include_in_schema=False)
async def saml_acs(
    request: Request,
    response: Response,
    session: SessionDep,
    ip: ClientIP,
    saml_response: str = Form(..., alias="SAMLResponse"),
    relay_state: str = Form("", alias="RelayState"),
) -> RedirectResponse:
    """Consume an IdP response and set HttpOnly cookies, then redirect to frontend."""
    target = settings.FRONTEND_URL.rstrip("/") + "/saml/callback"
    try:
        claims = decode_token(relay_state, expected_type="saml_state") if relay_state else {}
        outcome = await AuthService(session).login_saml(
            saml_response=saml_response,
            tenant_slug=claims.get("tenant"),
            expected_request_id=claims.get("request_id"),
            ip=ip,
            user_agent=await get_user_agent(request),
        )
    except Exception as exc:  # noqa: BLE001 - the SPA renders the error
        message = exc.message if isinstance(exc, AuthenticationError) else str(exc)
        from urllib.parse import quote

        return RedirectResponse(
            f"{target}#error={quote(message or 'SAML login failed')}", status_code=303
        )
    assert outcome.tokens is not None
    _set_auth_cookies(response, outcome.tokens.access_token, outcome.tokens.refresh_token, outcome.tokens.expires_in)
    return RedirectResponse(target, status_code=303)


@router.get("/saml/metadata", summary="SAML service provider metadata", include_in_schema=False)
async def saml_metadata() -> Response:
    provider = saml_provider()
    if not provider.enabled:
        raise BadRequestError("SAML is not configured")
    return Response(content=provider.metadata(), media_type="application/samlmetadata+xml")
