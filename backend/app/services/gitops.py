"""Policy-as-Code: parsing, validation, linting, compilation, diffing, deployment, drift."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import PolicyDeployed, event_bus
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError, PolicyValidationError
from app.core.logging import get_logger
from app.models.enums import (
    ChangeStatus,
    DeploymentStatus,
    DriftStatus,
    Environment,
    PolicyKind,
    PolicyStatus,
)
from app.models.policy import ChangeRequest, DriftReport, Policy, PolicyDeployment
from app.models.topology import Device
from app.repositories import UnitOfWork
from app.schemas.policies_doc import FirewallPolicySpec, NatPolicyEntry, VlanPolicyEntry, VpnPolicySpec
from app.schemas.policy import (
    PolicyCreate,
    PolicyDiff,
    PolicyDiffEntry,
    PolicySimulationResult,
    PolicyUpdate,
    PolicyValidationIssue,
    PolicyValidationResult,
)
from app.services.audit import AuditService
from app.services.configuration import ConfigurationDeployer
from app.services.devices import DeviceService
from app.services.vpn_policy import VpnPolicyDeployer

log = get_logger("ofme.gitops")

DOC_KINDS = {
    "FirewallPolicy": PolicyKind.FIREWALL,
    "NatPolicy": PolicyKind.NAT,
    "VlanPolicy": PolicyKind.VLAN,
    "VpnPolicy": PolicyKind.VPN,
    "CompliancePolicy": PolicyKind.COMPLIANCE,
}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PolicyValidator:
    """Schema + semantic validation and OPNsense compilation."""

    def validate(self, content: str, kind: PolicyKind | None = None) -> PolicyValidationResult:
        errors: list[PolicyValidationIssue] = []
        warnings: list[PolicyValidationIssue] = []
        compiled: dict[str, Any] = {}
        rule_count = 0
        conflict_count = 0

        try:
            documents = [doc for doc in yaml.safe_load_all(content) if doc is not None]
        except yaml.YAMLError as exc:
            return PolicyValidationResult(
                valid=False,
                errors=[
                    PolicyValidationIssue(
                        code="yaml_syntax",
                        message=f"YAML syntax error: {exc}",
                        line=getattr(getattr(exc, "problem_mark", None), "line", None),
                    )
                ],
            )

        if not documents:
            return PolicyValidationResult(
                valid=False,
                errors=[PolicyValidationIssue(code="empty_document", message="Policy document is empty")],
            )

        for index, document in enumerate(documents):
            if not isinstance(document, dict):
                errors.append(
                    PolicyValidationIssue(
                        code="invalid_document", message=f"Document #{index} is not a mapping"
                    )
                )
                continue

            api_version = document.get("apiVersion")
            doc_kind = document.get("kind")
            metadata = document.get("metadata") or {}
            spec = document.get("spec")

            if api_version != "fleet.opnsense.io/v1":
                errors.append(
                    PolicyValidationIssue(
                        code="unsupported_api_version",
                        message=f"Unsupported apiVersion '{api_version}' (expected fleet.opnsense.io/v1)",
                        path=f"documents[{index}].apiVersion",
                    )
                )
            if doc_kind not in DOC_KINDS:
                errors.append(
                    PolicyValidationIssue(
                        code="unsupported_kind",
                        message=f"Unsupported kind '{doc_kind}'",
                        path=f"documents[{index}].kind",
                    )
                )
                continue
            if not isinstance(metadata, dict) or not metadata.get("name"):
                errors.append(
                    PolicyValidationIssue(
                        code="missing_name",
                        message="metadata.name is required",
                        path=f"documents[{index}].metadata",
                    )
                )
            if not isinstance(spec, dict):
                errors.append(
                    PolicyValidationIssue(
                        code="missing_spec", message="spec must be a mapping", path=f"documents[{index}].spec"
                    )
                )
                continue

            if doc_kind == "FirewallPolicy":
                result = self._validate_firewall(spec, index)
                errors.extend(result["errors"])
                warnings.extend(result["warnings"])
                rule_count += result["rule_count"]
                conflict_count += result["conflicts"]
                compiled["firewall"] = result["compiled"]
            elif doc_kind == "NatPolicy":
                result = self._validate_nat(spec, index)
                errors.extend(result["errors"])
                compiled["nat"] = result["compiled"]
            elif doc_kind == "VlanPolicy":
                result = self._validate_vlan(spec, index)
                errors.extend(result["errors"])
                compiled["vlan"] = result["compiled"]
            elif doc_kind == "VpnPolicy":
                result = self._validate_vpn(spec, index)
                errors.extend(result["errors"])
                compiled["vpn"] = result["compiled"]

        if kind and kind not in {
            DOC_KINDS[doc.get("kind")]
            for doc in documents
            if isinstance(doc, dict) and doc.get("kind") in DOC_KINDS
        }:
            warnings.append(
                PolicyValidationIssue(
                    code="kind_mismatch",
                    message=f"Policy record is '{kind.value}' but document kind differs",
                )
            )

        return PolicyValidationResult(
            valid=not errors,
            errors=errors,
            warnings=warnings,
            rule_count=rule_count,
            conflict_count=conflict_count,
            compiled=compiled,
        )

    # ------------------------------------------------------------------ per-kind
    def _validate_firewall(self, spec: dict[str, Any], index: int) -> dict[str, Any]:
        errors: list[PolicyValidationIssue] = []
        warnings: list[PolicyValidationIssue] = []
        try:
            parsed = FirewallPolicySpec.model_validate(spec)
        except PydanticValidationError as exc:
            for error in exc.errors():
                errors.append(
                    PolicyValidationIssue(
                        code="schema_error",
                        message=error["msg"],
                        path=f"documents[{index}].spec.{'.'.join(str(p) for p in error['loc'])}",
                    )
                )
            return {"errors": errors, "warnings": warnings, "rule_count": 0, "conflicts": 0, "compiled": {}}

        seen: set[str] = set()
        compiled_rules: list[dict[str, Any]] = []
        for position, rule in enumerate(parsed.rules):
            if rule.name in seen:
                errors.append(
                    PolicyValidationIssue(
                        code="duplicate_rule",
                        message=f"Duplicate rule name '{rule.name}'",
                        path=f"spec.rules[{position}].name",
                    )
                )
            seen.add(rule.name)

            if rule.action == "pass" and rule.source == "any" and rule.destination == "any":
                if not rule.description:
                    errors.append(
                        PolicyValidationIssue(
                            code="permit_any_without_justification",
                            message=f"Rule '{rule.name}' permits any/any without a description",
                            path=f"spec.rules[{position}]",
                            remediation="Restrict source/destination or document the exception",
                        )
                    )
                else:
                    warnings.append(
                        PolicyValidationIssue(
                            code="permit_any",
                            severity="warning",
                            message=f"Rule '{rule.name}' permits any/any",
                            path=f"spec.rules[{position}]",
                        )
                    )
            if rule.protocol == "tcp" and not rule.destination_port:
                warnings.append(
                    PolicyValidationIssue(
                        severity="warning",
                        code="tcp_without_port",
                        message=f"TCP rule '{rule.name}' has no destination port",
                        path=f"spec.rules[{position}]",
                    )
                )
            compiled_rules.append(
                {
                    "enabled": "1",
                    "action": rule.action,
                    "direction": rule.direction,
                    "interface": rule.interface or "wan",
                    "protocol": rule.protocol,
                    "source_net": "" if rule.source == "any" else rule.source,
                    "destination_net": "" if rule.destination == "any" else rule.destination,
                    "destination_port": str(rule.destination_port or ""),
                    "source_port": str(rule.source_port or ""),
                    "descr": rule.description or rule.name,
                    "log": "1" if rule.log else "0",
                    "sequence": str((position + 1) * 10),
                }
            )

        conflicts = 0
        conn = [r for r in parsed.rules if r.action == "pass"]
        for i, left in enumerate(conn):
            for right in conn[i + 1 :]:
                if (
                    left.interface == right.interface
                    and left.protocol == right.protocol
                    and left.source == right.source
                    and left.destination == right.destination
                ):
                    warnings.append(
                        PolicyValidationIssue(
                            severity="warning",
                            code="duplicate_effective_rule",
                            message=f"Rules '{left.name}' and '{right.name}' overlap completely",
                        )
                    )
                    conflicts += 1

        return {
            "errors": errors,
            "warnings": warnings,
            "rule_count": len(parsed.rules),
            "conflicts": conflicts,
            "compiled": compiled_rules,
        }

    def _validate_nat(self, spec: dict[str, Any], index: int) -> dict[str, Any]:
        errors: list[PolicyValidationIssue] = []
        entries = spec.get("port_forwards") or spec.get("rules") or []
        compiled: list[dict[str, Any]] = []
        for position, entry in enumerate(entries):
            try:
                parsed = NatPolicyEntry.model_validate(entry)
            except PydanticValidationError as exc:
                errors.append(
                    PolicyValidationIssue(
                        code="schema_error",
                        message=str(exc.errors()[0]["msg"]),
                        path=f"documents[{index}].spec.rules[{position}]",
                    )
                )
                continue
            compiled.append(parsed.model_dump())
        return {"errors": errors, "compiled": compiled}

    def _validate_vlan(self, spec: dict[str, Any], index: int) -> dict[str, Any]:
        errors: list[PolicyValidationIssue] = []
        entries = spec.get("vlans") or []
        for position, entry in enumerate(entries):
            try:
                VlanPolicyEntry.model_validate(entry)
            except PydanticValidationError as exc:
                errors.append(
                    PolicyValidationIssue(
                        code="schema_error",
                        message=str(exc.errors()[0]["msg"]),
                        path=f"documents[{index}].spec.vlans[{position}]",
                    )
                )
        return {"errors": errors, "compiled": entries}

    def _validate_vpn(self, spec: dict[str, Any], index: int) -> dict[str, Any]:
        errors: list[PolicyValidationIssue] = []
        try:
            parsed = VpnPolicySpec.model_validate(spec)
        except PydanticValidationError as exc:
            errors.append(
                PolicyValidationIssue(
                    code="schema_error", message=str(exc.errors()[0]["msg"]), path=f"documents[{index}].spec"
                )
            )
            return {"errors": errors, "compiled": {}}
        keys = [peer.public_key for peer in parsed.peers if peer.public_key]
        if len(keys) != len(set(keys)):
            errors.append(
                PolicyValidationIssue(
                    code="duplicate_peer_key", message="Duplicate WireGuard public keys in peer list"
                )
            )
        return {"errors": errors, "compiled": parsed.model_dump()}


class PolicyService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)
        self.validator = PolicyValidator()

    async def create(self, payload: PolicyCreate) -> Policy:
        existing = await self.session.execute(
            select(Policy).where(
                Policy.tenant_id == self.tenant_id,
                Policy.name == payload.name,
                Policy.environment == payload.environment,
            )
        )
        if existing.scalars().first():
            raise ConflictError(f"Policy '{payload.name}' already exists in {payload.environment.value}")

        policy = Policy(
            tenant_id=self.tenant_id,
            repo_id=payload.repo_id,
            name=payload.name,
            kind=payload.kind,
            environment=payload.environment,
            path=payload.path,
            content=payload.content,
            content_hash=content_hash(payload.content),
            description=payload.description,
            target_selector=payload.target_selector,
            created_by=self.actor_id,
        )
        self.session.add(policy)
        await self.session.flush()
        await self.audit.record(
            action="policy.created",
            resource_type="Policy",
            resource_id=policy.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": policy.name, "kind": policy.kind.value, "environment": policy.environment.value},
        )
        return policy

    async def update(self, policy_id: uuid.UUID, payload: PolicyUpdate) -> Policy:
        policy = await self.uow.policies.get_or_404(policy_id)
        before = {"status": policy.status.value, "content_hash": policy.content_hash}
        if payload.content is not None:
            policy.content = payload.content
            policy.content_hash = content_hash(payload.content)
            policy.version += 1
            policy.status = PolicyStatus.DRAFT
            policy.validation_errors = []
        if payload.description is not None:
            policy.description = payload.description
        if payload.target_selector is not None:
            policy.target_selector = payload.target_selector
        if payload.status is not None:
            self._assert_transition(policy.status, payload.status)
            policy.status = payload.status
        await self.session.flush()
        await self.audit.record(
            action="policy.updated",
            resource_type="Policy",
            resource_id=policy.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before=before,
            after={
                "status": policy.status.value,
                "content_hash": policy.content_hash,
                "version": policy.version,
            },
        )
        return policy

    @staticmethod
    def _assert_transition(current: PolicyStatus, target: PolicyStatus) -> None:
        allowed: dict[PolicyStatus, set[PolicyStatus]] = {
            PolicyStatus.DRAFT: {PolicyStatus.VALIDATED, PolicyStatus.ARCHIVED},
            PolicyStatus.VALIDATED: {PolicyStatus.REVIEW, PolicyStatus.APPROVED, PolicyStatus.ARCHIVED},
            PolicyStatus.REVIEW: {PolicyStatus.APPROVED, PolicyStatus.DRAFT, PolicyStatus.ARCHIVED},
            PolicyStatus.APPROVED: {PolicyStatus.DEPLOYED, PolicyStatus.ARCHIVED},
            PolicyStatus.DEPLOYED: {PolicyStatus.DRAFT, PolicyStatus.ARCHIVED},
            PolicyStatus.ARCHIVED: set(),
        }
        if target not in allowed.get(current, set()):
            raise BadRequestError(f"Illegal policy transition {current.value} -> {target.value}")

    async def validate(self, policy_id: uuid.UUID) -> PolicyValidationResult:
        policy = await self.uow.policies.get_or_404(policy_id)
        result = self.validator.validate(policy.content, policy.kind)
        policy.validation_errors = [issue.model_dump() for issue in result.errors]
        policy.validated_at = datetime.now(UTC)
        policy.status = PolicyStatus.VALIDATED if result.valid else PolicyStatus.DRAFT
        await self.session.flush()
        await self.audit.record(
            action="policy.validated",
            resource_type="Policy",
            resource_id=policy.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"valid": result.valid, "errors": len(result.errors), "warnings": len(result.warnings)},
        )
        return result

    async def diff(self, policy_id: uuid.UUID, against_content: str | None = None) -> PolicyDiff:
        policy = await self.uow.policies.get_or_404(policy_id)
        base = against_content if against_content is not None else ""
        return DiffEngine.compare(policy.id, 0, policy.version, base, policy.content)

    async def simulate(
        self,
        policy_id: uuid.UUID,
        *,
        source_ip: str,
        destination_ip: str,
        protocol: str = "tcp",
        destination_port: int | None = None,
        interface: str | None = None,
    ) -> PolicySimulationResult:
        policy = await self.uow.policies.get_or_404(policy_id)
        try:
            documents = list(yaml.safe_load_all(policy.content))
        except yaml.YAMLError as exc:
            raise PolicyValidationError(f"Policy YAML invalid: {exc}") from exc
        rules: list[dict[str, Any]] = []
        for document in documents:
            if isinstance(document, dict) and document.get("kind") == "FirewallPolicy":
                rules.extend((document.get("spec") or {}).get("rules") or [])

        import ipaddress

        source = ipaddress.ip_address(source_ip)
        destination = ipaddress.ip_address(destination_ip)
        shadowed: list[str] = []
        evaluated = 0
        for position, rule in enumerate(rules):
            evaluated += 1
            if interface and rule.get("interface") not in (None, interface):
                continue
            if rule.get("protocol") not in (None, "any", protocol):
                continue
            if not _addr_match(rule.get("source", "any"), source):
                continue
            if not _addr_match(rule.get("destination", "any"), destination):
                continue
            port = rule.get("destination_port")
            if port and destination_port is not None and not _port_match(str(port), destination_port):
                continue
            if rule.get("action") == "pass":
                shadowed = [r["name"] for r in rules[position + 1 :]]
            return PolicySimulationResult(
                matched=True,
                action=rule.get("action", "block"),
                rule_name=rule.get("name"),
                rule_index=position,
                evaluated=evaluated,
                shadowed_rules=shadowed,
            )
        return PolicySimulationResult(
            matched=False, action="block", rule_name=None, rule_index=None, evaluated=evaluated
        )


def _addr_match(spec: str, address: Any) -> bool:
    import ipaddress

    if spec in {None, "", "any"}:
        return True
    if address.version == 4 and ":" in str(address):
        return False
    try:
        return address in ipaddress.ip_network(str(spec), strict=False)
    except ValueError:
        return False


def _port_match(spec: str, port: int) -> bool:
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, _, end = part.partition("-")
            if start.isdigit() and end.isdigit() and int(start) <= port <= int(end):
                return True
        elif part.isdigit() and int(part) == port:
            return True
    return False


class DiffEngine:
    @staticmethod
    def compare(
        policy_id: uuid.UUID, base_version: int, target_version: int, before: str, after: str
    ) -> PolicyDiff:
        try:
            before_doc = yaml.safe_load(before) if before else {}
            after_doc = yaml.safe_load(after) if after else {}
        except yaml.YAMLError as exc:
            raise PolicyValidationError(f"Unable to parse policy for diff: {exc}") from exc

        entries = DiffEngine._walk("", before_doc, after_doc)
        summary = (
            f"{len(entries)} change(s): "
            f"{sum(1 for e in entries if e.change == 'added')} added, "
            f"{sum(1 for e in entries if e.change == 'removed')} removed, "
            f"{sum(1 for e in entries if e.change == 'modified')} modified"
        )
        return PolicyDiff(
            policy_id=policy_id,
            base_version=base_version,
            target_version=target_version,
            entries=entries,
            summary=summary,
        )

    @staticmethod
    def _walk(path: str, before: Any, after: Any) -> list[PolicyDiffEntry]:
        entries: list[PolicyDiffEntry] = []
        if isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(set(before) | set(after)):
                child = f"{path}.{key}" if path else str(key)
                if key not in before:
                    entries.append(PolicyDiffEntry(path=child, change="added", after=after[key]))
                elif key not in after:
                    entries.append(PolicyDiffEntry(path=child, change="removed", before=before[key]))
                else:
                    entries.extend(DiffEngine._walk(child, before[key], after[key]))
            return entries
        if isinstance(before, list) and isinstance(after, list):
            for index in range(max(len(before), len(after))):
                child = f"{path}[{index}]"
                if index >= len(before):
                    entries.append(PolicyDiffEntry(path=child, change="added", after=after[index]))
                elif index >= len(after):
                    entries.append(PolicyDiffEntry(path=child, change="removed", before=before[index]))
                else:
                    entries.extend(DiffEngine._walk(child, before[index], after[index]))
            return entries
        if before != after:
            entries.append(PolicyDiffEntry(path=path or "$", change="modified", before=before, after=after))
        return entries


class DeploymentService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)
        self.devices = DeviceService(session, tenant_id, actor_id)

    async def _resolve_targets(self, policy: Policy, device_ids: list[uuid.UUID]) -> list[Device]:
        if device_ids:
            devices: list[Device] = []
            for device_id in device_ids:
                devices.append(await self.devices.get(device_id))
            return devices

        selector = policy.target_selector or {}
        query = self.uow.devices.query()
        if selector.get("site_id"):
            query = query.where(Device.site_id == uuid.UUID(str(selector["site_id"])))
        if selector.get("group_id"):
            query = query.where(Device.group_id == uuid.UUID(str(selector["group_id"])))
        devices = list((await self.session.execute(query)).scalars().all())
        if selector.get("tags"):
            required = set(selector["tags"])
            devices = [d for d in devices if required.issubset(set(d.tags or []))]
        if selector.get("all"):
            return devices
        return devices

    async def deploy(
        self,
        policy_id: uuid.UUID,
        *,
        device_ids: list[uuid.UUID],
        dry_run: bool = False,
        change_request_id: uuid.UUID | None = None,
    ) -> PolicyDeployment:
        policy = await self.uow.policies.get_or_404(policy_id)
        validation = PolicyValidator().validate(policy.content, policy.kind)
        if not validation.valid:
            raise PolicyValidationError(
                "Policy failed validation", details=[issue.model_dump() for issue in validation.errors]
            )

        if policy.environment == Environment.PRODUCTION and not dry_run:
            if change_request_id is None:
                raise BadRequestError("Production deployments require an approved change request")
            change = await self.uow.changes.get(change_request_id)
            if change is None or change.status != ChangeStatus.APPROVED:
                raise BadRequestError("Change request is not approved")
            if len(change.approvals) < change.required_approvals:
                raise BadRequestError("Change request lacks required approvals")

        targets = await self._resolve_targets(policy, device_ids)
        before = await self._capture_state(targets, policy.kind)
        if policy.kind == PolicyKind.VPN and not dry_run:
            # VPN policies have no desired-state tables: the appliance objects are
            # derived from the compiled document, so the previous completed
            # deployment is the state to restore on rollback.
            before = await self._vpn_snapshot(policy, targets)
        deployment = PolicyDeployment(
            tenant_id=self.tenant_id,
            policy_id=policy.id,
            environment=policy.environment,
            status=DeploymentStatus.VALIDATING,
            plan={
                "compiled": validation.compiled,
                "targets": [str(d.id) for d in targets],
                "warnings": [w.model_dump() for w in validation.warnings],
                "dry_run": dry_run,
            },
            snapshot={"before": before, "after": {}},
            target_device_ids=[str(d.id) for d in targets],
            triggered_by=self.actor_id,
            approved_by=self.actor_id if change_request_id else None,
            started_at=datetime.now(UTC),
        )
        self.session.add(deployment)
        await self.session.flush()

        results: list[dict[str, Any]] = []
        deployer = ConfigurationDeployer(self.session, self.tenant_id, self.actor_id)
        failures = 0

        if policy.kind == PolicyKind.FIREWALL:
            rules = self._compile_rules(policy, validation.compiled.get("firewall", []))
            if not dry_run:
                await self._persist_rules(policy, targets, rules)
            for device in targets:
                try:
                    if dry_run:
                        results.append({"device_id": str(device.id), "success": True, "dry_run": True})
                        continue
                    outcome = await deployer.deploy_rules(device.id, dry_run=False, apply=True)
                    results.append({"device_id": str(device.id), "success": True, **outcome})
                except Exception as exc:  # noqa: BLE001 - record per-device failure
                    failures += 1
                    results.append({"device_id": str(device.id), "success": False, "error": str(exc)})

        elif policy.kind == PolicyKind.NAT:
            entries = validation.compiled.get("nat", [])
            if not dry_run:
                await self._persist_nat(policy, targets, entries)
            for device in targets:
                try:
                    if dry_run:
                        results.append({"device_id": str(device.id), "success": True, "dry_run": True})
                        continue
                    outcome = await deployer.deploy_nat(device.id, dry_run=False, apply=True)
                    results.append({"device_id": str(device.id), "success": True, **outcome})
                except Exception as exc:  # noqa: BLE001 - record per-device failure
                    failures += 1
                    results.append({"device_id": str(device.id), "success": False, "error": str(exc)})

        elif policy.kind == PolicyKind.VLAN:
            entries = validation.compiled.get("vlan", [])
            if not dry_run:
                await self._persist_vlans(policy, targets, entries)
            for device in targets:
                try:
                    if dry_run:
                        results.append({"device_id": str(device.id), "success": True, "dry_run": True})
                        continue
                    outcome = await deployer.deploy_vlans(device.id, dry_run=False, apply=True)
                    results.append({"device_id": str(device.id), "success": True, **outcome})
                except Exception as exc:  # noqa: BLE001 - record per-device failure
                    failures += 1
                    results.append({"device_id": str(device.id), "success": False, "error": str(exc)})

        elif policy.kind == PolicyKind.VPN:
            spec = validation.compiled.get("vpn") or {}
            vpn_deployer = VpnPolicyDeployer(self.session, self.tenant_id, self.actor_id)
            for device in targets:
                try:
                    outcome = await vpn_deployer.deploy(
                        device.id, spec, policy.name, dry_run=dry_run, apply=not dry_run
                    )
                    results.append({"device_id": str(device.id), "success": True, **outcome})
                except Exception as exc:  # noqa: BLE001 - record per-device failure
                    failures += 1
                    results.append({"device_id": str(device.id), "success": False, "error": str(exc)})

        if not dry_run:
            after = await self._capture_state(targets, policy.kind)
            if policy.kind == PolicyKind.VPN:
                after = self._vpn_state(targets, validation.compiled.get("vpn") or {}, policy.name)
            deployment.snapshot = {"before": before, "after": after}

        deployment.results = results
        deployment.status = DeploymentStatus.COMPLETED if failures == 0 else DeploymentStatus.FAILED
        deployment.completed_at = datetime.now(UTC)
        deployment.logs = json.dumps(results, default=str)[:20000]

        if deployment.status == DeploymentStatus.COMPLETED and not dry_run:
            policy.status = PolicyStatus.DEPLOYED
            if change_request_id:
                change = await self.uow.changes.get(change_request_id)
                if change:
                    change.status = ChangeStatus.APPLIED
                    change.applied_at = datetime.now(UTC)
                    change.applied_by = self.actor_id

        await self.session.flush()
        await self.audit.record(
            action="policy.deployed",
            resource_type="Policy",
            resource_id=policy.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "deployment_id": str(deployment.id),
                "status": deployment.status.value,
                "targets": len(targets),
            },
        )
        await event_bus.publish(
            PolicyDeployed(
                policy_id=str(policy.id),
                deployment_id=str(deployment.id),
                tenant_id=str(self.tenant_id),
                environment=policy.environment.value,
                status=deployment.status.value,
            )
        )
        await self.session.commit()
        return deployment

    def _compile_rules(self, policy: Policy, compiled: list[dict[str, Any]]) -> list[dict[str, Any]]:
        import yaml

        documents = list(yaml.safe_load_all(policy.content))
        rules: list[dict[str, Any]] = []
        for document in documents:
            if isinstance(document, dict) and document.get("kind") == "FirewallPolicy":
                for position, rule in enumerate((document.get("spec") or {}).get("rules") or []):
                    rules.append(
                        {
                            "name": rule.get("name"),
                            "action": rule.get("action", "block"),
                            "direction": rule.get("direction", "in"),
                            "interface": rule.get("interface", "wan"),
                            "protocol": rule.get("protocol", "any"),
                            "source": rule.get("source", "any"),
                            "destination": rule.get("destination", "any"),
                            "destination_port": str(rule.get("destination_port") or "") or None,
                            "source_port": str(rule.get("source_port") or "") or None,
                            "description": rule.get("description"),
                            "log": bool(rule.get("log", False)),
                            "tags": rule.get("tags") or [],
                            "order_index": (position + 1) * 10,
                        }
                    )
        return rules

    async def _persist_rules(
        self, policy: Policy, targets: list[Device], rules: list[dict[str, Any]]
    ) -> None:
        from app.models.config import FirewallRule

        for device in targets:
            # Replace the desired state atomically; soft-deleted rows would still
            # collide with the (device_id, name) unique constraint on re-deploy.
            await self.session.execute(delete(FirewallRule).where(FirewallRule.device_id == device.id))
            for rule in rules:
                self.session.add(
                    FirewallRule(
                        tenant_id=self.tenant_id,
                        device_id=device.id,
                        name=rule["name"],
                        action=rule["action"],
                        direction=rule["direction"],
                        interface=rule["interface"],
                        protocol=rule["protocol"],
                        source=rule["source"],
                        destination=rule["destination"],
                        destination_port=rule["destination_port"],
                        source_port=rule["source_port"],
                        description=rule["description"],
                        log=rule["log"],
                        tags=rule["tags"],
                        order_index=rule["order_index"],
                        source_policy_id=policy.id,
                    )
                )
        await self.session.flush()

    async def _persist_nat(
        self, policy: Policy, targets: list[Device], entries: list[dict[str, Any]]
    ) -> None:
        from app.models.config import NatRule
        from app.models.enums import NatType

        for device in targets:
            await self.session.execute(delete(NatRule).where(NatRule.device_id == device.id))
            for position, entry in enumerate(entries):
                self.session.add(
                    NatRule(
                        tenant_id=self.tenant_id,
                        device_id=device.id,
                        name=entry["name"],
                        type=NatType(entry["type"]),
                        interface=entry.get("interface") or "wan",
                        protocol=entry.get("protocol") or "tcp",
                        source=entry.get("source") or "any",
                        destination=entry.get("destination") or "any",
                        destination_port=str(entry.get("destination_port") or "") or None,
                        target=entry["target"],
                        target_port=str(entry.get("target_port") or "") or None,
                        enabled=True,
                        order_index=(position + 1) * 10,
                    )
                )
        await self.session.flush()

    async def _persist_vlans(
        self, policy: Policy, targets: list[Device], entries: list[dict[str, Any]]
    ) -> None:
        from app.models.config import VlanConfig

        for device in targets:
            await self.session.execute(delete(VlanConfig).where(VlanConfig.device_id == device.id))
            for entry in entries:
                self.session.add(
                    VlanConfig(
                        tenant_id=self.tenant_id,
                        device_id=device.id,
                        vlan_id=int(entry["vlan_id"]),
                        parent_interface=entry["parent_interface"],
                        description=entry.get("description"),
                        enabled=True,
                    )
                )
        await self.session.flush()

    # ------------------------------------------------------------------ snapshots
    def _vpn_state(self, targets: list[Device], spec: dict[str, Any], policy_name: str) -> dict[str, Any]:
        return {str(device.id): {"vpn": spec or None, "policy": policy_name} for device in targets}

    async def _vpn_snapshot(self, policy: Policy, targets: list[Device]) -> dict[str, Any]:
        """Return the VPN spec of the last completed deployment, if any."""
        previous = (
            (
                await self.session.execute(
                    select(PolicyDeployment)
                    .where(
                        PolicyDeployment.policy_id == policy.id,
                        PolicyDeployment.status == DeploymentStatus.COMPLETED,
                    )
                    .order_by(PolicyDeployment.created_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        spec: dict[str, Any] | None = None
        if previous is not None:
            spec = ((previous.plan or {}).get("compiled") or {}).get("vpn") or None
        return self._vpn_state(targets, spec or {}, policy.name)

    async def _capture_state(self, targets: list[Device], kind: PolicyKind) -> dict[str, Any]:
        """Capture the desired state a policy is about to replace."""
        state: dict[str, Any] = {}
        for device in targets:
            entry: dict[str, Any] = {}
            if kind == PolicyKind.FIREWALL:
                entry["rules"] = [
                    self._rule_snapshot(rule) for rule in await self.uow.rules.for_device(device.id)
                ]
            elif kind == PolicyKind.NAT:
                entry["nat"] = [self._nat_snapshot(rule) for rule in await self.uow.nat.for_device(device.id)]
            elif kind == PolicyKind.VLAN:
                entry["vlans"] = [
                    self._vlan_snapshot(vlan) for vlan in await self.uow.vlans.for_device(device.id)
                ]
            state[str(device.id)] = entry
        return state

    @staticmethod
    def _rule_snapshot(rule: Any) -> dict[str, Any]:
        return {
            "name": rule.name,
            "description": rule.description,
            "action": rule.action.value,
            "direction": rule.direction.value,
            "interface": rule.interface,
            "protocol": rule.protocol,
            "source": rule.source,
            "destination": rule.destination,
            "destination_port": rule.destination_port,
            "source_port": rule.source_port,
            "gateway": rule.gateway,
            "log": rule.log,
            "enabled": rule.enabled,
            "order_index": rule.order_index,
            "tags": list(rule.tags or []),
        }

    @staticmethod
    def _nat_snapshot(rule: Any) -> dict[str, Any]:
        return {
            "name": rule.name,
            "description": rule.description,
            "type": rule.type.value,
            "interface": rule.interface,
            "protocol": rule.protocol,
            "source": rule.source,
            "destination": rule.destination,
            "destination_port": rule.destination_port,
            "target": rule.target,
            "target_port": rule.target_port,
            "enabled": rule.enabled,
            "order_index": rule.order_index,
        }

    @staticmethod
    def _vlan_snapshot(vlan: Any) -> dict[str, Any]:
        return {
            "vlan_id": vlan.vlan_id,
            "parent_interface": vlan.parent_interface,
            "description": vlan.description,
            "enabled": vlan.enabled,
        }

    async def _restore_state(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Replay a captured desired state to every device and to the appliances."""
        from app.models.config import FirewallRule, NatRule, VlanConfig
        from app.models.enums import NatType, RuleAction, RuleDirection

        deployer = ConfigurationDeployer(self.session, self.tenant_id, self.actor_id)
        vpn_deployer = VpnPolicyDeployer(self.session, self.tenant_id, self.actor_id)
        restored = {"rules": 0, "nat": 0, "vlans": 0, "vpn": 0, "errors": []}

        for raw_device_id, payload in (snapshot or {}).items():
            device = await self.uow.devices.get(uuid.UUID(str(raw_device_id)))
            if device is None:
                restored["errors"].append(f"Device {raw_device_id} no longer exists")
                continue

            if "rules" in payload:
                await self.session.execute(delete(FirewallRule).where(FirewallRule.device_id == device.id))
                for item in payload.get("rules") or []:
                    self.session.add(
                        FirewallRule(
                            tenant_id=self.tenant_id,
                            device_id=device.id,
                            name=item["name"],
                            description=item.get("description"),
                            action=RuleAction(item["action"]),
                            direction=RuleDirection(item["direction"]),
                            interface=item.get("interface"),
                            protocol=item.get("protocol") or "any",
                            source=item.get("source") or "any",
                            destination=item.get("destination") or "any",
                            destination_port=item.get("destination_port"),
                            source_port=item.get("source_port"),
                            gateway=item.get("gateway"),
                            log=bool(item.get("log")),
                            enabled=bool(item.get("enabled", True)),
                            order_index=int(item.get("order_index") or 0),
                            tags=item.get("tags") or [],
                        )
                    )
                await self.session.flush()
                try:
                    await deployer.deploy_rules(device.id, dry_run=False, apply=True)
                except Exception as exc:  # noqa: BLE001 - keep restoring other devices
                    restored["errors"].append(f"{device.name}: {exc}")
                restored["rules"] += len(payload.get("rules") or [])

            if "nat" in payload:
                await self.session.execute(delete(NatRule).where(NatRule.device_id == device.id))
                for item in payload.get("nat") or []:
                    self.session.add(
                        NatRule(
                            tenant_id=self.tenant_id,
                            device_id=device.id,
                            name=item["name"],
                            description=item.get("description"),
                            type=NatType(item["type"]),
                            interface=item.get("interface") or "wan",
                            protocol=item.get("protocol") or "tcp",
                            source=item.get("source") or "any",
                            destination=item.get("destination") or "any",
                            destination_port=item.get("destination_port"),
                            target=item["target"],
                            target_port=item.get("target_port"),
                            enabled=bool(item.get("enabled", True)),
                            order_index=int(item.get("order_index") or 0),
                        )
                    )
                await self.session.flush()
                try:
                    await deployer.deploy_nat(device.id, dry_run=False, apply=True)
                except Exception as exc:  # noqa: BLE001 - keep restoring other devices
                    restored["errors"].append(f"{device.name}: {exc}")
                restored["nat"] += len(payload.get("nat") or [])

            if "vlans" in payload:
                await self.session.execute(delete(VlanConfig).where(VlanConfig.device_id == device.id))
                for item in payload.get("vlans") or []:
                    self.session.add(
                        VlanConfig(
                            tenant_id=self.tenant_id,
                            device_id=device.id,
                            vlan_id=int(item["vlan_id"]),
                            parent_interface=item["parent_interface"],
                            description=item.get("description"),
                            enabled=bool(item.get("enabled", True)),
                        )
                    )
                await self.session.flush()
                try:
                    await deployer.deploy_vlans(device.id, dry_run=False, apply=True)
                except Exception as exc:  # noqa: BLE001 - keep restoring other devices
                    restored["errors"].append(f"{device.name}: {exc}")
                restored["vlans"] += len(payload.get("vlans") or [])

            if "vpn" in payload:
                spec = payload.get("vpn") or None
                policy_name = str(payload.get("policy") or "")
                try:
                    if spec:
                        await vpn_deployer.deploy(device.id, spec, policy_name, dry_run=False, apply=True)
                        restored["vpn"] += 1
                    elif policy_name:
                        await vpn_deployer.teardown(device.id, policy_name, dry_run=False, apply=True)
                except Exception as exc:  # noqa: BLE001 - keep restoring other devices
                    restored["errors"].append(f"{device.name}: {exc}")

        return restored

    async def rollback(self, deployment_id: uuid.UUID) -> PolicyDeployment:
        """Restore the desired state captured before a deployment.

        Every deployment stores ``snapshot.before`` and ``snapshot.after``. A
        rollback replays ``snapshot.before`` to the same targets and to the
        appliances, then records the outcome. Deployments created before
        snapshots existed fall back to the previous deployment's
        ``snapshot.after`` and are rejected when neither is available.
        """
        deployment = await self.session.get(PolicyDeployment, deployment_id)
        if deployment is None or deployment.tenant_id != self.tenant_id:
            raise NotFoundError("Deployment not found")
        policy = await self.uow.policies.get_or_404(deployment.policy_id)
        previous = (
            (
                await self.session.execute(
                    select(PolicyDeployment)
                    .where(
                        PolicyDeployment.policy_id == policy.id,
                        PolicyDeployment.created_at < deployment.created_at,
                        PolicyDeployment.status == DeploymentStatus.COMPLETED,
                    )
                    .order_by(PolicyDeployment.created_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )

        snapshot = deployment.snapshot or {}
        before = snapshot.get("before") or {}
        if not before and previous is not None:
            before = (previous.snapshot or {}).get("after") or {}
        if not before:
            raise BadRequestError("Deployment has no snapshot to restore")

        restored = await self._restore_state(before)
        deployment.status = (
            DeploymentStatus.ROLLED_BACK if not restored["errors"] else DeploymentStatus.FAILED
        )
        deployment.results = [restored]
        deployment.completed_at = datetime.now(UTC)
        await self.session.flush()
        await self.audit.record(
            action="policy.rolled_back",
            resource_type="Policy",
            resource_id=policy.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "deployment_id": str(deployment.id),
                "previous_deployment_id": str(previous.id) if previous else None,
                "restored": restored,
                "status": deployment.status.value,
            },
        )
        await self.session.commit()
        return deployment


class DriftService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.devices = DeviceService(session, tenant_id, actor_id)
        self.audit = AuditService(session)

    async def scan(self, device_ids: list[uuid.UUID] | None = None) -> list[DriftReport]:
        targets: list[Device] = []
        if device_ids:
            targets = [await self.devices.get(device_id) for device_id in device_ids]
        else:
            targets, _ = await self.devices.list(size=500)

        reports: list[DriftReport] = []
        for device in targets:
            policy = (
                (
                    await self.session.execute(
                        select(Policy)
                        .where(
                            Policy.tenant_id == self.tenant_id,
                            Policy.kind == PolicyKind.FIREWALL,
                            Policy.status == PolicyStatus.DEPLOYED,
                        )
                        .order_by(Policy.updated_at.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            if policy is None:
                continue

            desired = json.dumps(policy.content, sort_keys=True)
            desired_hash = content_hash(desired)
            actual_rules: list[dict[str, Any]] = []
            try:
                base_url, key, secret = await self.devices.credentials(device)
                from app.integrations.opnsense.client import client_for

                async with client_for(base_url, key, secret) as client:
                    payload = await client.search_rules()
                    actual_rules = payload.get("rows") or []
            except Exception as exc:  # noqa: BLE001 - unreachable device is reported as drift
                log.warning("drift.device_unreachable", device=device.name, error=str(exc))

            documented = await self.uow.rules.for_device(device.id)
            differences = self._compare(documented, actual_rules)
            actual_hash = content_hash(json.dumps(actual_rules, sort_keys=True, default=str))

            report = await self.uow.drift.open_for_device(device.id)
            if differences and report is None:
                report = DriftReport(
                    tenant_id=self.tenant_id,
                    device_id=device.id,
                    policy_id=policy.id,
                    status=DriftStatus.OPEN,
                    differences=differences,
                    desired_hash=desired_hash,
                    actual_hash=actual_hash,
                    detected_at=datetime.now(UTC),
                )
                self.session.add(report)
                await self.session.flush()
                from app.core.events import DriftDetected

                await event_bus.publish(
                    DriftDetected(
                        device_id=str(device.id),
                        tenant_id=str(self.tenant_id),
                        policy_id=str(policy.id),
                        differences=len(differences),
                    )
                )
            elif differences and report is not None:
                report.differences = differences
                report.actual_hash = actual_hash
            elif not differences and report is not None:
                report.status = DriftStatus.REMEDIATED
                report.resolved_at = datetime.now(UTC)
            if report is not None:
                reports.append(report)

        await self.session.commit()
        return reports

    @staticmethod
    def _compare(documented: list[Any], actual: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actual_summary = {
            str(row.get("descr") or row.get("description") or "").strip(): {
                "action": row.get("action"),
                "interface": row.get("interface"),
            }
            for row in actual
            if isinstance(row, dict)
        }
        differences: list[dict[str, Any]] = []
        for rule in documented:
            key = (rule.description or rule.name).strip()
            if key not in actual_summary:
                differences.append(
                    {"type": "missing_on_device", "rule": rule.name, "expected_action": rule.action.value}
                )
            elif str(actual_summary[key].get("action", "")).lower() != rule.action.value:
                differences.append(
                    {
                        "type": "action_mismatch",
                        "rule": rule.name,
                        "expected": rule.action.value,
                        "actual": actual_summary[key].get("action"),
                    }
                )
        return differences


class ChangeRequestService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.audit = AuditService(session)

    async def create(
        self,
        *,
        title: str,
        type_: str,
        payload: dict,
        description: str | None = None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        required_approvals: int = 1,
        environment: Environment | None = None,
        expires_in_hours: int = 72,
        priority: str = "medium",
    ) -> ChangeRequest:
        change = ChangeRequest(
            tenant_id=self.tenant_id,
            title=title,
            description=description,
            type=type_,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
            status=ChangeStatus.PENDING,
            priority=priority,
            environment=environment,
            requested_by=self.actor_id,
            required_approvals=required_approvals,
            expires_at=datetime.now(UTC) + timedelta(hours=expires_in_hours),
        )
        self.session.add(change)
        await self.session.flush()
        await self.audit.record(
            action="change_request.created",
            resource_type="ChangeRequest",
            resource_id=change.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"title": change.title, "type": str(change.type)},
        )
        return change

    async def approve(self, change_id: uuid.UUID, *, comment: str | None = None) -> ChangeRequest:
        change = await self.uow.changes.get_or_404(change_id)
        if change.status not in {ChangeStatus.PENDING, ChangeStatus.APPROVED}:
            raise BadRequestError(f"Change request is {change.status.value}")
        if change.requested_by == self.actor_id:
            raise BadRequestError("Four-eyes principle: the requester cannot approve their own change")
        approvals = list(change.approvals or [])
        if any(a.get("user_id") == str(self.actor_id) for a in approvals):
            raise BadRequestError("You have already reviewed this change")
        approvals.append(
            {
                "user_id": str(self.actor_id),
                "decision": "approved",
                "comment": comment,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        change.approvals = approvals
        if len([a for a in approvals if a["decision"] == "approved"]) >= change.required_approvals:
            change.status = ChangeStatus.APPROVED
        await self.session.flush()
        await self.audit.record(
            action="change_request.approved",
            resource_type="ChangeRequest",
            resource_id=change.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"approvals": len(approvals), "status": change.status.value},
        )
        return change

    async def reject(self, change_id: uuid.UUID, *, comment: str | None = None) -> ChangeRequest:
        change = await self.uow.changes.get_or_404(change_id)
        approvals = list(change.approvals or [])
        approvals.append(
            {
                "user_id": str(self.actor_id),
                "decision": "rejected",
                "comment": comment,
                "at": datetime.now(UTC).isoformat(),
            }
        )
        change.approvals = approvals
        change.status = ChangeStatus.REJECTED
        await self.session.flush()
        await self.audit.record(
            action="change_request.rejected",
            resource_type="ChangeRequest",
            resource_id=change.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
        )
        return change

    async def cancel(self, change_id: uuid.UUID) -> ChangeRequest:
        change = await self.uow.changes.get_or_404(change_id)
        change.status = ChangeStatus.CANCELLED
        await self.session.flush()
        return change


class PromotionService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)

    async def promote(
        self,
        *,
        policy_id: uuid.UUID,
        source_environment: Environment,
        target_environment: Environment,
        create_change_request: bool = True,
    ) -> Policy:
        source = await self.uow.policies.get_or_404(policy_id)
        if source.environment != source_environment:
            raise BadRequestError("Source environment does not match policy environment")
        if source.status not in {PolicyStatus.APPROVED, PolicyStatus.DEPLOYED, PolicyStatus.VALIDATED}:
            raise BadRequestError("Only approved or deployed policies can be promoted")

        target = (
            (
                await self.session.execute(
                    select(Policy).where(
                        Policy.tenant_id == self.tenant_id,
                        Policy.name == source.name,
                        Policy.environment == target_environment,
                    )
                )
            )
            .scalars()
            .first()
        )

        if target is None:
            target = Policy(
                tenant_id=self.tenant_id,
                repo_id=source.repo_id,
                name=source.name,
                kind=source.kind,
                environment=target_environment,
                path=source.path,
                content=source.content,
                content_hash=source.content_hash,
                description=source.description,
                target_selector=source.target_selector,
                created_by=self.actor_id,
                status=PolicyStatus.VALIDATED,
            )
            self.session.add(target)
        else:
            target.content = source.content
            target.content_hash = source.content_hash
            target.version += 1
            target.status = PolicyStatus.VALIDATED

        await self.session.flush()
        if create_change_request and target_environment == Environment.PRODUCTION:
            await ChangeRequestService(self.session, self.tenant_id, self.actor_id).create(
                title=f"Promote {source.name} to production",
                type_="policy",
                payload={"policy_id": str(target.id), "source": source_environment.value},
                resource_type="Policy",
                resource_id=target.id,
                required_approvals=2,
                environment=Environment.PRODUCTION,
            )
        await self.session.commit()
        return target
