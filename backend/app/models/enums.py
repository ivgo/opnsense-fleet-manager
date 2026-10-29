"""Domain enumerations shared by ORM models, DTOs and services."""

from __future__ import annotations

from enum import StrEnum


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"
    CANCELLED = "cancelled"


class TenantPlan(StrEnum):
    COMMUNITY = "community"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"
    MSP = "msp"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"
    PENDING = "pending"


class AuthProvider(StrEnum):
    LOCAL = "local"
    LDAP = "ldap"
    AD = "ad"
    ENTRA_ID = "entra_id"
    OIDC = "oidc"
    SAML = "saml"


class RoleName(StrEnum):
    SUPER_ADMIN = "SuperAdmin"
    TENANT_ADMIN = "TenantAdmin"
    ADMIN = "Admin"
    OPERATOR = "Operator"
    AUDITOR = "Auditor"
    READ_ONLY = "ReadOnly"


class DeviceStatus(StrEnum):
    UNREGISTERED = "unregistered"
    REGISTERED = "registered"
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class ConnectionStatus(StrEnum):
    UNKNOWN = "unknown"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class HARole(StrEnum):
    MASTER = "master"
    BACKUP = "backup"
    STANDALONE = "standalone"


class CertificateStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class RuleAction(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    REJECT = "reject"


class RuleDirection(StrEnum):
    IN = "in"
    OUT = "out"


class AliasType(StrEnum):
    HOST = "host"
    NETWORK = "network"
    PORT = "port"
    URL = "url"
    MAC = "mac"
    NESTED = "nested"


class NatType(StrEnum):
    PORT_FORWARD = "port_forward"
    OUTBOUND = "outbound"
    ONE_TO_ONE = "one_to_one"


class DnsRecordType(StrEnum):
    A = "A"
    AAAA = "AAAA"
    CNAME = "CNAME"
    MX = "MX"
    TXT = "TXT"
    SRV = "SRV"
    PTR = "PTR"
    NS = "NS"


class PolicyKind(StrEnum):
    FIREWALL = "firewall"
    NAT = "nat"
    VPN = "vpn"
    VLAN = "vlan"
    INTERFACE = "interface"
    ROUTING = "routing"
    COMPLIANCE = "compliance"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class PolicyStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    REVIEW = "review"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    ARCHIVED = "archived"


class DeploymentStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    DEPLOYING = "deploying"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class GitProvider(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"
    AZURE_DEVOPS = "azure_devops"
    GENERIC = "generic"


class GitAuthType(StrEnum):
    TOKEN = "token"
    SSH = "ssh"
    OAUTH = "oauth"


class ChangeStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ChangeType(StrEnum):
    FIREWALL = "firewall_rule"
    NAT = "nat"
    VPN = "vpn"
    TEMPLATE = "template"
    CONFIG = "config"
    POLICY = "policy"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TopologyType(StrEnum):
    HUB_SPOKE = "hub_spoke"
    FULL_MESH = "full_mesh"
    REGIONAL_HUB = "regional_hub"


class VpnProtocol(StrEnum):
    WIREGUARD = "wireguard"
    IPSEC = "ipsec"
    OPENVPN = "openvpn"


class HaNodeRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class TunnelStatus(StrEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    DOWN = "down"
    ERROR = "error"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class SteeringStrategy(StrEnum):
    LOWEST_LATENCY = "lowest_latency"
    LOWEST_LOSS = "lowest_loss"
    LOWEST_COST = "lowest_cost"
    APPLICATION = "application"
    WEIGHTED = "weighted"
    FAILOVER = "failover"


class ZtpStatus(StrEnum):
    PENDING = "pending"
    ENROLLED = "enrolled"
    PROVISIONING = "provisioning"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"

    REVOKED = "revoked"


class DiscoveryMethod(StrEnum):
    DHCP = "dhcp"
    DNS = "dns"
    HTTPS = "https"
    TOKEN = "token"
    CERTIFICATE = "certificate"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackupType(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    PRE_UPGRADE = "pre_upgrade"
    PRE_CHANGE = "pre_change"
    AUTO = "auto"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class NotificationType(StrEnum):
    ALERT = "alert"
    INFO = "info"
    WARNING = "warning"
    SUCCESS = "success"
    ERROR = "error"


class AuditResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class DriftStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    REMEDIATED = "remediated"
    IGNORED = "ignored"


class ComplianceFramework(StrEnum):
    CIS = "cis"
    ISO27001 = "iso27001"
    NIS2 = "nis2"
    PCI_DSS = "pci_dss"
    SOC2 = "soc2"


class ComplianceStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class ReportKind(StrEnum):
    FLEET = "fleet"
    COMPLIANCE = "compliance"
    TRAFFIC = "traffic"
    ALERTS = "alerts"


class ReportStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class MaintenanceTarget(StrEnum):
    FLEET = "fleet"
    DEVICE = "device"
    SITE = "site"
    GROUP = "group"


class MetricType(StrEnum):
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    LOAD = "load"
    INTERFACE = "interface"
    TRAFFIC = "traffic"
    GATEWAY = "gateway"
    VPN = "vpn"
    CARP = "carp"
    UPTIME = "uptime"
    SESSIONS = "sessions"


class TemplateKind(StrEnum):
    CONFIG = "config"
    POLICY = "policy"
    ZTP = "ztp"


class TaskKind(StrEnum):
    BACKUP = "backup"
    COMPLIANCE_SCAN = "compliance_scan"
    FIRMWARE_UPGRADE = "firmware_upgrade"
    POLICY_DEPLOY = "policy_deploy"
    DRIFT_SCAN = "drift_scan"
    METRIC_COLLECT = "metric_collect"
    CUSTOM = "custom"
    REPORT = "report"
