"""SAML 2.0 service provider: AuthnRequest, signed response validation, metadata.

The implementation is deliberately small: it supports the HTTP-Redirect binding
for AuthnRequests and the HTTP-POST binding for responses, which is what every
mainstream IdP (Entra ID, Okta, OneLogin, ADFS, Keycloak) uses for web SSO.
Assertions must be signed; unsigned or expired responses are rejected.
"""

from __future__ import annotations

import base64
import time
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from lxml import etree
from signxml import XMLVerifier

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.logging import get_logger

log = get_logger("ofme.saml")

NS_SAML = "urn:oasis:names:tc:SAML:2.0:assertion"
NS_SAMLP = "urn:oasis:names:tc:SAML:2.0:protocol"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS = {"saml": NS_SAML, "samlp": NS_SAMLP, "ds": NS_DS}

#: Clock skew tolerated on NotBefore/NotOnOrAfter, in seconds.
CLOCK_SKEW = 120
#: How long a consumed assertion ID is remembered (replay protection).
REPLAY_TTL = 600


@dataclass(slots=True)
class SamlIdentity:
    subject: str
    username: str
    email: str
    name: str | None
    groups: list[str]
    claims: dict[str, Any] = field(default_factory=dict)


def _pem(cert: str) -> str:
    cert = cert.strip()
    if "BEGIN CERTIFICATE" in cert:
        return cert
    body = "".join(cert.split())
    lines = [body[index : index + 64] for index in range(0, len(body), 64)]
    return "-----BEGIN CERTIFICATE-----\n" + "\n".join(lines) + "\n-----END CERTIFICATE-----\n"


def _text(element: etree._Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _attribute_values(assertion: etree._Element) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for attribute in assertion.findall("saml:AttributeStatement/saml:Attribute", NS):
        name = attribute.get("Name") or attribute.get("FriendlyName") or ""
        collected = [
            _text(value)
            for value in attribute.findall("saml:AttributeValue", NS)
            if _text(value)
        ]
        if name and collected:
            values[name] = [item for item in collected if item]
    return values


def _pick(attributes: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        if name and name in attributes and attributes[name]:
            return attributes[name][0]
    # IdPs occasionally use a URN or a differently-cased friendly name.
    lowered = {key.lower(): value for key, value in attributes.items()}
    for name in names:
        value = lowered.get(name.lower()) if name else None
        if value:
            return value[0]
    return None


def _groups(attributes: dict[str, list[str]], name: str) -> list[str]:
    if name in attributes:
        return attributes[name]
    lowered = {key.lower(): value for key, value in attributes.items()}
    return lowered.get(name.lower(), [])


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _remember_assertion(assertion_id: str) -> bool:
    """Return False when the assertion was already consumed.

    Redis is used when available so the check is shared by all API replicas; the
    process-local fallback keeps single-replica deployments safe.
    """
    now = time.time()
    _LOCAL_REPLAY[:] = [item for item in _LOCAL_REPLAY if item[1] > now]
    if any(item[0] == assertion_id for item in _LOCAL_REPLAY):
        return False
    _LOCAL_REPLAY.append((assertion_id, now + REPLAY_TTL))
    try:
        import redis

        client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            accepted = client.set(
                f"ofme:saml:assertion:{assertion_id}", "1", nx=True, ex=REPLAY_TTL
            )
        finally:
            client.close()
        return bool(accepted)
    except Exception:  # noqa: BLE001 - Redis is optional for this check
        return True


_LOCAL_REPLAY: list[tuple[str, float]] = []


class SamlProvider:
    def __init__(self) -> None:
        self.enabled = bool(
            settings.SAML_ENABLED and settings.SAML_IDP_SSO_URL and settings.SAML_IDP_CERT
        )
        self.entity_id = settings.SAML_SP_ENTITY_ID
        self.acs_url = settings.SAML_SP_ACS_URL
        self.idp_sso_url = settings.SAML_IDP_SSO_URL
        self.idp_entity_id = settings.SAML_IDP_ENTITY_ID or settings.SAML_IDP_SSO_URL

    # ------------------------------------------------------------------ requests
    def authorization_url(
        self, *, tenant_slug: str | None, relay_state: str, request_id: str | None = None
    ) -> str:
        request_id = request_id or ("_" + uuid.uuid4().hex)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        xml = (
            f'<samlp:AuthnRequest xmlns:samlp="{NS_SAMLP}" xmlns:saml="{NS_SAML}"'
            f' ID="{request_id}" Version="2.0" IssueInstant="{now}"'
            f' Destination="{self.idp_sso_url}"'
            f' AssertionConsumerServiceURL="{self.acs_url}"'
            ' ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
            f'<saml:Issuer>{self.entity_id}</saml:Issuer>'
            '<samlp:NameIDPolicy Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"'
            ' AllowCreate="true"/>'
            "</samlp:AuthnRequest>"
        )
        compressed = zlib.compress(xml.encode("utf-8"))[2:-4]
        encoded = base64.b64encode(compressed).decode("ascii")
        params = {
            "SAMLRequest": encoded,
            "RelayState": relay_state,
        }
        query = urlencode(params)
        if settings.SAML_SP_KEY and settings.SAML_SP_CERT:
            query = self._sign_query(query, relay_state, encoded)
        return f"{self.idp_sso_url}{'&' if '?' in self.idp_sso_url else '?'}{query}"

    def _sign_query(self, query: str, relay_state: str, encoded: str) -> str:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        sig_alg = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
        signed = (
            f"SAMLRequest={urlencode({'': encoded})[1:]}&RelayState="
            f"{urlencode({'': relay_state})[1:]}&SigAlg={urlencode({'': sig_alg})[1:]}"
        )
        key = serialization.load_pem_private_key(settings.SAML_SP_KEY.encode("utf-8"), None)
        signature = key.sign(signed.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
        return f"{query}&SigAlg={urlencode({'': sig_alg})[1:]}&Signature={urlencode({'': base64.b64encode(signature).decode()})[1:]}"

    # ----------------------------------------------------------------- responses
    def consume_response(self, saml_response: str, *, expected_request_id: str | None = None) -> SamlIdentity:
        try:
            raw = base64.b64decode(saml_response, validate=True)
        except Exception as exc:  # noqa: BLE001 - malformed input is an auth failure
            raise AuthenticationError("SAMLResponse is not valid base64") from exc
        try:
            root = etree.fromstring(raw)
        except etree.XMLSyntaxError as exc:
            raise AuthenticationError("SAMLResponse is not valid XML") from exc

        self._verify_signature(root)

        status = root.find("samlp:Status/samlp:StatusCode", NS)
        if status is None or status.get("Value") != "urn:oasis:names:tc:SAML:2.0:status:Success":
            message = _text(root.find("samlp:Status/samlp:StatusMessage", NS))
            raise AuthenticationError(message or "Identity provider rejected the login")

        assertion = root if etree.QName(root).localname == "Assertion" else root.find(
            "saml:Assertion", NS
        )
        if assertion is None:
            raise AuthenticationError("SAML response does not contain an assertion")

        self._validate_conditions(assertion, expected_request_id)
        assertion_id = assertion.get("ID") or ""
        if assertion_id and not _remember_assertion(assertion_id):
            raise AuthenticationError("SAML assertion has already been used")

        subject = assertion.find("saml:Subject/saml:NameID", NS)
        name_id = _text(subject)
        if not name_id:
            raise AuthenticationError("SAML assertion has no NameID")
        attributes = _attribute_values(assertion)
        username = _pick(attributes, settings.SAML_ATTRIBUTE_USERNAME, "uid", "sAMAccountName")
        email = _pick(attributes, settings.SAML_ATTRIBUTE_EMAIL, "mail", "email")
        display_name = _pick(attributes, settings.SAML_ATTRIBUTE_NAME, "cn", "displayName")
        groups = _groups(attributes, settings.SAML_ATTRIBUTE_GROUPS)
        return SamlIdentity(
            subject=name_id,
            username=(username or name_id)[:100],
            email=email or f"{name_id}@saml.local",
            name=display_name,
            groups=groups,
            claims={"attributes": attributes},
        )

    def _verify_signature(self, root: etree._Element) -> None:
        cert = _pem(settings.SAML_IDP_CERT)
        candidates: list[etree._Element] = []
        if root.find("ds:Signature", NS) is not None:
            candidates.append(root)
        assertion = root.find("saml:Assertion", NS)
        if assertion is not None and assertion.find("ds:Signature", NS) is not None:
            candidates.append(assertion)
        if not candidates:
            raise AuthenticationError("SAML response is not signed")
        for element in candidates:
            try:
                XMLVerifier().verify(element, x509_cert=cert)
                return
            except Exception as exc:  # noqa: BLE001 - try the next signed element
                last_error = exc
        raise AuthenticationError(f"SAML signature validation failed: {last_error}")

    def _validate_conditions(
        self, assertion: etree._Element, expected_request_id: str | None
    ) -> None:
        subject_confirmation = assertion.find(
            "saml:Subject/saml:SubjectConfirmation/saml:SubjectConfirmationData", NS
        )
        if subject_confirmation is not None:
            in_response_to = subject_confirmation.get("InResponseTo")
            if expected_request_id and in_response_to and in_response_to != expected_request_id:
                raise AuthenticationError("SAML response does not match the request")
            not_on_or_after = _parse_datetime(subject_confirmation.get("NotOnOrAfter"))
            if not_on_or_after and datetime.now(UTC) > not_on_or_after:
                raise AuthenticationError("SAML assertion has expired")

        conditions = assertion.find("saml:Conditions", NS)
        if conditions is not None:
            now = datetime.now(UTC)
            not_before = _parse_datetime(conditions.get("NotBefore"))
            not_on_or_after = _parse_datetime(conditions.get("NotOnOrAfter"))
            if not_before and now.timestamp() + CLOCK_SKEW < not_before.timestamp():
                raise AuthenticationError("SAML assertion is not valid yet")
            if not_on_or_after and now.timestamp() - CLOCK_SKEW > not_on_or_after.timestamp():
                raise AuthenticationError("SAML assertion has expired")
            audiences = [
                _text(node)
                for node in conditions.findall(
                    "saml:AudienceRestriction/saml:Audience", NS
                )
            ]
            if audiences and self.entity_id not in audiences:
                raise AuthenticationError("SAML assertion is addressed to another service")

    # ------------------------------------------------------------------ metadata
    def metadata(self) -> str:
        key_descriptor = ""
        if settings.SAML_SP_CERT:
            body = "".join(_pem(settings.SAML_SP_CERT).splitlines()[1:-1])
            key_descriptor = (
                '<md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data>'
                f"<ds:X509Certificate>{body}</ds:X509Certificate>"
                "</ds:X509Data></ds:KeyInfo></md:KeyDescriptor>"
            )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"'
            f' xmlns:ds="{NS_DS}" entityID="{self.entity_id}">'
            "<md:SPSSODescriptor"
            ' AuthnRequestsSigned="false" WantAssertionsSigned="true"'
            ' protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
            f"{key_descriptor}"
            '<md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified</md:NameIDFormat>'
            '<md:AssertionConsumerService'
            ' Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"'
            f' Location="{self.acs_url}" index="0" isDefault="true"/>'
            "</md:SPSSODescriptor>"
            "</md:EntityDescriptor>"
        )


def saml_provider() -> SamlProvider:
    return SamlProvider()
