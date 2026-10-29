"""Authentication use-cases: local, LDAP/AD, OIDC, MFA, refresh rotation, sessions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
)
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_scoped_token,
    decode_token,
    enforce_password_policy,
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_code,
    hash_password,
    token_fingerprint,
    totp_provisioning_uri,
    verify_password,
    verify_totp,
)
from app.models.enums import AuthProvider, RoleName, TenantStatus, UserStatus
from app.models.identity import ApiKey, RefreshToken, Role, User
from app.repositories.identity import (
    ApiKeyRepository,
    RefreshTokenRepository,
    RoleRepository,
    TenantRepository,
    UserRepository,
)
from app.schemas.auth import MfaChallenge, TokenPair
from app.services.audit import AuditService

log = get_logger("ofme.auth")


@dataclass(slots=True)
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_in: int
    mfa_required: bool = False


@dataclass(slots=True)
class LoginOutcome:
    tokens: TokenPair | None = None
    challenge: MfaChallenge | None = None
    user: User | None = None
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)


class AuthService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.users = UserRepository(session, tenant_id)
        self.roles = RoleRepository(session, tenant_id)
        self.tenants = TenantRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session, tenant_id)
        self.api_keys = ApiKeyRepository(session, tenant_id)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ helpers
    async def _resolve_tenant(self, tenant_slug: str | None) -> uuid.UUID | None:
        if not tenant_slug:
            return None
        tenant = await self.tenants.get_by_slug(tenant_slug)
        if tenant is None:
            raise AuthenticationError("Unknown tenant")
        if tenant.status in {TenantStatus.SUSPENDED, TenantStatus.CANCELLED}:
            raise AuthenticationError("Tenant is not active")
        return tenant.id

    async def _effective_roles_and_permissions(self, user: User) -> tuple[list[str], list[str]]:
        if user.is_superadmin:
            from app.rbac.permissions import SUPER_ADMIN

            return ["SuperAdmin"], sorted(p.value for p in SUPER_ADMIN)
        role_names = [role.name for role in user.roles]
        permissions: set[str] = set()
        for role in user.roles:
            permissions.update(role.permissions or [])
        return role_names, sorted(permissions)

    def _issue_tokens(
        self,
        user: User,
        roles: list[str],
        permissions: list[str],
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> tuple[str, str, datetime, str]:
        access = create_access_token(
            user_id=user.id,
            tenant_id=user.tenant_id,
            roles=roles,
            permissions=permissions,
            is_superadmin=user.is_superadmin,
        )
        refresh, jti, expires_at = create_refresh_token(user_id=user.id, tenant_id=user.tenant_id)
        record = RefreshToken(
            user_id=user.id,
            tenant_id=user.tenant_id,
            jti=jti,
            token_hash=token_fingerprint(refresh),
            expires_at=expires_at,
            ip_address=ip,
            user_agent=(user_agent or "")[:512] or None,
        )
        self.session.add(record)
        return access, refresh, expires_at, jti

    # ------------------------------------------------------------------ local login
    async def login(
        self,
        *,
        username: str,
        password: str,
        tenant_slug: str | None,
        mfa_code: str | None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> LoginOutcome:
        tenant_id = await self._resolve_tenant(tenant_slug)
        self.users.tenant_id = tenant_id
        user = await self.users.get_by_username(username, tenant_id)
        if user is None:
            # The login form accepts "username or e-mail"; the bootstrap account
            # in particular is documented by its e-mail address.
            user = await self.users.get_by_email(username, tenant_id)
        if user is None and tenant_slug is None:
            # SuperAdmin fallback: unique usernames/e-mails across the platform.
            user = (
                (
                    await self.session.execute(
                        select(User).where(
                            or_(User.username == username, User.email == username),
                            User.is_superadmin.is_(True),
                            User.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .first()
            )

        if user is None or not verify_password(password, user.password_hash):
            if user is not None:
                await self._register_failure(user)
            await self.audit.record(
                action="auth.login",
                resource_type="User",
                resource_id=username,
                tenant_id=tenant_id,
                actor=username,
                result="failure",
                ip_address=ip,
                user_agent=user_agent,
                error="invalid_credentials",
            )
            await self.session.commit()
            raise AuthenticationError("Invalid username or password")

        if user.status in {UserStatus.LOCKED, UserStatus.INACTIVE}:
            raise AuthenticationError("Account is locked or inactive")
        if user.locked_until and user.locked_until > datetime.now(UTC):
            raise AuthenticationError("Account temporarily locked")

        if user.tenant_id:
            tenant = await self.tenants.get(user.tenant_id)
            if tenant and tenant.status in {TenantStatus.SUSPENDED, TenantStatus.CANCELLED}:
                raise AuthenticationError("Tenant is not active")

        if settings.ENABLE_MFA and user.mfa_enabled:
            if not mfa_code:
                challenge = create_scoped_token(
                    subject=str(user.id),
                    token_type="mfa_challenge",
                    tenant_id=user.tenant_id,
                    ttl_seconds=300,
                )
                await self.audit.record(
                    action="auth.mfa_challenge",
                    resource_type="User",
                    resource_id=user.id,
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    actor=user.username,
                    ip_address=ip,
                    user_agent=user_agent,
                )
                await self.session.commit()
                return LoginOutcome(challenge=MfaChallenge(challenge_token=challenge))

            if not self._check_mfa(user, mfa_code):
                await self._register_failure(user)
                await self.session.commit()
                raise AuthenticationError("Invalid MFA code")

        roles, permissions = await self._effective_roles_and_permissions(user)
        access, refresh, _expires, _jti = self._issue_tokens(
            user, roles, permissions, ip=ip, user_agent=user_agent
        )
        user.last_login_at = datetime.now(UTC)
        user.failed_login_attempts = 0
        user.locked_until = None

        await self.audit.record(
            action="auth.login",
            resource_type="User",
            resource_id=user.id,
            tenant_id=user.tenant_id,
            user_id=user.id,
            actor=user.username,
            ip_address=ip,
            user_agent=user_agent,
        )
        await self.session.commit()

        return LoginOutcome(
            tokens=TokenPair(
                access_token=access,
                refresh_token=refresh,
                expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            ),
            user=user,
            roles=roles,
            permissions=permissions,
        )

    async def complete_mfa(
        self,
        *,
        challenge_token: str,
        code: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> LoginOutcome:
        payload = decode_token(challenge_token, expected_type="mfa_challenge")
        user = await self.users.get(uuid.UUID(payload["sub"]))
        if user is None:
            raise AuthenticationError("Challenge subject no longer exists")
        if not self._check_mfa(user, code):
            await self._register_failure(user)
            await self.session.commit()
            raise AuthenticationError("Invalid MFA code")

        roles, permissions = await self._effective_roles_and_permissions(user)
        access, refresh, _expires, _jti = self._issue_tokens(
            user, roles, permissions, ip=ip, user_agent=user_agent
        )
        user.last_login_at = datetime.now(UTC)
        user.failed_login_attempts = 0
        await self.audit.record(
            action="auth.mfa_login",
            resource_type="User",
            resource_id=user.id,
            tenant_id=user.tenant_id,
            user_id=user.id,
            actor=user.username,
            ip_address=ip,
            user_agent=user_agent,
        )
        await self.session.commit()
        return LoginOutcome(
            tokens=TokenPair(
                access_token=access,
                refresh_token=refresh,
                expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            ),
            user=user,
            roles=roles,
            permissions=permissions,
        )

    def _check_mfa(self, user: User, code: str) -> bool:
        from app.core.security import decrypt_secret

        if not user.mfa_secret_encrypted:
            return False
        secret = decrypt_secret(user.mfa_secret_encrypted)
        if verify_totp(secret, code):
            return True
        hashed = hash_backup_code(code.strip())
        codes = list(user.mfa_backup_codes or [])
        if hashed in codes:
            codes.remove(hashed)
            user.mfa_backup_codes = codes
            return True
        return False

    async def _register_failure(self, user: User) -> None:
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= settings.LOGIN_MAX_FAILURES:
            user.status = UserStatus.LOCKED
            user.locked_until = datetime.now(UTC) + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
        await self.session.flush()

    # ------------------------------------------------------------------ tokens
    async def refresh(
        self, refresh_token: str, *, ip: str | None = None, user_agent: str | None = None
    ) -> TokenPair:
        payload = decode_token(refresh_token, expected_type="refresh")
        jti = payload["jti"]
        record = (
            (
                await self.session.execute(
                    select(RefreshToken).where(
                        RefreshToken.jti == jti,
                        RefreshToken.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )
        if record is None:
            raise AuthenticationError("Refresh token is not active")
        if record.expires_at <= datetime.now(UTC):
            raise AuthenticationError("Refresh token expired")
        if record.token_hash != token_fingerprint(refresh_token):
            record.revoked_at = datetime.now(UTC)
            await self.session.commit()
            raise AuthenticationError("Refresh token mismatch")

        user = await self.users.get(record.user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise AuthenticationError("User is not active")

        roles, permissions = await self._effective_roles_and_permissions(user)
        access, new_refresh, _expires, new_jti = self._issue_tokens(
            user, roles, permissions, ip=ip, user_agent=user_agent
        )
        record.revoked_at = datetime.now(UTC)
        record.replaced_by = new_jti
        await self.session.commit()
        return TokenPair(
            access_token=access,
            refresh_token=new_refresh,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def logout(self, *, user_id: uuid.UUID, refresh_token: str | None, all_sessions: bool) -> int:
        if all_sessions:
            count = await self.refresh_tokens.revoke_all_for_user(user_id)
        elif refresh_token:
            try:
                payload = decode_token(refresh_token, expected_type="refresh")
            except AuthenticationError:
                count = 0
            else:
                record = (
                    (
                        await self.session.execute(
                            select(RefreshToken).where(RefreshToken.jti == payload["jti"])
                        )
                    )
                    .scalars()
                    .first()
                )
                if record and not record.revoked_at:
                    record.revoked_at = datetime.now(UTC)
                    count = 1
                else:
                    count = 0
        else:
            count = await self.refresh_tokens.revoke_all_for_user(user_id)

        await self.audit.record(
            action="auth.logout", resource_type="User", resource_id=user_id, user_id=user_id
        )
        await self.session.commit()
        return count

    # ------------------------------------------------------------------ password
    async def change_password(self, *, user_id: uuid.UUID, current: str, new: str) -> None:
        user = await self.users.get_or_404(user_id)
        if user.auth_provider != AuthProvider.LOCAL or not verify_password(current, user.password_hash):
            raise AuthenticationError("Current password is incorrect")
        enforce_password_policy(new)
        user.password_hash = hash_password(new)
        user.password_changed_at = datetime.now(UTC)
        await self.refresh_tokens.revoke_all_for_user(user.id)
        await self.audit.record(
            action="auth.password_changed",
            resource_type="User",
            resource_id=user.id,
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        await self.session.commit()

    # ------------------------------------------------------------------ MFA
    async def setup_mfa(self, user_id: uuid.UUID) -> tuple[str, str, list[str]]:
        user = await self.users.get_or_404(user_id)
        if user.mfa_enabled:
            raise ConflictError("MFA is already enabled")
        from app.core.security import encrypt_secret

        secret = generate_totp_secret()
        user.mfa_secret_encrypted = encrypt_secret(secret)
        codes = generate_backup_codes()
        user.mfa_backup_codes = [hash_backup_code(code) for code in codes]
        await self.session.commit()
        return secret, totp_provisioning_uri(secret, user.email), codes

    async def verify_mfa_setup(self, user_id: uuid.UUID, code: str) -> None:
        user = await self.users.get_or_404(user_id)
        if not user.mfa_secret_encrypted:
            raise BadRequestError("MFA setup was not started")
        from app.core.security import decrypt_secret

        if not verify_totp(decrypt_secret(user.mfa_secret_encrypted), code):
            raise AuthenticationError("Invalid TOTP code")
        user.mfa_enabled = True
        user.mfa_confirmed_at = datetime.now(UTC)
        await self.audit.record(
            action="auth.mfa_enabled",
            resource_type="User",
            resource_id=user.id,
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        await self.session.commit()

    async def disable_mfa(self, user_id: uuid.UUID, *, password: str, code: str) -> None:
        user = await self.users.get_or_404(user_id)
        if not verify_password(password, user.password_hash) or not user.mfa_secret_encrypted:
            raise AuthenticationError("Password or MFA state invalid")
        from app.core.security import decrypt_secret

        if not verify_totp(decrypt_secret(user.mfa_secret_encrypted), code):
            raise AuthenticationError("Invalid TOTP code")
        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        user.mfa_backup_codes = []
        await self.audit.record(
            action="auth.mfa_disabled",
            resource_type="User",
            resource_id=user.id,
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        await self.session.commit()

    # ------------------------------------------------------------------ external providers
    async def login_ldap(
        self,
        *,
        username: str,
        password: str,
        tenant_slug: str | None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> LoginOutcome:
        from app.integrations.ldap import ldap_authenticator

        identity = await ldap_authenticator.authenticate(username, password)
        tenant_id = await self._resolve_tenant(tenant_slug)
        user = await self._provision_external_user(
            username=identity.username,
            email=identity.email or f"{identity.username}@ldap.local",
            full_name=identity.display_name,
            provider=AuthProvider.LDAP,
            external_id=identity.distinguished_name,
            role_names=identity.roles,
            tenant_id=tenant_id,
        )
        return await self._finish_external_login(user, ip=ip, user_agent=user_agent, action="auth.login_ldap")

    async def login_oidc(
        self,
        *,
        code: str,
        tenant_slug: str | None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> LoginOutcome:
        from app.integrations.oidc import oidc_provider

        identity = await oidc_provider().exchange_code(code)
        tenant_id = await self._resolve_tenant(tenant_slug)
        user = await self._provision_external_user(
            username=identity.username or identity.subject,
            email=identity.email or f"{identity.subject}@oidc.local",
            full_name=identity.name,
            provider=AuthProvider.OIDC,
            external_id=identity.subject,
            role_names=[],
            tenant_id=tenant_id,
        )
        return await self._finish_external_login(user, ip=ip, user_agent=user_agent, action="auth.login_oidc")

    async def login_saml(
        self,
        *,
        saml_response: str,
        tenant_slug: str | None,
        expected_request_id: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> LoginOutcome:
        from app.integrations.saml import saml_provider

        identity = saml_provider().consume_response(
            saml_response, expected_request_id=expected_request_id
        )
        tenant_id = await self._resolve_tenant(tenant_slug)
        known_roles = {role.value for role in RoleName}
        role_names = [group for group in identity.groups if group in known_roles]
        if not role_names:
            role_names = [settings.SAML_DEFAULT_ROLE]
        user = await self._provision_external_user(
            username=identity.username,
            email=identity.email,
            full_name=identity.name,
            provider=AuthProvider.SAML,
            external_id=identity.subject,
            role_names=role_names,
            tenant_id=tenant_id,
        )
        return await self._finish_external_login(user, ip=ip, user_agent=user_agent, action="auth.login_saml")

    async def _provision_external_user(
        self,
        *,
        username: str,
        email: str,
        full_name: str | None,
        provider: AuthProvider,
        external_id: str,
        role_names: list[str],
        tenant_id: uuid.UUID | None,
    ) -> User:
        user = (
            (
                await self.session.execute(
                    select(User).where(
                        User.external_id == external_id,
                        User.auth_provider == provider,
                    )
                )
            )
            .scalars()
            .first()
        )
        if user is None:
            user = await self.users.get_by_username(username, tenant_id)
        if user is None:
            if tenant_id is None:
                raise AuthenticationError("Federated login requires a tenant context")
            role_objs: list[Role] = []
            for name in role_names or ["ReadOnly"]:
                role = await self.roles.get_by_name(name, tenant_id)
                if role:
                    role_objs.append(role)
            user = User(
                tenant_id=tenant_id,
                username=username[:100],
                email=email[:255],
                full_name=full_name,
                auth_provider=provider,
                external_id=external_id,
                status=UserStatus.ACTIVE,
                roles=role_objs,
            )
            self.session.add(user)
            await self.session.flush()
            log.info("auth.user_provisioned", username=username, provider=provider.value)
        else:
            user.email = email or user.email
            user.full_name = full_name or user.full_name
            user.external_id = external_id
            await self.session.flush()
        return user

    async def _finish_external_login(
        self, user: User, *, ip: str | None, user_agent: str | None, action: str
    ) -> LoginOutcome:
        if user.status != UserStatus.ACTIVE:
            raise AuthenticationError("User is not active")
        roles, permissions = await self._effective_roles_and_permissions(user)
        access, refresh, _expires, _jti = self._issue_tokens(
            user, roles, permissions, ip=ip, user_agent=user_agent
        )
        user.last_login_at = datetime.now(UTC)
        await self.audit.record(
            action=action,
            resource_type="User",
            resource_id=user.id,
            tenant_id=user.tenant_id,
            user_id=user.id,
            actor=user.username,
            ip_address=ip,
            user_agent=user_agent,
        )
        await self.session.commit()
        return LoginOutcome(
            tokens=TokenPair(
                access_token=access,
                refresh_token=refresh,
                expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            ),
            user=user,
            roles=roles,
            permissions=permissions,
        )

    # ------------------------------------------------------------------ API keys
    async def authenticate_api_key(self, plaintext_key: str) -> tuple[ApiKey, User]:
        from app.core.security import token_fingerprint as fingerprint

        key_hash = fingerprint(plaintext_key)
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        api_key = (await self.session.execute(stmt)).scalars().first()
        if api_key is None:
            raise AuthenticationError("Invalid API key")
        if api_key.expires_at and api_key.expires_at <= datetime.now(UTC):
            raise AuthenticationError("API key expired")
        user = await self.users.get(api_key.user_id) if api_key.user_id else None
        if user is None:
            raise AuthenticationError("API key owner not found")
        api_key.last_used_at = datetime.now(UTC)
        await self.session.flush()
        return api_key, user


async def get_user_permissions(session: AsyncSession, user: User) -> tuple[list[str], list[str]]:
    service = AuthService(session, user.tenant_id)
    return await service._effective_roles_and_permissions(user)
