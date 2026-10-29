"""Configuration orchestration: preview, diff and apply of desired state to devices."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import (
    CurrentPrincipal,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.integrations.opnsense.client import client_for
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.config import (
    ApplyRequest,
    ApplyResult,
    ConfigChange,
    ConfigDiff,
)
from app.services.configuration import (
    ConfigurationDeployer,
    is_managed_description,
    managed_description,
    rule_payload,
)
from app.services.devices import DeviceService

router = APIRouter(prefix="/configuration", tags=["Configuration"])

DEFAULT_APPLY_RESOURCES = ["rules"]


@router.post(
    "/apply",
    response_model=list[ApplyResult],
    dependencies=[Depends(require_permissions(P.POLICY_DEPLOY))],
    summary="Apply managed configuration to one or more devices",
    description=(
        "Runs the requested deployers (`rules`, `nat`, `vlans`, `dhcp`, `dns`) for every "
        "device. Each deployer is idempotent and prunes OFME-managed objects that are no "
        "longer part of the desired state."
    ),
)
async def apply_configuration(
    payload: ApplyRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> list[ApplyResult]:
    deployer = ConfigurationDeployer(session, tenant_id, principal.user_id)
    resources = payload.resources or DEFAULT_APPLY_RESOURCES
    results: list[ApplyResult] = []
    for device_id in payload.device_ids:
        try:
            outcome = await deployer.apply_resources(
                device_id,
                resources,
                dry_run=payload.dry_run,
                apply=payload.reload and not payload.dry_run,
            )
            details = outcome.get("details", {})
            applied = sum(
                int(detail.get("created", 0)) + int(detail.get("updated", 0)) for detail in details.values()
            )
            results.append(
                ApplyResult(
                    device_id=device_id,
                    success=True,
                    applied=applied,
                    message="dry-run" if payload.dry_run else "applied",
                    details=details,
                )
            )
        except Exception as exc:  # noqa: BLE001 - per-device failures are reported, not raised
            results.append(
                ApplyResult(
                    device_id=device_id,
                    success=False,
                    errors=[str(exc)],
                    message="failed",
                )
            )
    return results


@router.get(
    "/diff/{device_id}",
    response_model=ConfigDiff,
    dependencies=[Depends(require_permissions(P.DEVICE_READ))],
    summary="Diff managed rules against the device's live rule set",
)
async def configuration_diff(device_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> ConfigDiff:
    devices = DeviceService(session, tenant_id)
    device = await devices.get(device_id)
    base_url, key, secret = await devices.credentials(device)
    async with client_for(base_url, key, secret) as client:
        current = await client.search_rules()

    live_rows = [row for row in (current.get("rows") or []) if isinstance(row, dict)]
    live: dict[str, dict[str, Any]] = {}
    for row in live_rows:
        name = row.get("description") or row.get("descr") or row.get("uuid")
        if name:
            live[str(name)] = row

    managed = await UnitOfWork(session, tenant_id).rules.for_device(device_id)
    desired = {managed_description(rule.name): rule for rule in managed}

    additions: list[ConfigChange] = []
    removals: list[ConfigChange] = []
    modifications: list[ConfigChange] = []

    for name, rule in desired.items():
        target = rule_payload(rule)
        if name not in live:
            additions.append(ConfigChange(resource="firewall_rule", operation="add", payload=target))
            continue
        current_payload = live[name]
        changes = {
            field: {"before": current_payload.get(field), "after": value}
            for field, value in target.items()
            if field in {"action", "interface", "protocol", "description", "enabled", "log"}
            and str(current_payload.get(field, "")) != str(value)
        }
        if changes:
            modifications.append(
                ConfigChange(
                    resource="firewall_rule",
                    operation="modify",
                    payload={"name": name, "changes": changes},
                )
            )

    for name, row in live.items():
        if name not in desired and is_managed_description(name):
            removals.append(
                ConfigChange(
                    resource="firewall_rule",
                    operation="remove",
                    payload={"name": name, "uuid": row.get("uuid")},
                )
            )

    return ConfigDiff(
        device_id=device_id,
        generated_at=datetime.now(UTC),
        additions=additions,
        removals=removals,
        modifications=modifications,
        conflicts=[],
        summary={
            "device": device.name,
            "managed_rules": len(desired),
            "live_rules": len(live),
            "additions": len(additions),
            "removals": len(removals),
            "modifications": len(modifications),
        },
    )


@router.get(
    "/preview/{device_id}",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.DEVICE_READ))],
    summary="Render the managed rule payloads without touching the device",
)
async def preview_configuration(
    device_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> list[dict]:
    rules = await UnitOfWork(session, tenant_id).rules.for_device(device_id)
    return [rule_payload(rule) for rule in rules]
