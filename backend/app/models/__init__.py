"""Import every model so `Base.metadata` is complete for Alembic and tests."""

from app.db.base import Base
from app.models.audit import AuditLog, DomainEventRecord
from app.models.compliance import ComplianceReport
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
from app.models.enums import *  # noqa: F403
from app.models.ha import HaCluster, HaNode
from app.models.identity import ApiKey, Permission, RefreshToken, Role, Tenant, User, user_roles
from app.models.metrics import DeviceMetric, DeviceTelemetrySnapshot
from app.models.operations import Alert, AlertRule, Backup, Job, Notification, Task
from app.models.policy import ChangeRequest, DriftReport, GitRepository, Policy, PolicyDeployment
from app.models.sdwan import (
    OpenVpnCa,
    OpenVpnCertificate,
    SdwanLink,
    SdwanRoute,
    SdwanTopology,
    TrafficPolicy,
    VpnTunnel,
    WireGuardKey,
)
from app.models.topology import Device, DeviceCertificate, DeviceGroup, Site
from app.models.ztp import ZtpEnrollment

__all__ = [
    "Base",
    # identity
    "Tenant",
    "User",
    "Role",
    "Permission",
    "RefreshToken",
    "ApiKey",
    "user_roles",
    # topology
    "Site",
    "DeviceGroup",
    "Device",
    "DeviceCertificate",
    # configuration
    "Template",
    "FirewallRule",
    "Alias",
    "NatRule",
    "InterfaceConfig",
    "RouteConfig",
    "VlanConfig",
    "DhcpScope",
    "DhcpReservation",
    "DnsRecord",
    # gitops
    "GitRepository",
    "Policy",
    "PolicyDeployment",
    "DriftReport",
    "ChangeRequest",
    # sdwan
    "SdwanTopology",
    "VpnTunnel",
    "SdwanLink",
    "TrafficPolicy",
    "SdwanRoute",
    "WireGuardKey",
    "OpenVpnCa",
    "OpenVpnCertificate",
    # high availability
    "HaCluster",
    "HaNode",
    # operations
    "Task",
    "Job",
    "Backup",
    "Alert",
    "AlertRule",
    "Notification",
    # telemetry
    "DeviceMetric",
    "DeviceTelemetrySnapshot",
    # ztp / compliance / audit
    "ZtpEnrollment",
    "ComplianceReport",
    "AuditLog",
    "DomainEventRecord",
]
