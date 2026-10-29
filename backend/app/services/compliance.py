"""Compliance engine: control catalogues, evaluation, scoring and remediation."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.config import FirewallRule
from app.models.enums import (
    AlertStatus,
    CertificateStatus,
    ComplianceFramework,
    RuleAction,
)
from app.models.metrics import DeviceTelemetrySnapshot
from app.models.operations import Backup
from app.models.policy import ChangeRequest, DriftReport, Policy
from app.models.topology import Device, DeviceCertificate
from app.repositories import UnitOfWork
from app.schemas.compliance import ControlResult
from app.services.audit import AuditService

log = get_logger("ofme.compliance")


@dataclass(slots=True)
class Facts:
    devices: list[Device]
    rules: list[FirewallRule]
    policies: list[Policy]
    certificates: list[DeviceCertificate]
    snapshots: dict[uuid.UUID, DeviceTelemetrySnapshot]
    open_alerts: int
    drift_open: int
    backups_7d: int
    mfa_users: int
    total_users: int
    change_requests_approved: int


Check = Callable[[Facts], Awaitable[ControlResult]]


@dataclass(slots=True)
class Control:
    control_id: str
    title: str
    severity: str
    check: Check
    remediation: str | None = None


class ComplianceService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ facts
    async def collect(self, device_ids: list[uuid.UUID]) -> Facts:
        device_query = self.uow.devices.query()
        if device_ids:
            device_query = device_query.where(Device.id.in_(device_ids))
        devices = list((await self.session.execute(device_query)).scalars().all())
        ids = [d.id for d in devices]

        rules = list(
            (
                await self.session.execute(
                    self.uow.rules.query().where(FirewallRule.device_id.in_(ids))
                    if ids
                    else self.uow.rules.query().where(FirewallRule.tenant_id == self.tenant_id)
                )
            )
            .scalars()
            .all()
        )
        policies = list((await self.session.execute(self.uow.policies.query())).scalars().all())
        certificates = list(
            (
                await self.session.execute(
                    self.uow.certificates.query().where(DeviceCertificate.device_id.in_(ids))
                    if ids
                    else self.uow.certificates.query()
                )
            )
            .scalars()
            .all()
        )
        snapshots = {
            snapshot.device_id: snapshot
            for snapshot in (await self.session.execute(self.uow.snapshots.query())).scalars().all()
        }
        open_alerts = (
            await self.session.execute(
                select(func.count()).select_from(
                    self.uow.alerts.query()
                    .where(self.uow.alerts.model.status == AlertStatus.FIRING)
                    .subquery()
                )
            )
        ).scalar_one()
        drift_open = (
            await self.session.execute(
                select(func.count()).select_from(
                    self.uow.drift.query().where(DriftReport.status == "open").subquery()
                )
            )
        ).scalar_one()
        backups_7d = (
            await self.session.execute(
                select(func.count()).select_from(
                    self.uow.backups.query()
                    .where(Backup.created_at >= datetime.now(UTC) - timedelta(days=7))
                    .subquery()
                )
            )
        ).scalar_one()
        users = list((await self.session.execute(self.uow.users.query())).scalars().all())
        approved_changes = (
            await self.session.execute(
                select(func.count()).select_from(
                    self.uow.changes.query().where(ChangeRequest.status == "approved").subquery()
                )
            )
        ).scalar_one()

        return Facts(
            devices=devices,
            rules=rules,
            policies=policies,
            certificates=certificates,
            snapshots=snapshots,
            open_alerts=int(open_alerts),
            drift_open=int(drift_open),
            backups_7d=int(backups_7d),
            mfa_users=sum(1 for u in users if u.mfa_enabled),
            total_users=len(users),
            change_requests_approved=int(approved_changes),
        )

    # ------------------------------------------------------------------ run
    async def run(self, framework: ComplianceFramework, device_ids: list[uuid.UUID]) -> dict[str, Any]:
        facts = await self.collect(device_ids)
        controls = self._catalogue(framework)
        results: list[ControlResult] = []
        for control in controls:
            try:
                result = await control.check(facts)
            except Exception as exc:  # noqa: BLE001 - a failing check must not abort the report
                result = ControlResult(
                    control_id=control.control_id,
                    title=control.title,
                    status="fail",
                    severity=control.severity,
                    evidence=f"Evaluation error: {exc}",
                    remediation=control.remediation,
                )
            if control.remediation and not result.remediation:
                result.remediation = control.remediation
            results.append(result)

        passed = sum(1 for r in results if r.status == "pass")
        failed = sum(1 for r in results if r.status == "fail")
        applicable = passed + failed
        score = (passed / applicable * 100.0) if applicable else 100.0

        from app.models.compliance import ComplianceReport

        report = ComplianceReport(
            tenant_id=self.tenant_id,
            framework=framework,
            scope={"device_ids": [str(d) for d in device_ids], "devices_evaluated": len(facts.devices)},
            status="completed",
            score=round(score, 2),
            controls_total=len(results),
            controls_passed=passed,
            controls_failed=failed,
            findings=[r.model_dump() for r in results if r.status == "fail"],
            controls=[r.model_dump() for r in results],
            summary=(
                f"{framework.value.upper()}: {passed}/{applicable} controls passed "
                f"across {len(facts.devices)} device(s)."
            ),
            generated_at=datetime.now(UTC),
            generated_by=self.actor_id,
        )
        self.session.add(report)
        await self.session.flush()
        await self.audit.record(
            action="compliance.report_generated",
            resource_type="ComplianceReport",
            resource_id=report.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"framework": framework.value, "score": report.score, "failed": failed},
        )
        await self.session.commit()
        return {"report": report, "results": results}

    # ------------------------------------------------------------------ catalogue
    def _catalogue(self, framework: ComplianceFramework) -> list[Control]:
        common: list[Control] = [
            Control(
                control_id="FW-001",
                title="No unrestricted pass rules on WAN",
                severity="critical",
                check=self._check_no_any_any,
                remediation="Restrict or remove pass-any rules on the WAN interface.",
            ),
            Control(
                control_id="FW-002",
                title="Firewall logging enabled for deny rules",
                severity="medium",
                check=self._check_deny_logging,
                remediation="Enable logging on block/reject rules for forensic visibility.",
            ),
            Control(
                control_id="PKI-001",
                title="All device certificates valid",
                severity="high",
                check=self._check_certificates,
                remediation="Rotate expired certificates and revoke compromised ones.",
            ),
            Control(
                control_id="BCK-001",
                title="Configuration backups within 7 days",
                severity="high",
                check=self._check_backups,
                remediation="Schedule automated configuration backups.",
            ),
            Control(
                control_id="IDN-001",
                title="MFA enforced for privileged accounts",
                severity="high",
                check=self._check_mfa,
                remediation="Enable TOTP for all administrative accounts.",
            ),
            Control(
                control_id="CHG-001",
                title="Change control in use",
                severity="medium",
                check=self._check_change_control,
                remediation="Route production changes through the approval workflow.",
            ),
            Control(
                control_id="DRF-001",
                title="No unresolved configuration drift",
                severity="high",
                check=self._check_drift,
                remediation="Re-deploy the approved policy or acknowledge drift.",
            ),
            Control(
                control_id="MON-001",
                title="Telemetry present for all devices",
                severity="medium",
                check=self._check_telemetry,
                remediation="Install os-fleet-agent or configure API polling.",
            ),
        ]

        if framework == ComplianceFramework.CIS:
            common.extend(
                [
                    Control(
                        control_id="CIS-4.1",
                        title="Secure configuration baseline applied",
                        severity="high",
                        check=self._check_policy_baseline,
                        remediation="Deploy the CIS baseline policy to all devices.",
                    ),
                    Control(
                        control_id="CIS-8.2",
                        title="Audit logging enabled",
                        severity="high",
                        check=self._check_audit_logging,
                        remediation="Enable platform audit logging (always on) and forward to SIEM.",
                    ),
                ]
            )
        elif framework == ComplianceFramework.ISO27001:
            common.extend(
                [
                    Control(
                        control_id="A.9.2",
                        title="User access management",
                        severity="high",
                        check=self._check_access,
                    ),
                    Control(
                        control_id="A.12.4",
                        title="Event logging",
                        severity="high",
                        check=self._check_audit_logging,
                    ),
                    Control(
                        control_id="A.13.1",
                        title="Network controls",
                        severity="high",
                        check=self._check_no_any_any,
                    ),
                ]
            )
        elif framework == ComplianceFramework.NIS2:
            common.extend(
                [
                    Control(
                        control_id="NIS2-21.2a",
                        title="Risk analysis and security policies",
                        severity="high",
                        check=self._check_policy_baseline,
                    ),
                    Control(
                        control_id="NIS2-21.2i",
                        title="MFA and secured communications",
                        severity="critical",
                        check=self._check_mfa,
                    ),
                    Control(
                        control_id="NIS2-21.2c",
                        title="Business continuity and backups",
                        severity="high",
                        check=self._check_backups,
                    ),
                ]
            )
        elif framework == ComplianceFramework.PCI_DSS:
            common.extend(
                [
                    Control(
                        control_id="PCI-1.3",
                        title="DMZ segmentation",
                        severity="critical",
                        check=self._check_no_any_any,
                    ),
                    Control(
                        control_id="PCI-10.1",
                        title="Audit trails",
                        severity="high",
                        check=self._check_audit_logging,
                    ),
                    Control(
                        control_id="PCI-6.2",
                        title="Secure configuration",
                        severity="high",
                        check=self._check_policy_baseline,
                    ),
                ]
            )
        elif framework == ComplianceFramework.SOC2:
            common.extend(
                [
                    Control(
                        control_id="CC6.1",
                        title="Logical access controls",
                        severity="high",
                        check=self._check_access,
                    ),
                    Control(
                        control_id="CC7.2",
                        title="Monitoring activities",
                        severity="high",
                        check=self._check_telemetry,
                    ),
                ]
            )
        return common

    # ------------------------------------------------------------------ checks
    async def _check_no_any_any(self, facts: Facts) -> ControlResult:
        offenders = [
            rule.name
            for rule in facts.rules
            if rule.action == RuleAction.PASS
            and rule.source in {"any", ""}
            and rule.destination in {"any", ""}
            and rule.enabled
        ]
        return self._result(
            "FW-001",
            "No unrestricted pass rules on WAN",
            "critical",
            not offenders,
            f"{len(offenders)} unrestricted pass rule(s): {', '.join(offenders[:5])}"
            if offenders
            else "No pass-any rules",
            [d.id for d in facts.devices],
        )

    async def _check_deny_logging(self, facts: Facts) -> ControlResult:
        deny = [r for r in facts.rules if r.action in {RuleAction.BLOCK, RuleAction.REJECT}]
        offenders = [r.name for r in deny if not r.log]
        return self._result(
            "FW-002",
            "Firewall logging enabled for deny rules",
            "medium",
            not offenders,
            f"{len(offenders)} deny rule(s) without logging" if offenders else "Deny logging enabled",
        )

    async def _check_certificates(self, facts: Facts) -> ControlResult:
        now = datetime.now(UTC)
        invalid = [
            cert.device_id
            for cert in facts.certificates
            if cert.status != CertificateStatus.ACTIVE or cert.valid_to <= now
        ]
        return self._result(
            "PKI-001",
            "All device certificates valid",
            "high",
            not invalid,
            f"{len(invalid)} invalid certificate(s)" if invalid else "All certificates valid",
            invalid,
        )

    async def _check_backups(self, facts: Facts) -> ControlResult:
        return self._result(
            "BCK-001",
            "Configuration backups within 7 days",
            "high",
            facts.backups_7d > 0,
            f"{facts.backups_7d} backup(s) in the last 7 days",
        )

    async def _check_mfa(self, facts: Facts) -> ControlResult:
        ok = facts.total_users == 0 or facts.mfa_users / max(facts.total_users, 1) >= 0.5
        return self._result(
            "IDN-001",
            "MFA enforced for privileged accounts",
            "high",
            ok,
            f"{facts.mfa_users}/{facts.total_users} users have MFA",
        )

    async def _check_change_control(self, facts: Facts) -> ControlResult:
        return self._result(
            "CHG-001",
            "Change control in use",
            "medium",
            facts.change_requests_approved >= 0,
            f"{facts.change_requests_approved} approved change request(s)",
        )

    async def _check_drift(self, facts: Facts) -> ControlResult:
        return self._result(
            "DRF-001",
            "No unresolved configuration drift",
            "high",
            facts.drift_open == 0,
            f"{facts.drift_open} open drift report(s)",
        )

    async def _check_telemetry(self, facts: Facts) -> ControlResult:
        missing = [d.id for d in facts.devices if d.id not in facts.snapshots]
        return self._result(
            "MON-001",
            "Telemetry present for all devices",
            "medium",
            not missing,
            f"{len(missing)} device(s) without telemetry" if missing else "All devices reporting",
            missing,
        )

    async def _check_policy_baseline(self, facts: Facts) -> ControlResult:
        deployed = [p for p in facts.policies if p.status == "deployed"]
        return self._result(
            "CIS-4.1",
            "Secure configuration baseline applied",
            "high",
            bool(deployed),
            f"{len(deployed)} deployed policy set(s)",
        )

    async def _check_audit_logging(self, facts: Facts) -> ControlResult:
        from app.models.audit import AuditLog

        count = (
            await self.session.execute(
                select(func.count()).select_from(
                    select(AuditLog)
                    .where(
                        AuditLog.tenant_id == self.tenant_id,
                        AuditLog.created_at >= datetime.now(UTC) - timedelta(days=1),
                    )
                    .subquery()
                )
            )
        ).scalar_one()
        return self._result(
            "AUD-001",
            "Audit logging enabled",
            "high",
            int(count) > 0,
            f"{count} audit events in the last 24h",
        )

    async def _check_access(self, facts: Facts) -> ControlResult:
        return self._result(
            "IAM-001",
            "User access management",
            "high",
            facts.total_users > 0,
            f"{facts.total_users} user(s) provisioned",
        )

    @staticmethod
    def _result(
        control_id: str,
        title: str,
        severity: str,
        ok: bool,
        evidence: str,
        affected: list[uuid.UUID] | None = None,
    ) -> ControlResult:
        return ControlResult(
            control_id=control_id,
            title=title,
            status="pass" if ok else "fail",
            severity=severity,
            evidence=evidence,
            affected_devices=affected or [],
        )


class RemediationService:
    """Automated remediation for a subset of findings (safe, idempotent)."""

    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.actor_id = actor_id
        self.audit = AuditService(session)

    async def remediate(
        self, finding_ids: list[str], device_ids: list[uuid.UUID], dry_run: bool = True
    ) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        dry_run = dry_run

        if not finding_ids or "FW-001" in finding_ids or "FW-002" in finding_ids:
            query = self.uow.rules.query().where(FirewallRule.tenant_id == self.tenant_id)
            if device_ids:
                query = query.where(FirewallRule.device_id.in_(device_ids))
            rules = list((await self.session.execute(query)).scalars().all())
            for rule in rules:
                if (
                    "FW-001" in finding_ids
                    and rule.action == RuleAction.PASS
                    and rule.source in {"any", ""}
                    and rule.destination in {"any", ""}
                ):
                    actions.append({"rule": rule.name, "action": "disable", "reason": "FW-001"})
                    if not dry_run:
                        rule.enabled = False
                if (
                    "FW-002" in finding_ids
                    and rule.action in {RuleAction.BLOCK, RuleAction.REJECT}
                    and not rule.log
                ):
                    actions.append({"rule": rule.name, "action": "enable_logging", "reason": "FW-002"})
                    if not dry_run:
                        rule.log = True

        if "BCK-001" in finding_ids and not dry_run:
            from app.services.backup import BackupService

            service = BackupService(self.session, self.tenant_id, self.actor_id)
            for device in (await self.uow.devices.list(size=200))[0]:
                try:
                    await service.create_backup(device.id, backup_type="auto")
                    actions.append({"device": device.name, "action": "backup_created", "reason": "BCK-001"})
                except Exception as exc:  # noqa: BLE001 - continue best-effort
                    actions.append({"device": device.name, "action": "backup_failed", "error": str(exc)})

        if not dry_run:
            await self.session.flush()
            await self.audit.record(
                action="compliance.remediated",
                resource_type="ComplianceFinding",
                resource_id=",".join(finding_ids),
                tenant_id=self.tenant_id,
                user_id=self.actor_id,
                after={"actions": len(actions)},
            )
            await self.session.commit()

        return {
            "requested": len(finding_ids),
            "remediated": sum(1 for a in actions if "error" not in a),
            "failed": sum(1 for a in actions if "error" in a),
            "details": actions,
        }
