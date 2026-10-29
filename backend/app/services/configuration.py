"""Firewall / NAT / alias / interface / route / VLAN management and deployment."""

from __future__ import annotations

import ipaddress
import re
import uuid
from typing import Any

from jinja2 import Environment, StrictUndefined
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.integrations.opnsense.client import client_for
from app.models.config import (
    Alias,
    DhcpReservation,
    DhcpScope,
    DnsRecord,
    FirewallRule,
    InterfaceConfig,
    NatRule,
    RouteConfig,
    Template,
    VlanConfig,
)
from app.models.enums import AliasType, DnsRecordType, NatType, RuleAction
from app.repositories import UnitOfWork
from app.schemas.config import (
    AliasCreate,
    AliasUpdate,
    InterfaceCreate,
    NatCreate,
    NatUpdate,
    RouteCreate,
    RuleCreate,
    RuleUpdate,
    VlanCreate,
)
from app.services.audit import AuditService
from app.services.devices import DeviceService

log = get_logger("ofme.config")

# Device configuration is plain text (OPNsense XML/shell snippets), not HTML: automatic
# escaping would corrupt the rendered configuration, so autoescape stays disabled.
_jinja = Environment(
    undefined=StrictUndefined,
    autoescape=False,  # noqa: S701 - rendered output is device configuration, not HTML
    trim_blocks=True,
    lstrip_blocks=True,
)


class TemplateService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, **values: Any) -> Template:
        template = Template(tenant_id=self.tenant_id, **values)
        self.session.add(template)
        await self.session.flush()
        await self.audit.record(
            action="template.created",
            resource_type="Template",
            resource_id=template.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": template.name, "kind": template.kind.value},
        )
        return template

    async def render(self, template: Template, variables: dict[str, Any]) -> dict[str, Any]:
        context = {"tenant": str(self.tenant_id), **variables}
        rendered = await self._render_value(template.body, context)
        return {"rendered": rendered, "variables_used": sorted(context.keys()), "warnings": []}

    async def _render_value(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            try:
                return _jinja.from_string(value).render(**context)
            except Exception as exc:  # noqa: BLE001 - surface template errors as validation errors
                raise BadRequestError(f"Template rendering failed: {exc}") from exc
        if isinstance(value, dict):
            return {key: await self._render_value(item, context) for key, item in value.items()}
        if isinstance(value, list):
            return [await self._render_value(item, context) for item in value]
        return value

    async def inherited_body(self, template: Template) -> dict[str, Any]:
        chain = await self.uow.templates.inheritance_chain(template)
        merged: dict[str, Any] = {}
        for ancestor in chain:
            merged = _deep_merge(merged, ancestor.body or {})
        return merged


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = [*result[key], *value]
        else:
            result[key] = value
    return result


class RuleService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, payload: RuleCreate) -> FirewallRule:
        if payload.device_id:
            await self._ensure_device(payload.device_id)
            existing = await self.session.execute(
                self.uow.rules.query().where(
                    FirewallRule.device_id == payload.device_id, FirewallRule.name == payload.name
                )
            )
            if existing.scalars().first():
                raise ConflictError(f"Rule '{payload.name}' already exists on this device")

        order_index = payload.order_index
        if order_index is None:
            order_index = (
                (await self.uow.rules.max_order(payload.device_id)) + 10 if payload.device_id else 10
            )

        rule = FirewallRule(
            tenant_id=self.tenant_id,
            device_id=payload.device_id,
            group_id=payload.group_id,
            name=payload.name,
            description=payload.description,
            action=payload.action,
            direction=payload.direction,
            interface=payload.interface,
            protocol=payload.protocol,
            source=payload.source,
            destination=payload.destination,
            destination_port=payload.destination_port,
            source_port=payload.source_port,
            gateway=payload.gateway,
            log=payload.log,
            enabled=payload.enabled,
            order_index=order_index,
            tags=payload.tags,
            created_by=self.actor_id,
        )
        self._validate_rule(rule)
        conflicts = await self.conflicts(rule)
        if conflicts:
            log.warning("rule.conflicts_detected", rule=rule.name, conflicts=len(conflicts))
        self.session.add(rule)
        await self.session.flush()
        await self.audit.record(
            action="rule.created",
            resource_type="FirewallRule",
            resource_id=rule.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "name": rule.name,
                "action": rule.action.value,
                "device_id": str(rule.device_id) if rule.device_id else None,
            },
        )
        return rule

    async def update(self, rule_id: uuid.UUID, payload: RuleUpdate) -> FirewallRule:
        rule = await self.uow.rules.get_or_404(rule_id)
        before = {
            "action": rule.action.value,
            "source": rule.source,
            "destination": rule.destination,
            "destination_port": rule.destination_port,
            "enabled": rule.enabled,
        }
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(rule, field, value)
        rule.version += 1
        self._validate_rule(rule)
        await self.session.flush()
        await self.audit.record(
            action="rule.updated",
            resource_type="FirewallRule",
            resource_id=rule.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before=before,
            after={
                k: (v.value if hasattr(v, "value") else v)
                for k, v in payload.model_dump(exclude_unset=True).items()
            },
        )
        return rule

    async def delete(self, rule_id: uuid.UUID) -> None:
        rule = await self.uow.rules.get_or_404(rule_id)
        await self.uow.rules.delete(rule)
        await self.audit.record(
            action="rule.deleted",
            resource_type="FirewallRule",
            resource_id=rule.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before={"name": rule.name},
        )

    async def reorder(self, device_id: uuid.UUID, rule_ids: list[uuid.UUID]) -> int:
        rules = await self.uow.rules.for_device(device_id)
        by_id = {rule.id: rule for rule in rules}
        position = 10
        for rule_id in rule_ids:
            rule = by_id.get(rule_id)
            if rule is None:
                continue
            rule.order_index = position
            position += 10
        await self.session.flush()
        await self.audit.record(
            action="rule.reordered",
            resource_type="FirewallRule",
            resource_id=device_id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"order": [str(r) for r in rule_ids]},
        )
        return len(rule_ids)

    # ------------------------------------------------------------------ validation
    @staticmethod
    def _validate_rule(rule: FirewallRule) -> None:
        if (
            rule.action == RuleAction.PASS
            and rule.source == "any"
            and rule.destination == "any"
            and not rule.description
        ):
            raise BadRequestError(
                "A pass-any rule requires a description justifying the exception (audit requirement)"
            )
        for value in (rule.source, rule.destination):
            if value in {"any", ""} or re.fullmatch(r"[A-Za-z0-9_.-]+", value):
                continue
            if "/" in value:
                try:
                    ipaddress.ip_network(value, strict=False)
                except ValueError as exc:
                    raise BadRequestError(f"Invalid network '{value}'") from exc

    async def conflicts(self, rule: FirewallRule) -> list[dict[str, Any]]:
        if rule.device_id is None:
            return []
        peers = await self.uow.rules.for_device(rule.device_id)
        conflicts: list[dict[str, Any]] = []
        for peer in peers:
            if peer.id == rule.id or peer.interface != rule.interface or peer.protocol != rule.protocol:
                continue
            if (
                _overlaps(rule.source, peer.source)
                and _overlaps(rule.destination, peer.destination)
                and _ports_overlap(rule.destination_port, peer.destination_port)
            ):
                conflicts.append(
                    {
                        "rule_id": str(peer.id),
                        "name": peer.name,
                        "reason": "overlapping_match",
                        "shadowed": peer.order_index > rule.order_index,
                        "actions": [rule.action.value, peer.action.value],
                    }
                )
        return conflicts

    async def _ensure_device(self, device_id: uuid.UUID) -> None:
        if await self.uow.devices.get(device_id) is None:
            raise NotFoundError("Device not found")


def _overlaps(left: str, right: str) -> bool:
    if left == right or left in {"any", ""} or right in {"any", ""}:
        return True
    try:
        return ipaddress.ip_network(left, strict=False).overlaps(ipaddress.ip_network(right, strict=False))
    except ValueError:
        return left == right


def _ports_overlap(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return True
    return left == right or left == "any" or right == "any"


NAT_KIND_PATH: dict[NatType, str] = {
    NatType.PORT_FORWARD: "d_nat",
    NatType.OUTBOUND: "source_nat",
    NatType.ONE_TO_ONE: "one_to_one",
}

# Destination NAT still uses the legacy model field `descr`; source NAT and
# one-to-one NAT moved to the Filter model, where the field is `description`.
_NAT_DESCRIPTION_FIELD: dict[NatType, str] = {
    NatType.PORT_FORWARD: "descr",
    NatType.OUTBOUND: "description",
    NatType.ONE_TO_ONE: "description",
}

# Every object OFME owns carries this prefix in its description/descr field. The
# plugin agent already writes ``OFME-``; the legacy ``OFME:`` prefix is still
# recognised so objects created by older releases are adopted instead of
# duplicated and are still pruned when they disappear from the desired state.
_MANAGED_MARKER = "OFME-"
_LEGACY_MARKER = "OFME:"
_MANAGED_PREFIXES = (_MANAGED_MARKER, _LEGACY_MARKER)

# Unbound host overrides express A, AAAA, MX and TXT directly. CNAME records
# are published as host aliases that point at a managed A/AAAA override, which
# yields the same answers (there is no CNAME chain in Unbound's host model).
# PTR, SRV and NS cannot be represented and are reported as skipped.
_UNBOUND_RECORD_TYPES = frozenset({"A", "AAAA", "MX", "TXT"})


def managed_description(name: str) -> str:
    """Return the marker-prefixed description written to the appliance."""
    return f"{_MANAGED_MARKER}{name}"


def is_managed_description(value: Any) -> bool:
    """True when the appliance object was created by OFME (any marker era)."""
    return str(value or "").strip().startswith(_MANAGED_PREFIXES)


def _legacy_description(name: str) -> str:
    return f"{_LEGACY_MARKER} {name}"


def _normalise(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, list | tuple):
        # OPNsense returns some list-valued model fields either as a list or as
        # a comma-separated string depending on the endpoint; compare both forms.
        return ",".join(_normalise(item) for item in value)
    if value is None:
        return ""
    return str(value).strip()


def needs_update(existing: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Compare only the fields the appliance actually returns for an object.

    Fields missing from the live row are ignored, so a sparse API response can
    never cause a rewrite on every apply. Nested option dictionaries are
    compared key by key for the same reason. This is what makes a second apply
    a no-op (created = updated = deleted = 0).
    """

    def _matches(current: Any, wanted: Any) -> bool:
        if isinstance(wanted, dict):
            if not isinstance(current, dict):
                return False
            return all(key not in current or _matches(current[key], value) for key, value in wanted.items())
        return _normalise(current) == _normalise(wanted)

    return any(field in existing and not _matches(existing[field], value) for field, value in payload.items())


def rule_payload(rule: FirewallRule) -> dict[str, Any]:
    """Translate a stored firewall rule into the OPNsense filter rule body."""

    def _address(value: str) -> str:
        return "" if value in {"any", ""} else value

    return {
        "enabled": "1" if rule.enabled else "0",
        "action": rule.action.value,
        "direction": rule.direction.value,
        "interface": rule.interface or "wan",
        "ipprotocol": "inet",
        "protocol": rule.protocol,
        "source_net": _address(rule.source),
        "destination_net": _address(rule.destination),
        "destination_port": rule.destination_port or "",
        "source_port": rule.source_port or "",
        "description": managed_description(rule.name),
        "log": "1" if rule.log else "0",
        "sequence": str(rule.order_index),
    }


def nat_payload(rule: NatRule) -> dict[str, Any]:
    """Translate a stored NAT rule into the OPNsense NAT rule body."""
    enabled = "1" if rule.enabled else "0"
    descr = managed_description(rule.name)
    if rule.type == NatType.PORT_FORWARD:
        return {
            "enabled": enabled,
            "interface": rule.interface,
            "protocol": rule.protocol,
            "src": "" if rule.source in {"any", ""} else rule.source,
            "dst": "" if rule.destination in {"any", ""} else rule.destination,
            "dstport": rule.destination_port or "",
            "target": rule.target,
            "local-port": rule.target_port or "",
            "descr": descr,
            "natreflection": "disable",
            "log": "0",
        }
    if rule.type == NatType.OUTBOUND:
        # Source NAT uses the modern Filter model (`snatrules.rule`).
        return {
            "enabled": enabled,
            "interface": rule.interface,
            "ipprotocol": "inet",
            "protocol": rule.protocol,
            "source_net": rule.source or "any",
            "source_port": "",
            "destination_net": rule.destination or "any",
            "destination_port": rule.destination_port or "",
            "target": rule.target,
            "target_port": rule.target_port or "",
            "description": descr,
            "log": "0",
            "sequence": str(rule.order_index),
        }
    # One-to-one NAT maps an internal network onto an external address.
    return {
        "enabled": enabled,
        "interface": rule.interface,
        "type": "binat",
        "source_net": rule.source,
        "destination_net": rule.destination or "any",
        "external": rule.target,
        "natreflection": "disable",
        "description": descr,
    }


def vlan_payload(vlan: VlanConfig) -> dict[str, Any]:
    """Translate a stored VLAN into the OPNsense VLAN settings body."""
    description = vlan.description or f"{vlan.parent_interface}.{vlan.vlan_id}"
    return {
        "enabled": "1" if vlan.enabled else "0",
        "if": vlan.parent_interface,
        "tag": str(vlan.vlan_id),
        "pcp": "0",
        "descr": managed_description(description),
    }


def dhcp_subnet_payload(scope: DhcpScope) -> dict[str, Any]:
    """Translate a stored DHCP scope into a Kea DHCPv4 subnet body."""
    option_data: dict[str, str] = {}
    if scope.dns_servers:
        # OPNsense stores list-valued option fields as comma-separated strings.
        option_data["domain_name_servers"] = ",".join(scope.dns_servers)
    if scope.gateway:
        option_data["routers"] = scope.gateway
    if scope.domain_name:
        option_data["domain_name"] = scope.domain_name
    return {
        "subnet": scope.subnet,
        "pools": f"{scope.pool_start}-{scope.pool_end}",
        "valid_lifetime": str(scope.lease_time_seconds),
        "option_data": option_data,
        # Explicit option data must win over Kea's interface autocollect.
        "option_data_autocollect": "0" if option_data else "1",
        "description": managed_description(scope.name),
    }


def dhcp_reservation_payload(reservation: DhcpReservation, subnet_uuid: str) -> dict[str, Any]:
    """Translate a stored reservation into a Kea DHCPv4 reservation body."""
    return {
        "subnet": subnet_uuid,
        "ip_address": reservation.ip_address,
        "hw_address": reservation.mac_address,
        "hostname": reservation.hostname,
        "description": managed_description(reservation.hostname),
    }


def dns_override_payload(record: DnsRecord) -> tuple[dict[str, Any] | None, str | None]:
    """Translate a DNS record into an Unbound host override.

    Returns ``(payload, None)`` when the record can be expressed, or
    ``(None, reason)`` when Unbound cannot represent it.
    """
    record_type = (
        record.record_type.value if isinstance(record.record_type, DnsRecordType) else str(record.record_type)
    )
    if record_type not in _UNBOUND_RECORD_TYPES:
        return None, f"{record.name} {record_type}: Unbound host overrides support A, AAAA, MX and TXT only"
    name = record.name.strip().rstrip(".").lower()
    if name in {"", "@"} or "." not in name:
        return None, f"{record.name}: Unbound host overrides require a fully qualified name (host.domain.tld)"
    hostname, domain = name.split(".", 1)
    payload: dict[str, Any] = {
        "enabled": "1" if record.enabled else "0",
        "hostname": hostname,
        "domain": domain,
        "rr": record_type,
        "ttl": str(record.ttl),
        "addptr": "1",
        "description": managed_description(name),
    }
    if record.record_type == DnsRecordType.MX:
        payload["mx"] = record.value.strip().rstrip(".")
        payload["mxprio"] = str(record.priority if record.priority is not None else 10)
    elif record.record_type == DnsRecordType.TXT:
        payload["txtdata"] = record.value
    else:
        payload["server"] = record.value.strip()
    return payload, None


def _dns_record_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """Identify a host override by owner name, type and data (not by UUID)."""
    record_type = _normalise(row.get("rr")).upper()
    if record_type == "MX":
        data = _normalise(row.get("mx")).rstrip(".").lower()
    elif record_type == "TXT":
        data = _normalise(row.get("txtdata"))
    else:
        data = _normalise(row.get("server"))
    return (
        _normalise(row.get("hostname")).lower(),
        _normalise(row.get("domain")).lower(),
        record_type,
        data,
    )


def dns_alias_payload(record: DnsRecord, host_uuid: str) -> dict[str, Any]:
    """Express a CNAME as an Unbound host alias for a managed override.

    Unbound's host-override model has no CNAME type. A host alias on the
    override of the target A/AAAA record returns the same address, which is
    what a CNAME resolves to for clients.
    """
    name = record.name.strip().rstrip(".").lower()
    hostname, domain = name.split(".", 1)
    return {
        "enabled": "1" if record.enabled else "0",
        "host": host_uuid,
        "hostname": hostname,
        "domain": domain,
        "description": managed_description(name),
    }


def _dns_alias_key(row: dict[str, Any]) -> tuple[str, str]:
    """Identify a host alias by the owner name it publishes."""
    return (
        _normalise(row.get("hostname")).lower(),
        _normalise(row.get("domain")).lower(),
    )


class AliasService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, payload: AliasCreate) -> Alias:
        self._validate(payload.type, payload.content)
        alias = Alias(
            tenant_id=self.tenant_id,
            device_id=payload.device_id,
            name=payload.name,
            description=payload.description,
            type=payload.type,
            content=payload.content,
            enabled=payload.enabled,
        )
        self.session.add(alias)
        await self.session.flush()
        await self.audit.record(
            action="alias.created",
            resource_type="Alias",
            resource_id=alias.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": alias.name, "type": alias.type.value, "entries": len(alias.content)},
        )
        return alias

    async def update(self, alias_id: uuid.UUID, payload: AliasUpdate) -> Alias:
        alias = await self.uow.aliases.get_or_404(alias_id)
        if payload.content is not None:
            self._validate(alias.type, payload.content)
            alias.content = payload.content
        if payload.description is not None:
            alias.description = payload.description
        if payload.enabled is not None:
            alias.enabled = payload.enabled
        await self.session.flush()
        await self.audit.record(
            action="alias.updated",
            resource_type="Alias",
            resource_id=alias.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after=payload.model_dump(exclude_unset=True),
        )
        return alias

    @staticmethod
    def _validate(alias_type: AliasType, content: list[str]) -> None:
        for entry in content:
            if alias_type == AliasType.HOST:
                try:
                    ipaddress.ip_address(entry)
                except ValueError as exc:
                    raise BadRequestError(f"Invalid host '{entry}'") from exc
            elif alias_type == AliasType.NETWORK:
                try:
                    ipaddress.ip_network(entry, strict=False)
                except ValueError as exc:
                    raise BadRequestError(f"Invalid network '{entry}'") from exc
            elif alias_type == AliasType.PORT:
                if not re.fullmatch(r"\d{1,5}(-\d{1,5})?", entry):
                    raise BadRequestError(f"Invalid port specification '{entry}'")
            elif alias_type == AliasType.MAC and not re.fullmatch(
                r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", entry
            ):
                raise BadRequestError(f"Invalid MAC address '{entry}'")


class NatService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, payload: NatCreate) -> NatRule:
        nat = NatRule(tenant_id=self.tenant_id, created_by=self.actor_id, **payload.model_dump())
        self.session.add(nat)
        await self.session.flush()
        await self.audit.record(
            action="nat.created",
            resource_type="NatRule",
            resource_id=nat.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": nat.name, "type": nat.type.value, "target": nat.target},
        )
        return nat

    async def update(self, nat_id: uuid.UUID, payload: NatUpdate) -> NatRule:
        nat = await self.uow.nat.get_or_404(nat_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(nat, field, value)
        await self.session.flush()
        await self.audit.record(
            action="nat.updated",
            resource_type="NatRule",
            resource_id=nat.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after=payload.model_dump(exclude_unset=True),
        )
        return nat

    async def delete(self, nat_id: uuid.UUID) -> None:
        nat = await self.uow.nat.get_or_404(nat_id)
        await self.uow.nat.delete(nat)
        await self.audit.record(
            action="nat.deleted",
            resource_type="NatRule",
            resource_id=nat.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
        )


class InterfaceService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def create(self, payload: InterfaceCreate) -> InterfaceConfig:
        interface = InterfaceConfig(tenant_id=self.tenant_id, **payload.model_dump())
        self.session.add(interface)
        await self.session.flush()
        await self.audit.record(
            action="interface.created",
            resource_type="InterfaceConfig",
            resource_id=interface.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": interface.name, "device_id": str(interface.device_id)},
        )
        return interface


class RouteService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id

    async def create(self, payload: RouteCreate) -> RouteConfig:
        try:
            ipaddress.ip_network(payload.network, strict=False)
        except ValueError as exc:
            raise BadRequestError(f"Invalid destination network '{payload.network}'") from exc
        try:
            ipaddress.ip_address(payload.gateway)
        except ValueError as exc:
            raise BadRequestError(f"Invalid gateway '{payload.gateway}'") from exc
        route = RouteConfig(tenant_id=self.tenant_id, **payload.model_dump())
        self.session.add(route)
        await self.session.flush()
        return route


class VlanService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id

    async def create(self, payload: VlanCreate) -> VlanConfig:
        vlan = VlanConfig(tenant_id=self.tenant_id, **payload.model_dump())
        self.session.add(vlan)
        await self.session.flush()
        return vlan


class ConfigurationDeployer:
    """Push desired state for a device to the OPNsense REST API.

    Every deploy method is idempotent: objects are matched against the live
    configuration by their natural key (rule name, NAT description, VLAN
    tag, DHCP subnet/pool, DNS owner name), only genuinely changed objects are
    rewritten, and objects carrying the ``OFME-`` marker that no longer exist
    in the database are pruned. A second identical apply therefore reports
    ``created = updated = deleted = 0`` and does not reload the service.
    """

    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.devices = DeviceService(session, tenant_id, actor_id)
        self.audit = AuditService(session)

    async def _audit_apply(
        self, action: str, device_id: uuid.UUID, counts: dict[str, Any], skipped: list[Any] | None = None
    ) -> None:
        await self.audit.record(
            action=action,
            resource_type="Device",
            resource_id=device_id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={**counts, "skipped": skipped or []},
        )
        await self.session.commit()

    # ------------------------------------------------------------------ firewall
    async def deploy_rules(
        self, device_id: uuid.UUID, *, dry_run: bool = False, apply: bool = True
    ) -> dict[str, Any]:
        """Push every stored firewall rule and prune stale OFME rules."""
        device = await self.devices.get(device_id)
        rules = await self.uow.rules.for_device(device_id)
        payloads = [rule_payload(rule) for rule in rules]

        if dry_run:
            return {"device_id": str(device_id), "rules": payloads, "applied": False}

        base_url, key, secret = await self.devices.credentials(device)
        created = updated = deleted = 0
        async with client_for(base_url, key, secret) as client:
            current = await client.search_rules()
            existing = {
                str(row.get("description")): row
                for row in (current.get("rows") or [])
                if isinstance(row, dict) and row.get("description") and row.get("uuid")
            }
            for rule, payload in zip(rules, payloads, strict=True):
                row = existing.pop(payload["description"], None)
                if row is None:
                    # Adopt rules written by older releases without a marker.
                    row = existing.pop(rule.name, None)
                if row and row.get("uuid"):
                    if needs_update(row, payload):
                        await client.set_rule(str(row["uuid"]), payload)
                        updated += 1
                else:
                    await client.add_rule(payload)
                    created += 1
            for description, row in existing.items():
                if is_managed_description(description) and row.get("uuid"):
                    await client.delete_rule(str(row["uuid"]))
                    deleted += 1
            if apply and (created or updated or deleted):
                await client.apply_rules()

        counts = {"created": created, "updated": updated, "deleted": deleted}
        await self._audit_apply("config.deployed", device_id, counts)
        return {"device_id": str(device_id), **counts, "applied": apply}

    # ------------------------------------------------------------------ NAT
    async def deploy_nat(
        self, device_id: uuid.UUID, *, dry_run: bool = False, apply: bool = True
    ) -> dict[str, Any]:
        """Push every stored NAT rule of a device, grouped by NAT kind."""
        device = await self.devices.get(device_id)
        rules = await self.uow.nat.for_device(device_id)
        grouped: dict[NatType, list[NatRule]] = {}
        for rule in rules:
            grouped.setdefault(rule.type, []).append(rule)

        if dry_run:
            return {
                "device_id": str(device_id),
                "rules": {
                    kind.value: [nat_payload(rule) for rule in grouped.get(kind, [])] for kind in NatType
                },
                "applied": False,
            }

        base_url, key, secret = await self.devices.credentials(device)
        created = updated = deleted = 0
        async with client_for(base_url, key, secret) as client:
            for kind in NatType:
                controller = NAT_KIND_PATH[kind]
                field = _NAT_DESCRIPTION_FIELD[kind]
                current = await client.search_nat(controller)
                existing = {
                    str(row.get(field)): row
                    for row in (current.get("rows") or [])
                    if isinstance(row, dict) and row.get(field) and row.get("uuid")
                }
                kind_changed = False
                for rule in grouped.get(kind, []):
                    payload = nat_payload(rule)
                    row = existing.pop(payload[field], None)
                    if row is None:
                        row = existing.pop(_legacy_description(rule.name), None)
                    if row is None:
                        # Adopt rules created before the marker was introduced.
                        row = existing.pop(rule.name, None)
                    if row and row.get("uuid"):
                        if needs_update(row, payload):
                            await client.set_nat_rule(controller, str(row["uuid"]), payload)
                            updated += 1
                            kind_changed = True
                    else:
                        await client.add_nat_rule(controller, payload)
                        created += 1
                        kind_changed = True
                for descr, row in existing.items():
                    if is_managed_description(descr) and row.get("uuid"):
                        await client.delete_nat_rule(controller, str(row["uuid"]))
                        deleted += 1
                        kind_changed = True
                if apply and kind_changed:
                    await client.apply_nat(controller)

        counts = {"created": created, "updated": updated, "deleted": deleted}
        await self._audit_apply("nat.applied", device_id, counts)
        return {"device_id": str(device_id), **counts, "applied": apply}

    # ------------------------------------------------------------------ VLAN
    async def deploy_vlans(
        self, device_id: uuid.UUID, *, dry_run: bool = False, apply: bool = True
    ) -> dict[str, Any]:
        """Push every stored VLAN of a device and prune stale OFME VLANs."""
        device = await self.devices.get(device_id)
        vlans = await self.uow.vlans.for_device(device_id)

        if dry_run:
            return {
                "device_id": str(device_id),
                "vlans": [vlan_payload(vlan) for vlan in vlans],
                "applied": False,
            }

        base_url, key, secret = await self.devices.credentials(device)
        created = updated = deleted = 0
        async with client_for(base_url, key, secret) as client:
            current = await client.search_vlans()
            existing = {
                f"{row.get('if')}:{row.get('tag')}": row
                for row in (current.get("rows") or [])
                if isinstance(row, dict)
            }
            for vlan in vlans:
                key = f"{vlan.parent_interface}:{vlan.vlan_id}"
                payload = vlan_payload(vlan)
                row = existing.pop(key, None)
                if row and row.get("uuid"):
                    if needs_update(row, payload):
                        await client.set_vlan(str(row["uuid"]), payload)
                        updated += 1
                else:
                    await client.add_vlan(payload)
                    created += 1
            for row in existing.values():
                if is_managed_description(row.get("descr")) and row.get("uuid"):
                    await client.delete_vlan(str(row["uuid"]))
                    deleted += 1
            if apply and (created or updated or deleted):
                await client.apply_interfaces()

        counts = {"created": created, "updated": updated, "deleted": deleted}
        await self._audit_apply("vlan.applied", device_id, counts)
        return {"device_id": str(device_id), **counts, "applied": apply}

    # ------------------------------------------------------------------ DHCP
    async def deploy_dhcp(
        self, device_id: uuid.UUID, *, dry_run: bool = False, apply: bool = True
    ) -> dict[str, Any]:
        """Push DHCP scopes and reservations to Kea DHCPv4 and prune stale ones."""
        device = await self.devices.get(device_id)
        scopes = await self.uow.dhcp_scopes.for_device(device_id)
        reservations: dict[uuid.UUID, list[DhcpReservation]] = {
            scope.id: await self.uow.dhcp_reservations.for_scope(scope.id) for scope in scopes
        }
        enabled_scopes = [scope for scope in scopes if scope.enabled]
        skipped: list[dict[str, str]] = [
            {"name": scope.name, "reason": "scope is disabled"} for scope in scopes if not scope.enabled
        ]
        for scope in enabled_scopes:
            for reservation in reservations[scope.id]:
                if not reservation.enabled:
                    skipped.append(
                        {
                            "name": f"{scope.name}/{reservation.hostname}",
                            "reason": "reservation is disabled",
                        }
                    )

        if dry_run:
            return {
                "device_id": str(device_id),
                "subnets": [dhcp_subnet_payload(scope) for scope in enabled_scopes],
                "reservations": [
                    {
                        "scope": scope.name,
                        "ip_address": reservation.ip_address,
                        "hw_address": reservation.mac_address,
                        "hostname": reservation.hostname,
                        "description": managed_description(reservation.hostname),
                    }
                    for scope in enabled_scopes
                    for reservation in reservations[scope.id]
                    if reservation.enabled
                ],
                "skipped": skipped,
                "applied": False,
            }

        base_url, key, secret = await self.devices.credentials(device)
        created = updated = deleted = 0
        res_created = res_updated = res_deleted = 0
        async with client_for(base_url, key, secret) as client:
            current = await client.search_kea_subnets()
            existing = {
                str(row.get("subnet")): row
                for row in (current.get("rows") or [])
                if isinstance(row, dict) and row.get("subnet") and row.get("uuid")
            }
            for scope in enabled_scopes:
                payload = dhcp_subnet_payload(scope)
                row = existing.pop(payload["subnet"], None)
                if row and row.get("uuid"):
                    if needs_update(row, payload):
                        await client.set_kea_subnet(str(row["uuid"]), payload)
                        updated += 1
                else:
                    await client.add_kea_subnet(payload)
                    created += 1
            for row in existing.values():
                if is_managed_description(row.get("description")) and row.get("uuid"):
                    await client.delete_kea_subnet(str(row["uuid"]))
                    deleted += 1

            # Reservations reference the subnet UUID assigned by the appliance,
            # so the subnet list has to be read back after the upsert phase.
            refreshed = await client.search_kea_subnets()
            subnet_uuids: dict[str, str] = {
                str(row.get("subnet")): str(row.get("uuid"))
                for row in (refreshed.get("rows") or [])
                if isinstance(row, dict) and row.get("subnet") and row.get("uuid")
            }

            current_reservations = await client.search_kea_reservations()
            existing_reservations = {
                (str(row.get("subnet")), str(row.get("hw_address")).lower()): row
                for row in (current_reservations.get("rows") or [])
                if isinstance(row, dict) and row.get("subnet") and row.get("hw_address") and row.get("uuid")
            }
            for scope in enabled_scopes:
                subnet_uuid = subnet_uuids.get(scope.subnet)
                if not subnet_uuid:
                    skipped.append({"name": scope.name, "reason": "subnet was not accepted by Kea"})
                    continue
                for reservation in reservations[scope.id]:
                    if not reservation.enabled:
                        continue
                    payload = dhcp_reservation_payload(reservation, subnet_uuid)
                    key_row = (subnet_uuid, reservation.mac_address.lower())
                    row = existing_reservations.pop(key_row, None)
                    if row and row.get("uuid"):
                        if needs_update(row, payload):
                            await client.set_kea_reservation(str(row["uuid"]), payload)
                            res_updated += 1
                    else:
                        await client.add_kea_reservation(payload)
                        res_created += 1
            for row in existing_reservations.values():
                # Every managed reservation is ours, including the ones whose
                # parent subnet was just pruned, so orphaned entries go too.
                if is_managed_description(row.get("description")) and row.get("uuid"):
                    await client.delete_kea_reservation(str(row["uuid"]))
                    res_deleted += 1

            changed = created or updated or deleted or res_created or res_updated or res_deleted
            if apply and changed:
                await client.apply_kea()

        counts = {
            "created": created + res_created,
            "updated": updated + res_updated,
            "deleted": deleted + res_deleted,
            "subnets": {"created": created, "updated": updated, "deleted": deleted},
            "reservations": {
                "created": res_created,
                "updated": res_updated,
                "deleted": res_deleted,
            },
        }
        await self._audit_apply("dhcp.applied", device_id, counts, skipped)
        return {
            "device_id": str(device_id),
            **counts,
            "skipped": skipped,
            "applied": apply,
        }

    # ------------------------------------------------------------------ DNS
    async def deploy_dns(
        self, device_id: uuid.UUID, *, dry_run: bool = False, apply: bool = True
    ) -> dict[str, Any]:
        """Push DNS records as Unbound host overrides/aliases and prune stale ones."""
        device = await self.devices.get(device_id)
        records = await self.uow.dns_records.for_device(device_id)
        payloads: list[dict[str, Any]] = []
        cname_records: list[DnsRecord] = []
        skipped: list[dict[str, str]] = []
        for record in records:
            if not record.enabled:
                skipped.append({"name": record.name, "reason": "record is disabled"})
                continue
            if record.record_type == DnsRecordType.CNAME:
                cname_records.append(record)
                continue
            payload, reason = dns_override_payload(record)
            if payload is None:
                skipped.append({"name": record.name, "reason": reason or "unsupported record"})
            else:
                payloads.append(payload)

        # A CNAME is published as an alias of the override that owns the target
        # address. The target must be an A/AAAA record managed on this device.
        targets: dict[str, dict[str, Any]] = {
            f"{payload['hostname']}.{payload['domain']}".lower(): payload
            for payload in payloads
            if payload["rr"] in {"A", "AAAA"}
        }
        alias_plans: list[tuple[DnsRecord, dict[str, Any]]] = []
        for record in cname_records:
            target = record.value.strip().rstrip(".").lower()
            target_payload = targets.get(target)
            if target_payload is None:
                skipped.append(
                    {
                        "name": record.name,
                        "reason": (f"CNAME target {target} is not a managed A/AAAA record on this device"),
                    }
                )
            else:
                alias_plans.append((record, target_payload))

        if dry_run:
            return {
                "device_id": str(device_id),
                "overrides": payloads,
                "aliases": [{"name": record.name, "target": record.value} for record, _ in alias_plans],
                "skipped": skipped,
                "applied": False,
            }

        base_url, key, secret = await self.devices.credentials(device)
        created = updated = deleted = 0
        async with client_for(base_url, key, secret) as client:
            current = await client.search_unbound_host_overrides()
            existing = {
                _dns_record_key(row): row
                for row in (current.get("rows") or [])
                if isinstance(row, dict) and row.get("uuid")
            }
            for payload in payloads:
                record_key = _dns_record_key(payload)
                row = existing.pop(record_key, None)
                if row and row.get("uuid"):
                    if needs_update(row, payload):
                        await client.set_unbound_host_override(str(row["uuid"]), payload)
                        updated += 1
                else:
                    await client.add_unbound_host_override(payload)
                    created += 1
            for row in existing.values():
                if is_managed_description(row.get("description")) and row.get("uuid"):
                    await client.delete_unbound_host_override(str(row["uuid"]))
                    deleted += 1

            if alias_plans:
                live = {
                    _dns_record_key(row): row
                    for row in ((await client.search_unbound_host_overrides()).get("rows") or [])
                    if isinstance(row, dict) and row.get("uuid")
                }
                aliases_current = await client.search_unbound_host_aliases()
                existing_aliases = {
                    _dns_alias_key(row): row
                    for row in (aliases_current.get("rows") or [])
                    if isinstance(row, dict) and row.get("uuid")
                }
                for record, target_payload in alias_plans:
                    host_row = live.get(_dns_record_key(target_payload))
                    if host_row is None or not host_row.get("uuid"):
                        skipped.append(
                            {
                                "name": record.name,
                                "reason": "target override was not created on the appliance",
                            }
                        )
                        continue
                    payload = dns_alias_payload(record, str(host_row["uuid"]))
                    alias_key = _dns_alias_key(payload)
                    row = existing_aliases.pop(alias_key, None)
                    if row and row.get("uuid"):
                        if needs_update(row, payload):
                            await client.set_unbound_host_alias(str(row["uuid"]), payload)
                            updated += 1
                    else:
                        await client.add_unbound_host_alias(payload)
                        created += 1
                for row in existing_aliases.values():
                    if is_managed_description(row.get("description")) and row.get("uuid"):
                        await client.delete_unbound_host_alias(str(row["uuid"]))
                        deleted += 1

            if apply and (created or updated or deleted):
                await client.apply_unbound()

        counts = {"created": created, "updated": updated, "deleted": deleted}
        await self._audit_apply("dns.applied", device_id, counts, skipped)
        return {
            "device_id": str(device_id),
            **counts,
            "aliases": [record.name for record, _ in alias_plans],
            "skipped": skipped,
            "applied": apply,
        }

    # ------------------------------------------------------------------ unified
    async def apply_resources(
        self,
        device_id: uuid.UUID,
        resources: list[str],
        *,
        dry_run: bool = False,
        apply: bool = True,
    ) -> dict[str, Any]:
        """Run several deployers for one device and collect their outcomes."""
        deployers = {
            "rules": self.deploy_rules,
            "nat": self.deploy_nat,
            "vlans": self.deploy_vlans,
            "dhcp": self.deploy_dhcp,
            "dns": self.deploy_dns,
        }
        unknown = [name for name in resources if name not in deployers]
        if unknown:
            raise BadRequestError(f"Unknown configuration resource(s): {', '.join(unknown)}")
        details: dict[str, Any] = {}
        for name in resources:
            details[name] = await deployers[name](device_id, dry_run=dry_run, apply=apply)
        return {
            "device_id": str(device_id),
            "resources": resources,
            "details": details,
            "applied": apply and not dry_run,
        }
