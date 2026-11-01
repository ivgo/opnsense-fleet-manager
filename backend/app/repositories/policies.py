from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.config import (
    Alias,
    DhcpReservation,
    DhcpScope,
    DnsRecord,
    FirewallRule,
    InterfaceConfig,
    IpsecPhase1,
    IpsecPhase2,
    NatRule,
    RouteConfig,
    Template,
    VlanConfig,
)
from app.models.enums import Environment, PolicyStatus
from app.models.policy import ChangeRequest, DriftReport, GitRepository, Policy, PolicyDeployment
from app.repositories.base import BaseRepository


class TemplateRepository(BaseRepository[Template]):
    model = Template

    async def inheritance_chain(self, template: Template) -> list[Template]:
        chain: list[Template] = [template]
        seen: set[uuid.UUID] = {template.id}
        current = template
        while current.parent_id and current.parent_id not in seen:
            parent = await self.get(current.parent_id)
            if parent is None:
                break
            chain.append(parent)
            seen.add(parent.id)
            current = parent
        return list(reversed(chain))


class FirewallRuleRepository(BaseRepository[FirewallRule]):
    model = FirewallRule

    async def for_device(self, device_id: uuid.UUID) -> list[FirewallRule]:
        stmt = self.query().where(FirewallRule.device_id == device_id).order_by(FirewallRule.order_index)
        return list((await self.session.execute(stmt)).scalars().all())

    async def max_order(self, device_id: uuid.UUID) -> int:
        stmt = select(FirewallRule.order_index).where(FirewallRule.device_id == device_id)
        values = [row[0] for row in (await self.session.execute(stmt)).all()]
        return max(values, default=0)


class AliasRepository(BaseRepository[Alias]):
    model = Alias


class NatRuleRepository(BaseRepository[NatRule]):
    model = NatRule

    async def for_device(self, device_id: uuid.UUID) -> list[NatRule]:
        stmt = self.query().where(NatRule.device_id == device_id).order_by(NatRule.order_index, NatRule.name)
        return list((await self.session.execute(stmt)).scalars().all())


class InterfaceRepository(BaseRepository[InterfaceConfig]):
    model = InterfaceConfig


class RouteRepository(BaseRepository[RouteConfig]):
    model = RouteConfig

    async def for_device(self, device_id: uuid.UUID) -> list[RouteConfig]:
        stmt = self.query().where(RouteConfig.device_id == device_id)
        return list((await self.session.execute(stmt)).scalars().all())


class VlanRepository(BaseRepository[VlanConfig]):
    model = VlanConfig

    async def for_device(self, device_id: uuid.UUID) -> list[VlanConfig]:
        stmt = (
            self.query()
            .where(VlanConfig.device_id == device_id)
            .order_by(VlanConfig.parent_interface, VlanConfig.vlan_id)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class DhcpScopeRepository(BaseRepository[DhcpScope]):
    model = DhcpScope

    async def for_device(self, device_id: uuid.UUID) -> list[DhcpScope]:
        stmt = self.query().where(DhcpScope.device_id == device_id).order_by(DhcpScope.name)
        return list((await self.session.execute(stmt)).scalars().all())


class DhcpReservationRepository(BaseRepository[DhcpReservation]):
    model = DhcpReservation

    async def for_scope(self, scope_id: uuid.UUID) -> list[DhcpReservation]:
        stmt = self.query().where(DhcpReservation.scope_id == scope_id).order_by(DhcpReservation.hostname)
        return list((await self.session.execute(stmt)).scalars().all())


class DnsRecordRepository(BaseRepository[DnsRecord]):
    model = DnsRecord

    async def for_device(self, device_id: uuid.UUID) -> list[DnsRecord]:
        stmt = self.query().where(DnsRecord.device_id == device_id).order_by(DnsRecord.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_name(self, device_id: uuid.UUID, name: str) -> list[DnsRecord]:
        stmt = self.query().where(DnsRecord.device_id == device_id, DnsRecord.name == name)
        return list((await self.session.execute(stmt)).scalars().all())


class IpsecPhase1Repository(BaseRepository[IpsecPhase1]):
    model = IpsecPhase1

    async def for_device(self, device_id: uuid.UUID) -> list[IpsecPhase1]:
        stmt = self.query().where(IpsecPhase1.device_id == device_id).order_by(IpsecPhase1.name)
        return list((await self.session.execute(stmt)).scalars().all())


class IpsecPhase2Repository(BaseRepository[IpsecPhase2]):
    model = IpsecPhase2

    async def for_device(self, device_id: uuid.UUID) -> list[IpsecPhase2]:
        stmt = self.query().where(IpsecPhase2.device_id == device_id).order_by(IpsecPhase2.name)
        return list((await self.session.execute(stmt)).scalars().all())


class GitRepositoryRepository(BaseRepository[GitRepository]):
    model = GitRepository

    async def auto_sync_repos(self) -> list[GitRepository]:
        stmt = self.query().where(GitRepository.auto_sync.is_(True), GitRepository.status == "active")
        return list((await self.session.execute(stmt)).scalars().all())


class PolicyRepository(BaseRepository[Policy]):
    model = Policy

    async def by_environment(self, environment: Environment) -> list[Policy]:
        stmt = self.query().where(Policy.environment == environment)
        return list((await self.session.execute(stmt)).scalars().all())

    async def deployable(self) -> list[Policy]:
        stmt = self.query().where(Policy.status.in_([PolicyStatus.APPROVED, PolicyStatus.VALIDATED]))
        return list((await self.session.execute(stmt)).scalars().all())


class DeploymentRepository(BaseRepository[PolicyDeployment]):
    model = PolicyDeployment
    soft_delete = False

    async def latest_for_policy(self, policy_id: uuid.UUID) -> PolicyDeployment | None:
        stmt = (
            self.query()
            .where(PolicyDeployment.policy_id == policy_id)
            .order_by(PolicyDeployment.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()


class DriftRepository(BaseRepository[DriftReport]):
    model = DriftReport
    soft_delete = False

    async def open_for_device(self, device_id: uuid.UUID) -> DriftReport | None:
        stmt = (
            self.query()
            .where(DriftReport.device_id == device_id, DriftReport.status == "open")
            .order_by(DriftReport.detected_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()


class ChangeRequestRepository(BaseRepository[ChangeRequest]):
    model = ChangeRequest
    soft_delete = False
