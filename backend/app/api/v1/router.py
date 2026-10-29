"""Version 1 API router: composes every endpoint module."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    agent,
    alerts,
    aliases,
    audit,
    auth,
    backups,
    bulk,
    compliance,
    configuration,
    devices,
    git,
    groups,
    ha,
    health,
    interfaces,
    inventory,
    jobs,
    maintenance,
    metrics,
    nat,
    networking,
    policies,
    reports,
    rules,
    sdwan,
    sites,
    templates,
    tenants,
    users,
    ztp,
)

api_router = APIRouter()

# --------------------------------------------------------------------------- platform
api_router.include_router(health.router)
api_router.include_router(auth.router)

# --------------------------------------------------------------------------- identity & tenancy
api_router.include_router(tenants.router)
api_router.include_router(users.users_router)
api_router.include_router(users.roles_router)
api_router.include_router(users.permissions_router)
api_router.include_router(users.api_keys_router)

# --------------------------------------------------------------------------- inventory
api_router.include_router(sites.router)
api_router.include_router(groups.router)
api_router.include_router(devices.router)
api_router.include_router(devices.certificates_router)
api_router.include_router(bulk.router)
api_router.include_router(ha.router)

# --------------------------------------------------------------------------- configuration
api_router.include_router(rules.router)
api_router.include_router(aliases.router)
api_router.include_router(nat.router)
api_router.include_router(interfaces.interfaces_router)
api_router.include_router(interfaces.routes_router)
api_router.include_router(interfaces.vlans_router)
api_router.include_router(networking.dhcp_router)
api_router.include_router(networking.dns_router)
api_router.include_router(configuration.router)
api_router.include_router(templates.router)

# --------------------------------------------------------------------------- GitOps
api_router.include_router(policies.policies_router)
api_router.include_router(policies.deployments_router)
api_router.include_router(policies.drift_router)
api_router.include_router(policies.changes_router)
api_router.include_router(reports.router)
api_router.include_router(git.router)
api_router.include_router(git.webhooks_router)

# --------------------------------------------------------------------------- SD-WAN & ZTP
api_router.include_router(sdwan.router)
api_router.include_router(ztp.router)

# --------------------------------------------------------------------------- operations
api_router.include_router(backups.router)
api_router.include_router(jobs.jobs_router)
api_router.include_router(jobs.tasks_router)
api_router.include_router(alerts.alerts_router)
api_router.include_router(alerts.alert_rules_router)
api_router.include_router(alerts.notifications_router)
api_router.include_router(maintenance.router)
api_router.include_router(metrics.router)
api_router.include_router(inventory.router)

# --------------------------------------------------------------------------- governance & devices
api_router.include_router(audit.router)
api_router.include_router(compliance.router)
api_router.include_router(agent.router)

__all__ = ["api_router"]
