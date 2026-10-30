"""Repository package exports and Unit of Work factory."""

from __future__ import annotations

import uuid
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.devices import (
    DeviceCertificateRepository,
    DeviceGroupRepository,
    DeviceRepository,
    SiteRepository,
)
from app.repositories.ha import HaClusterRepository, HaNodeRepository
from app.repositories.identity import (
    ApiKeyRepository,
    PermissionRepository,
    RefreshTokenRepository,
    RoleRepository,
    TenantRepository,
    UserRepository,
)
from app.repositories.operations import (
    AlertRepository,
    AlertRuleRepository,
    BackupRepository,
    ComplianceReportRepository,
    JobRepository,
    MaintenanceWindowRepository,
    MetricRepository,
    NotificationRepository,
    ReportRepository,
    SnapshotRepository,
    TaskRepository,
    ZtpEnrollmentRepository,
)
from app.repositories.policies import (
    AliasRepository,
    ChangeRequestRepository,
    DeploymentRepository,
    DhcpReservationRepository,
    DhcpScopeRepository,
    DnsRecordRepository,
    DriftRepository,
    FirewallRuleRepository,
    GitRepositoryRepository,
    InterfaceRepository,
    IpsecPhase1Repository,
    IpsecPhase2Repository,
    NatRuleRepository,
    PolicyRepository,
    RouteRepository,
    TemplateRepository,
    VlanRepository,
)
from app.repositories.sdwan import (
    LinkRepository,
    OpenVpnCaRepository,
    OpenVpnCertificateRepository,
    TopologyRepository,
    TrafficPolicyRepository,
    TunnelRepository,
    WireGuardKeyRepository,
)
from app.repositories.sdwan import (
    RouteRepository as SdwanRouteRepository,
)

__all__ = [
    "UnitOfWork",
    "UserRepository",
    "RoleRepository",
    "PermissionRepository",
    "RefreshTokenRepository",
    "ApiKeyRepository",
    "TenantRepository",
    "SiteRepository",
    "DeviceGroupRepository",
    "DeviceRepository",
    "DeviceCertificateRepository",
    "TemplateRepository",
    "FirewallRuleRepository",
    "AliasRepository",
    "NatRuleRepository",
    "InterfaceRepository",
    "RouteRepository",
    "VlanRepository",
    "DhcpScopeRepository",
    "DhcpReservationRepository",
    "DnsRecordRepository",
    "IpsecPhase1Repository",
    "IpsecPhase2Repository",
    "GitRepositoryRepository",
    "PolicyRepository",
    "DeploymentRepository",
    "DriftRepository",
    "ChangeRequestRepository",
    "TopologyRepository",
    "TunnelRepository",
    "LinkRepository",
    "TrafficPolicyRepository",
    "SdwanRouteRepository",
    "WireGuardKeyRepository",
    "OpenVpnCaRepository",
    "OpenVpnCertificateRepository",
    "HaClusterRepository",
    "HaNodeRepository",
    "JobRepository",
    "TaskRepository",
    "BackupRepository",
    "AlertRuleRepository",
    "AlertRepository",
    "NotificationRepository",
    "MetricRepository",
    "SnapshotRepository",
    "MaintenanceWindowRepository",
    "ReportRepository",
    "ComplianceReportRepository",
    "ZtpEnrollmentRepository",
]


class UnitOfWork:
    """One transactional boundary per request/task.

    Usage::

        async with UnitOfWork(session, tenant_id) as uow:
            device = await uow.devices.get_or_404(device_id)
            await uow.commit()
    """

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id

        self.users = UserRepository(session, tenant_id)
        self.roles = RoleRepository(session, tenant_id)
        self.permissions = PermissionRepository(session, tenant_id)
        self.refresh_tokens = RefreshTokenRepository(session, tenant_id)
        self.api_keys = ApiKeyRepository(session, tenant_id)
        self.tenants = TenantRepository(session)

        self.sites = SiteRepository(session, tenant_id)
        self.groups = DeviceGroupRepository(session, tenant_id)
        self.devices = DeviceRepository(session, tenant_id)
        self.certificates = DeviceCertificateRepository(session, tenant_id)

        self.templates = TemplateRepository(session, tenant_id)
        self.rules = FirewallRuleRepository(session, tenant_id)
        self.aliases = AliasRepository(session, tenant_id)
        self.nat = NatRuleRepository(session, tenant_id)
        self.interfaces = InterfaceRepository(session, tenant_id)
        self.routes = RouteRepository(session, tenant_id)
        self.vlans = VlanRepository(session, tenant_id)
        self.dhcp_scopes = DhcpScopeRepository(session, tenant_id)
        self.dhcp_reservations = DhcpReservationRepository(session, tenant_id)
        self.dns_records = DnsRecordRepository(session, tenant_id)
        self.ipsec_phase1 = IpsecPhase1Repository(session, tenant_id)
        self.ipsec_phase2 = IpsecPhase2Repository(session, tenant_id)

        self.git_repos = GitRepositoryRepository(session, tenant_id)
        self.policies = PolicyRepository(session, tenant_id)
        self.deployments = DeploymentRepository(session, tenant_id)
        self.drift = DriftRepository(session, tenant_id)
        self.changes = ChangeRequestRepository(session, tenant_id)

        self.topologies = TopologyRepository(session, tenant_id)
        self.tunnels = TunnelRepository(session, tenant_id)
        self.links = LinkRepository(session, tenant_id)
        self.traffic_policies = TrafficPolicyRepository(session, tenant_id)
        self.sdwan_routes = SdwanRouteRepository(session, tenant_id)
        self.wireguard_keys = WireGuardKeyRepository(session, tenant_id)
        self.openvpn_cas = OpenVpnCaRepository(session, tenant_id)
        self.openvpn_certificates = OpenVpnCertificateRepository(session, tenant_id)

        self.ha_clusters = HaClusterRepository(session, tenant_id)
        self.ha_nodes = HaNodeRepository(session, tenant_id)

        self.jobs = JobRepository(session, tenant_id)
        self.tasks = TaskRepository(session, tenant_id)
        self.backups = BackupRepository(session, tenant_id)
        self.alert_rules = AlertRuleRepository(session, tenant_id)
        self.alerts = AlertRepository(session, tenant_id)
        self.notifications = NotificationRepository(session, tenant_id)
        self.metrics = MetricRepository(session, tenant_id)
        self.snapshots = SnapshotRepository(session, tenant_id)
        self.maintenance = MaintenanceWindowRepository(session, tenant_id)
        self.reports = ReportRepository(session, tenant_id)
        self.compliance = ComplianceReportRepository(session, tenant_id)
        self.ztp = ZtpEnrollmentRepository(session, tenant_id)

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            await self.session.commit()
        else:
            await self.session.rollback()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def flush(self) -> None:
        await self.session.flush()
