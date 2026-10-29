"""Repositories for CARP clusters and member nodes."""

from __future__ import annotations

import uuid

from app.models.ha import HaCluster, HaNode
from app.repositories.base import BaseRepository


class HaClusterRepository(BaseRepository[HaCluster]):
    model = HaCluster


class HaNodeRepository(BaseRepository[HaNode]):
    model = HaNode
    soft_delete = False

    async def for_cluster(self, cluster_id: uuid.UUID) -> list[HaNode]:
        stmt = self.query().where(HaNode.cluster_id == cluster_id).order_by(HaNode.advskew)
        return list((await self.session.execute(stmt)).scalars().all())
