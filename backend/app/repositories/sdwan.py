from __future__ import annotations

import uuid
from datetime import datetime

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
from app.repositories.base import BaseRepository


class TopologyRepository(BaseRepository[SdwanTopology]):
    model = SdwanTopology


class TunnelRepository(BaseRepository[VpnTunnel]):
    model = VpnTunnel
    soft_delete = False

    async def for_topology(self, topology_id: uuid.UUID) -> list[VpnTunnel]:
        stmt = self.query().where(VpnTunnel.topology_id == topology_id).order_by(VpnTunnel.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_device(self, device_id: uuid.UUID) -> list[VpnTunnel]:
        stmt = self.query().where(
            (VpnTunnel.local_device_id == device_id) | (VpnTunnel.remote_device_id == device_id)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class LinkRepository(BaseRepository[SdwanLink]):
    model = SdwanLink
    soft_delete = False

    async def for_topology(self, topology_id: uuid.UUID) -> list[SdwanLink]:
        stmt = self.query().where(SdwanLink.topology_id == topology_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def eligible_for_steering(self, topology_id: uuid.UUID) -> list[SdwanLink]:
        stmt = self.query().where(
            SdwanLink.topology_id == topology_id,
            SdwanLink.status == "active",
            SdwanLink.latency_ms.is_not(None),
        )
        return list((await self.session.execute(stmt)).scalars().all())


class TrafficPolicyRepository(BaseRepository[TrafficPolicy]):
    model = TrafficPolicy
    soft_delete = False


class RouteRepository(BaseRepository[SdwanRoute]):
    model = SdwanRoute
    soft_delete = False

    async def for_device(self, device_id: uuid.UUID) -> list[SdwanRoute]:
        stmt = self.query().where(SdwanRoute.device_id == device_id).order_by(SdwanRoute.metric)
        return list((await self.session.execute(stmt)).scalars().all())

    async def record_measurement(
        self,
        link: SdwanLink,
        *,
        latency_ms: float | None,
        jitter_ms: float | None,
        loss_pct: float | None,
        bandwidth_mbps: float | None = None,
        measured_at: datetime | None = None,
    ) -> SdwanLink:
        if latency_ms is not None:
            link.latency_ms = latency_ms
        if jitter_ms is not None:
            link.jitter_ms = jitter_ms
        if loss_pct is not None:
            link.loss_pct = loss_pct
        if bandwidth_mbps is not None:
            link.bandwidth_mbps = bandwidth_mbps
        link.measured_at = measured_at or datetime.utcnow()
        await self.session.flush()
        return link


class WireGuardKeyRepository(BaseRepository[WireGuardKey]):
    model = WireGuardKey
    soft_delete = False

    async def for_device(self, topology_id: uuid.UUID, device_id: uuid.UUID) -> WireGuardKey | None:
        stmt = self.query().where(
            WireGuardKey.topology_id == topology_id,
            WireGuardKey.device_id == device_id,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def for_topology(self, topology_id: uuid.UUID) -> list[WireGuardKey]:
        stmt = self.query().where(WireGuardKey.topology_id == topology_id).order_by(WireGuardKey.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def all_for_device(self, device_id: uuid.UUID) -> list[WireGuardKey]:
        stmt = self.query().where(WireGuardKey.device_id == device_id)
        return list((await self.session.execute(stmt)).scalars().all())


class OpenVpnCaRepository(BaseRepository[OpenVpnCa]):
    model = OpenVpnCa
    soft_delete = False

    async def for_topology(self, topology_id: uuid.UUID) -> OpenVpnCa | None:
        stmt = self.query().where(OpenVpnCa.topology_id == topology_id)
        return (await self.session.execute(stmt)).scalars().first()


class OpenVpnCertificateRepository(BaseRepository[OpenVpnCertificate]):
    model = OpenVpnCertificate
    soft_delete = False

    async def for_device(self, topology_id: uuid.UUID, device_id: uuid.UUID) -> OpenVpnCertificate | None:
        stmt = self.query().where(
            OpenVpnCertificate.topology_id == topology_id,
            OpenVpnCertificate.device_id == device_id,
        )
        return (await self.session.execute(stmt)).scalars().first()
