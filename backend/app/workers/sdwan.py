"""SD-WAN worker: SLA evaluation, steering decisions and stale-link detection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.models.enums import TunnelStatus
from app.services.sdwan import SdwanHealthService, SteeringService
from app.workers.base import execute_task, resolve_tenants
from app.workers.celery_app import celery_app
from app.workers.dispatch import TASK_SDWAN_HEALTH

log = get_logger("ofme.workers.sdwan")

RETRYABLE = (UpstreamError, OperationalError, ConnectionError, TimeoutError)
STALE_FACTOR = 3


async def _sweep(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    from app.repositories import UnitOfWork

    totals: dict[str, int] = {"tenants": 0, "topologies": 0, "failovers": 0, "stale_links": 0}
    stale_after = int(params.get("stale_after_seconds", settings.HEARTBEAT_INTERVAL_SECONDS * STALE_FACTOR))
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after)

    for tid in await resolve_tenants(session, tenant_id):
        uow = UnitOfWork(session, tid)
        topologies, _ = await uow.topologies.list(size=200)
        steering = SteeringService(session, tid)
        health = SdwanHealthService(session, tid)

        for topology in topologies:
            if topology.status == "draft":
                continue
            events = await steering.evaluate_failover(topology.id)
            totals["failovers"] += len(events)
            totals["topologies"] += 1
            for event in events:
                log.warning("sdwan.failover", tenant=str(tid), topology=str(topology.id), **event)

        links, _ = await uow.links.list(size=500)
        for link in links:
            if link.status == TunnelStatus.PENDING:
                continue
            measured = link.measured_at
            if measured is not None and measured.tzinfo is None:
                measured = measured.replace(tzinfo=UTC)
            if link.status == TunnelStatus.ACTIVE and (measured is None or measured < cutoff):
                await health.record(link.id, status=TunnelStatus.DOWN)
                totals["stale_links"] += 1
                log.warning(
                    "sdwan.link_stale",
                    tenant=str(tid),
                    link=str(link.id),
                    measured_at=measured.isoformat() if measured else None,
                )

        await session.commit()
        totals["tenants"] += 1

    return totals


@celery_app.task(
    bind=True,
    name=TASK_SDWAN_HEALTH,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=2,
)
def health_sweep(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    return execute_task(TASK_SDWAN_HEALTH, _sweep, job_id=job_id, tenant_id=tenant_id, params=params)


__all__ = ["health_sweep"]
