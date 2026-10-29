"""RBAC catalogue: canonical permission strings and the system role matrix."""

from __future__ import annotations

from enum import StrEnum

from app.models.enums import RoleName


class P(StrEnum):
    # tenant & identity
    TENANT_READ = "tenant:read"
    TENANT_WRITE = "tenant:write"
    TENANT_DELETE = "tenant:delete"
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_DELETE = "user:delete"
    ROLE_READ = "role:read"
    ROLE_WRITE = "role:write"
    APIKEY_READ = "apikey:read"
    APIKEY_WRITE = "apikey:write"

    # inventory
    SITE_READ = "site:read"
    SITE_WRITE = "site:write"
    GROUP_READ = "group:read"
    GROUP_WRITE = "group:write"
    DEVICE_READ = "device:read"
    DEVICE_WRITE = "device:write"
    DEVICE_DELETE = "device:delete"
    DEVICE_ENROLL = "device:enroll"
    DEVICE_EXEC = "device:exec"
    DEVICE_CREDENTIALS = "device:credentials"
    FIRMWARE_READ = "firmware:read"
    FIRMWARE_UPGRADE = "firmware:upgrade"
    FIRMWARE_REBOOT = "firmware:reboot"
    CERT_READ = "certificate:read"
    CERT_WRITE = "certificate:write"

    # configuration
    RULE_READ = "rule:read"
    RULE_WRITE = "rule:write"
    RULE_DELETE = "rule:delete"
    NAT_READ = "nat:read"
    NAT_WRITE = "nat:write"
    ALIAS_READ = "alias:read"
    ALIAS_WRITE = "alias:write"
    INTERFACE_READ = "interface:read"
    INTERFACE_WRITE = "interface:write"
    ROUTE_READ = "route:read"
    ROUTE_WRITE = "route:write"
    VLAN_READ = "vlan:read"
    VLAN_WRITE = "vlan:write"
    DHCP_READ = "dhcp:read"
    DHCP_WRITE = "dhcp:write"
    DNS_READ = "dns:read"
    DNS_WRITE = "dns:write"

    # templates & policies
    TEMPLATE_READ = "template:read"
    TEMPLATE_WRITE = "template:write"
    POLICY_READ = "policy:read"
    POLICY_WRITE = "policy:write"
    POLICY_VALIDATE = "policy:validate"
    POLICY_APPROVE = "policy:approve"
    POLICY_DEPLOY = "policy:deploy"
    POLICY_ROLLBACK = "policy:rollback"
    GIT_READ = "git:read"
    GIT_WRITE = "git:write"

    # sd-wan
    SDWAN_READ = "sdwan:read"
    SDWAN_WRITE = "sdwan:write"
    SDWAN_DEPLOY = "sdwan:deploy"

    # high availability
    HA_READ = "ha:read"
    HA_WRITE = "ha:write"

    # ztp
    ZTP_READ = "ztp:read"
    ZTP_WRITE = "ztp:write"
    ZTP_APPROVE = "ztp:approve"

    # operations
    BACKUP_READ = "backup:read"
    BACKUP_CREATE = "backup:create"
    BACKUP_RESTORE = "backup:restore"
    BACKUP_DELETE = "backup:delete"
    JOB_READ = "job:read"
    JOB_CANCEL = "job:cancel"
    TASK_READ = "task:read"
    TASK_WRITE = "task:write"
    ALERT_READ = "alert:read"
    ALERT_ACK = "alert:ack"
    ALERT_WRITE = "alert:write"
    METRIC_READ = "metric:read"
    INVENTORY_READ = "inventory:read"
    INVENTORY_WRITE = "inventory:write"
    REPORT_READ = "report:read"
    REPORT_WRITE = "report:write"

    # governance
    AUDIT_READ = "audit:read"
    COMPLIANCE_READ = "compliance:read"
    COMPLIANCE_RUN = "compliance:run"
    COMPLIANCE_REMEDIATE = "compliance:remediate"
    CHANGE_READ = "change:read"
    CHANGE_WRITE = "change:write"
    CHANGE_APPROVE = "change:approve"

    # platform
    PLATFORM_SETTINGS = "platform:settings"
    LICENSE_MANAGE = "license:manage"


READ_ONLY: frozenset[P] = frozenset(
    {
        P.TENANT_READ,
        P.USER_READ,
        P.ROLE_READ,
        P.SITE_READ,
        P.GROUP_READ,
        P.DEVICE_READ,
        P.CERT_READ,
        P.RULE_READ,
        P.NAT_READ,
        P.ALIAS_READ,
        P.INTERFACE_READ,
        P.ROUTE_READ,
        P.VLAN_READ,
        P.DHCP_READ,
        P.DNS_READ,
        P.TEMPLATE_READ,
        P.POLICY_READ,
        P.GIT_READ,
        P.SDWAN_READ,
        P.HA_READ,
        P.ZTP_READ,
        P.BACKUP_READ,
        P.JOB_READ,
        P.TASK_READ,
        P.ALERT_READ,
        P.METRIC_READ,
        P.INVENTORY_READ,
        P.COMPLIANCE_READ,
        P.CHANGE_READ,
        P.FIRMWARE_READ,
        P.REPORT_READ,
    }
)

AUDITOR: frozenset[P] = READ_ONLY | {P.AUDIT_READ, P.COMPLIANCE_RUN, P.APIKEY_READ}

OPERATOR: frozenset[P] = READ_ONLY | {
    P.DEVICE_WRITE,
    P.DEVICE_EXEC,
    P.RULE_WRITE,
    P.NAT_WRITE,
    P.ALIAS_WRITE,
    P.INTERFACE_WRITE,
    P.ROUTE_WRITE,
    P.VLAN_WRITE,
    P.DHCP_WRITE,
    P.DNS_WRITE,
    P.BACKUP_CREATE,
    P.JOB_CANCEL,
    P.ALERT_ACK,
    P.POLICY_VALIDATE,
    P.COMPLIANCE_RUN,
    P.CHANGE_WRITE,
    P.HA_WRITE,
    P.ZTP_READ,
    P.FIRMWARE_UPGRADE,
    P.FIRMWARE_REBOOT,
    P.REPORT_WRITE,
}

ADMIN: frozenset[P] = OPERATOR | {
    P.USER_READ,
    P.USER_WRITE,
    P.ROLE_READ,
    P.SITE_WRITE,
    P.GROUP_WRITE,
    P.DEVICE_DELETE,
    P.DEVICE_ENROLL,
    P.DEVICE_CREDENTIALS,
    P.CERT_WRITE,
    P.RULE_DELETE,
    P.TEMPLATE_WRITE,
    P.POLICY_WRITE,
    P.POLICY_APPROVE,
    P.POLICY_DEPLOY,
    P.POLICY_ROLLBACK,
    P.GIT_WRITE,
    P.SDWAN_WRITE,
    P.SDWAN_DEPLOY,
    P.ZTP_WRITE,
    P.ZTP_APPROVE,
    P.BACKUP_DELETE,
    P.BACKUP_RESTORE,
    P.TASK_WRITE,
    P.ALERT_WRITE,
    P.COMPLIANCE_REMEDIATE,
    P.CHANGE_APPROVE,
    P.APIKEY_READ,
    P.APIKEY_WRITE,
}

TENANT_ADMIN: frozenset[P] = ADMIN | {P.TENANT_WRITE, P.USER_DELETE}

SUPER_ADMIN: frozenset[P] = frozenset(P)


ROLE_MATRIX: dict[RoleName, frozenset[P]] = {
    RoleName.SUPER_ADMIN: SUPER_ADMIN,
    RoleName.TENANT_ADMIN: TENANT_ADMIN,
    RoleName.ADMIN: ADMIN,
    RoleName.OPERATOR: OPERATOR,
    RoleName.AUDITOR: AUDITOR,
    RoleName.READ_ONLY: READ_ONLY,
}


def permissions_for(role: RoleName) -> list[str]:
    return sorted(p.value for p in ROLE_MATRIX[role])


def role_descriptions() -> dict[RoleName, str]:
    return {
        RoleName.SUPER_ADMIN: "Platform owner. Cross-tenant access, licensing and platform settings.",
        RoleName.TENANT_ADMIN: "Full control of a single tenant, including users and tenant settings.",
        RoleName.ADMIN: "Network administration: devices, policies, SD-WAN, backups.",
        RoleName.OPERATOR: "Day-to-day operations: rules, monitoring, backups, alerts.",
        RoleName.AUDITOR: "Read-only plus audit trail and compliance reporting.",
        RoleName.READ_ONLY: "Read-only visibility across the tenant.",
    }
