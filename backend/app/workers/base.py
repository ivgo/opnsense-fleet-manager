"""Shared Celery task plumbing: isolated engine, job bookkeeping, tenant fan-out."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import JobStatus, TenantStatus
from app.models.identity import Tenant
from app.models.operations import Job
from app.observability.metrics import observe_job

log = get_logger("ofme.workers")

Handler = Callable[[AsyncSession, uuid.UUID | None, dict[str, Any]], Awaitable[dict[str, Any]]]


@asynccontextmanager
async def worker_session() -> AsyncIterator[AsyncSession]:
    """Create a short-lived engine so no connection is shared across event loops.

    Celery prefork workers execute each task with ``asyncio.run``; reusing the API
    engine would hand asyncpg connections to a foreign loop.
    """
    engine = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        pool_pre_ping=True,
        echo=False,
    )
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    try:
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
    finally:
        await engine.dispose()


async def resolve_tenants(session: AsyncSession, tenant_id: uuid.UUID | None) -> list[uuid.UUID]:
    """Return the explicit tenant, or every active tenant for platform-wide sweeps."""
    if tenant_id is not None:
        return [tenant_id]
    rows = await session.execute(
        select(Tenant.id).where(Tenant.status == TenantStatus.ACTIVE, Tenant.deleted_at.is_(None))
    )
    return list(rows.scalars().all())


def merge_counts(target: dict[str, int], addition: dict[str, Any]) -> dict[str, int]:
    for key, value in addition.items():
        if isinstance(value, int | float):
            target[key] = target.get(key, 0) + int(value)
    return target


async def _start_job(session: AsyncSession, job_id: uuid.UUID | None) -> Job | None:
    if job_id is None:
        return None
    job = await session.get(Job, job_id)
    if job is None:
        log.warning("worker.job_missing", job=str(job_id))
        return None
    if job.status == JobStatus.CANCELLED:
        return job
    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(UTC)
    job.progress = 5
    job.error = None
    await session.commit()
    return job


async def _finish_job(
    session: AsyncSession,
    job_id: uuid.UUID | None,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if job_id is None:
        return
    job = await session.get(Job, job_id)
    if job is None:
        return
    if job.status == JobStatus.CANCELLED:
        return
    job.finished_at = datetime.now(UTC)
    job.progress = 100
    if error is None:
        job.status = JobStatus.COMPLETED
        job.result = result or {}
        job.error = None
    else:
        job.status = JobStatus.FAILED
        job.error = error[:8000]
    await session.commit()


async def _execute(
    task_name: str,
    handler: Handler,
    job_id: uuid.UUID | None,
    tenant_id: uuid.UUID | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    async with worker_session() as session:
        job = await _start_job(session, job_id)
        if job is not None and job.status == JobStatus.CANCELLED:
            log.info("worker.job_cancelled", task=task_name, job=str(job_id))
            return {"cancelled": True}
        try:
            result = await handler(session, tenant_id, params)
        except Exception as exc:
            await session.rollback()
            await _finish_job(session, job_id, error=f"{type(exc).__name__}: {exc}")
            raise
        await _finish_job(session, job_id, result=result)
        return result


def execute_task(
    task_name: str,
    handler: Handler,
    *,
    job_id: str | None = None,
    tenant_id: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run an async handler inside a fresh event loop and update the Job row."""
    started = time.perf_counter()
    parsed_job = uuid.UUID(job_id) if job_id else None
    parsed_tenant = uuid.UUID(tenant_id) if tenant_id else None
    payload = params or {}
    try:
        result = asyncio.run(_execute(task_name, handler, parsed_job, parsed_tenant, payload))
    except Exception:
        observe_job(task_name, JobStatus.FAILED.value, time.perf_counter() - started)
        log.exception("worker.task_failed", task=task_name, job=job_id, tenant=tenant_id)
        raise
    duration = time.perf_counter() - started
    observe_job(task_name, JobStatus.COMPLETED.value, duration)
    log.info(
        "worker.task_completed",
        task=task_name,
        job=job_id,
        tenant=tenant_id,
        duration_ms=round(duration * 1000, 2),
    )
    return result


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_uuid_list(values: Iterable[Any] | None) -> list[uuid.UUID]:
    if not values:
        return []
    result: list[uuid.UUID] = []
    for value in values:
        result.append(value if isinstance(value, uuid.UUID) else uuid.UUID(str(value)))
    return result


__all__ = [
    "Handler",
    "as_uuid_list",
    "execute_task",
    "merge_counts",
    "resolve_tenants",
    "utcnow",
    "worker_session",
]
