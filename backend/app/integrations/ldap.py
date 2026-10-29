"""LDAP / Active Directory authentication with group-to-role mapping."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ldap3 import ALL, SIMPLE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPBindError, LDAPException

from app.core.config import settings
from app.core.exceptions import AuthenticationError, UpstreamError
from app.core.logging import get_logger

log = get_logger("ofme.ldap")


@dataclass(slots=True)
class LdapIdentity:
    username: str
    email: str | None
    display_name: str | None
    distinguished_name: str
    groups: list[str]
    roles: list[str]


class LdapAuthenticator:
    def __init__(self) -> None:
        self.server_uri = settings.LDAP_SERVER
        self.base_dn = settings.LDAP_BASE_DN
        self.bind_dn = settings.LDAP_BIND_DN
        self.bind_password = settings.LDAP_BIND_PASSWORD
        self.user_filter = settings.LDAP_USER_FILTER
        self.group_attribute = settings.LDAP_GROUP_ATTRIBUTE
        self.role_map = settings.ldap_role_map

    @property
    def enabled(self) -> bool:
        return bool(self.server_uri and self.base_dn)

    def _server(self) -> Server:
        tls = Tls(validate=2) if settings.LDAP_USE_TLS else None
        return Server(self.server_uri, use_ssl=self.server_uri.startswith("ldaps://"), tls=tls, get_info=ALL)

    def _authenticate_sync(self, username: str, password: str) -> LdapIdentity:
        if not self.enabled:
            raise AuthenticationError("LDAP authentication is not configured")
        server = self._server()
        try:
            with Connection(
                server,
                user=self.bind_dn,
                password=self.bind_password,
                authentication=SIMPLE,
                auto_bind=True,
                raise_exceptions=True,
            ) as service:
                search_filter = self.user_filter.format(username=username)
                service.search(
                    search_base=self.base_dn,
                    search_filter=search_filter,
                    search_scope=SUBTREE,
                    attributes=["cn", "mail", "displayName", self.group_attribute, "memberOf"],
                )
                if not service.entries:
                    raise AuthenticationError("Invalid credentials")
                entry = service.entries[0]
                dn = entry.entry_dn
                groups: list[str] = []
                attribute_name = self.group_attribute if self.group_attribute in entry else "memberOf"
                raw_groups = entry[attribute_name].values if attribute_name in entry else []
                for group in raw_groups or []:
                    groups.append(str(group))
        except LDAPBindError as exc:
            raise UpstreamError(f"LDAP service bind failed: {exc}") from exc
        except LDAPException as exc:
            raise UpstreamError(f"LDAP error: {exc}") from exc

        try:
            with Connection(
                server, user=dn, password=password, authentication=SIMPLE, auto_bind=True
            ) as _user_conn:
                pass
        except LDAPBindError as exc:
            raise AuthenticationError("Invalid credentials") from exc

        roles: list[str] = []
        for group in groups:
            mapped = self.role_map.get(group.lower())
            if mapped and mapped not in roles:
                roles.append(mapped)
        if not roles:
            roles = ["ReadOnly"]

        return LdapIdentity(
            username=username,
            email=str(entry.mail) if "mail" in entry else None,
            display_name=str(entry.displayName)
            if "displayName" in entry
            else str(entry.cn)
            if "cn" in entry
            else None,
            distinguished_name=dn,
            groups=groups,
            roles=roles,
        )

    async def authenticate(self, username: str, password: str) -> LdapIdentity:
        return await asyncio.to_thread(self._authenticate_sync, username, password)


ldap_authenticator = LdapAuthenticator()
