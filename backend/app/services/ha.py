"""CARP high-availability orchestration: configuration, status and failover."""

from __future__ import annotations

import ipaddress
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret
from app.db.base import utcnow
from app.integrations.opnsense.client import client_for
from app.models.enums import HaNodeRole
from app.models.ha import HaCluster, HaNode
from app.repositories import UnitOfWork
from app.schemas.ha import HaClusterCreate, HaClusterUpdate, HaFailoverResult
from app.services.audit import AuditService
from app.services.devices import DeviceService

log = get_logger("ofme.ha")


class HaService:
    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.uow = UnitOfWork(session, tenant_id)
        self.devices = DeviceService(session, tenant_id, actor_id)
        self.audit = AuditService(session)
        self.actor_id = actor_id

    # ------------------------------------------------------------------ CRUD
    async def create(self, payload: HaClusterCreate) -> HaCluster:
        self._validate_ip(payload.virtual_ip)
        nodes = await self._build_nodes(payload.nodes)
        cluster = HaCluster(
            tenant_id=self.tenant_id,
            name=payload.name,
            description=payload.description,
            site_id=payload.site_id,
            virtual_ip=payload.virtual_ip,
            interface=payload.interface,
            vhid=payload.vhid,
            advbase=payload.advbase,
            password_encrypted=encrypt_secret(payload.password) if payload.password else None,
            enabled=payload.enabled,
            created_by=self.actor_id,
        )
        cluster.nodes = nodes
        self.session.add(cluster)
        await self.session.flush()
        await self.audit.record(
            action="ha.cluster_created",
            resource_type="HaCluster",
            resource_id=cluster.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": cluster.name, "vhid": cluster.vhid, "nodes": len(nodes)},
        )
        return cluster

    async def update(self, cluster_id: uuid.UUID, payload: HaClusterUpdate) -> HaCluster:
        cluster = await self.uow.ha_clusters.get_or_404(cluster_id)
        data = payload.model_dump(exclude_unset=True)
        if "virtual_ip" in data and data["virtual_ip"]:
            self._validate_ip(data["virtual_ip"])
        password = data.pop("password", None)
        if password:
            cluster.password_encrypted = encrypt_secret(password)
        for field, value in data.items():
            setattr(cluster, field, value)
        await self.session.flush()
        await self.audit.record(
            action="ha.cluster_updated",
            resource_type="HaCluster",
            resource_id=cluster.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after=payload.model_dump(exclude_unset=True, exclude={"password"}),
        )
        return cluster

    async def delete(self, cluster_id: uuid.UUID) -> None:
        cluster = await self.uow.ha_clusters.get_or_404(cluster_id)
        await self.uow.ha_clusters.delete(cluster)
        await self.audit.record(
            action="ha.cluster_deleted",
            resource_type="HaCluster",
            resource_id=cluster.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before={"name": cluster.name, "vhid": cluster.vhid},
        )

    # ------------------------------------------------------------------ status
    async def refresh(self, cluster_id: uuid.UUID) -> HaCluster:
        cluster = await self.uow.ha_clusters.get_or_404(cluster_id)
        statuses: set[str] = set()
        for node in cluster.nodes:
            device = await self.uow.devices.get(node.device_id)
            if device is None:
                node.status = "unknown"
                continue
            try:
                base_url, key, secret = await self.devices.credentials(device)
                async with client_for(base_url, key, secret) as client:
                    payload = await client.carp_status()
            except Exception as exc:  # noqa: BLE001 - status polling is best effort
                node.status = "unreachable"
                node.details = {"error": str(exc)}
                log.warning("ha.status_failed", cluster=str(cluster.id), device=str(device.id))
                continue
            row = self._match_row(payload or {}, cluster)
            if row is None:
                node.status = "not_configured"
                continue
            node.status = str(row.get("status") or row.get("state") or "unknown").lower()
            node.vip_uuid = str(row.get("uuid")) if row.get("uuid") else node.vip_uuid
            node.last_seen_at = utcnow()
            node.details = row
            statuses.add(node.status)
        cluster.sync_status = self._sync_status(statuses)
        cluster.last_sync_at = utcnow()
        await self.session.flush()
        await self.audit.record(
            action="ha.status_refreshed",
            resource_type="HaCluster",
            resource_id=cluster.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"sync_status": cluster.sync_status},
        )
        await self.session.commit()
        return cluster

    async def failover(self, cluster_id: uuid.UUID) -> HaFailoverResult:
        cluster = await self.uow.ha_clusters.get_or_404(cluster_id)
        nodes = sorted(cluster.nodes, key=lambda node: (node.role != HaNodeRole.PRIMARY, node.advskew))
        if len(nodes) < 2:
            raise BadRequestError("Failover requires at least two cluster nodes")
        primary, secondary = nodes[0], nodes[1]
        if primary.role != HaNodeRole.PRIMARY:
            raise BadRequestError("Cluster has no primary node to fail over from")

        await self._move_node(cluster, primary, advskew=100, role=HaNodeRole.SECONDARY)
        await self._move_node(cluster, secondary, advskew=0, role=HaNodeRole.PRIMARY)
        cluster.sync_status = "failover_requested"
        cluster.last_sync_at = utcnow()
        await self.session.flush()
        await self.audit.record(
            action="ha.failover",
            resource_type="HaCluster",
            resource_id=cluster.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "promoted": str(secondary.device_id),
                "demoted": str(primary.device_id),
            },
        )
        await self.session.commit()
        return HaFailoverResult(
            cluster_id=cluster.id,
            promoted_device_id=secondary.device_id,
            demoted_device_id=primary.device_id,
            applied=True,
            nodes=[self._node_out(node) for node in cluster.nodes],
        )

    # ------------------------------------------------------------------ internals
    async def _move_node(self, cluster: HaCluster, node: HaNode, *, advskew: int, role: HaNodeRole) -> None:
        device = await self.uow.devices.get(node.device_id)
        if device is None:
            raise BadRequestError("Cluster node references a missing device")
        base_url, key, secret = await self.devices.credentials(device)
        async with client_for(base_url, key, secret) as client:
            current = await client.search_vips()
            row = self._match_row(current, cluster)
            if row is None or not row.get("uuid"):
                raise BadRequestError(f"CARP VIP {cluster.vhid} is not configured on device {device.name}")
            payload = dict(row)
            payload.update(
                {
                    "vhid": str(cluster.vhid),
                    "interface": cluster.interface,
                    "advskew": str(advskew),
                    "advbase": str(cluster.advbase),
                    "descr": cluster.name,
                }
            )
            if cluster.password_encrypted:
                payload["password"] = decrypt_secret(cluster.password_encrypted)
            await client.set_vip(str(row["uuid"]), payload)
            await client.apply_vips()
        node.vip_uuid = str(row["uuid"])
        node.advskew = advskew
        node.role = role
        node.status = "master" if role == HaNodeRole.PRIMARY else "backup"
        node.last_seen_at = utcnow()

    async def _build_nodes(self, payloads: list[Any]) -> list[HaNode]:
        nodes: list[HaNode] = []
        seen: set[uuid.UUID] = set()
        for index, payload in enumerate(payloads):
            if payload.device_id in seen:
                raise BadRequestError("A device can only appear once in a cluster")
            seen.add(payload.device_id)
            device = await self.uow.devices.get(payload.device_id)
            if device is None:
                raise BadRequestError("Cluster node references a missing device")
            role = payload.role
            if index == 0 and not any(item.role == HaNodeRole.PRIMARY for item in payloads):
                role = HaNodeRole.PRIMARY
            nodes.append(
                HaNode(
                    tenant_id=self.tenant_id,
                    device_id=payload.device_id,
                    role=role,
                    advskew=payload.advskew,
                )
            )
        if sum(1 for node in nodes if node.role == HaNodeRole.PRIMARY) > 1:
            raise BadRequestError("A CARP cluster can only have one primary node")
        return nodes

    @staticmethod
    def _validate_ip(value: str) -> None:
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise BadRequestError(f"Invalid CARP virtual IP '{value}'") from exc

    @staticmethod
    def _match_row(payload: dict[str, Any], cluster: HaCluster) -> dict[str, Any] | None:
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("rows") or payload.get("vips") or []
            if isinstance(rows, dict):
                rows = list(rows.values())
        else:
            rows = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            vhid = row.get("vhid") or row.get("vhid_local")
            if vhid is not None and str(vhid) == str(cluster.vhid):
                return row
            subnet = str(row.get("subnet") or row.get("network") or "")
            if subnet.split("/")[0] == cluster.virtual_ip:
                return row
        return None

    @staticmethod
    def _sync_status(statuses: set[str]) -> str:
        if not statuses:
            return "unknown"
        if "master" in statuses and "backup" in statuses:
            return "in_sync"
        return "degraded"

    @staticmethod
    def _node_out(node: HaNode) -> Any:
        from app.schemas.ha import HaNodeOut

        return HaNodeOut.model_validate(node)
