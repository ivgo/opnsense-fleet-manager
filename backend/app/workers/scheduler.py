"""Tenant-defined cron schedules plus the safe ``ofme.tasks.custom`` executor."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.models.operations import Task
from app.workers.base import execute_task
from app.workers.celery_app import celery_app
from app.workers.dispatch import (
    ALL_TASK_NAMES,
    TASK_CUSTOM,
    TASK_FOR_KIND,
    enqueue,
)

log = get_logger("ofme.workers.scheduler")

RETRYABLE = (UpstreamError, OperationalError, ConnectionError, TimeoutError)

# Deliberately tiny registry: custom tasks never execute arbitrary shell commands.
CUSTOM_ACTIONS = {"noop", "echo", "touch"}


def _next_run(cron: str, reference: datetime | None = None) -> datetime | None:
    try:
        if not croniter.is_valid(cron):
            return None
        return croniter(cron, reference or datetime.now(UTC)).get_next(datetime)
    except (ValueError, KeyError):
        return None


def _task_name(task: Task) -> str | None:
    payload = task.payload if isinstance(task.payload, dict) else {}
    requested = payload.get("task_name")
    if isinstance(requested, str) and requested in ALL_TASK_NAMES and requested != TASK_CUSTOM:
        return requested
    mapped = TASK_FOR_KIND.get(task.kind)
    if mapped == TASK_CUSTOM:
        return None
    return mapped


async def _scheduler_tick(session: AsyncSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    due = list(
        (
            await session.execute(
                select(Task).where(
                    Task.enabled.is_(True),
                    Task.next_run_at.is_not(None),
                    Task.next_run_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )

    dispatched: list[dict[str, str]] = []
    skipped: list[str] = []
    for task in due:
        task_name = _task_name(task)
        if task_name is None:
            skipped.append(str(task.id))
            task.last_run_at = now
            task.next_run_at = _next_run(task.cron, now)
            continue

        try:
            job = await enqueue(
                session,
                tenant_id=task.tenant_id,
                task_name=task_name,
                params={**(task.payload or {}), "task_id": str(task.id)},
                actor_id=task.created_by,
            )
        except UpstreamError as exc:
            log.error("scheduler.enqueue_failed", task=str(task.id), error=str(exc))
            task.next_run_at = _next_run(task.cron, now)
            continue

        task.last_run_at = now
        task.next_run_at = _next_run(task.cron, now)
        dispatched.append({"task_id": str(task.id), "job_id": str(job.id), "task_name": task_name})

    if due:
        await session.commit()
    return {"due": len(due), "dispatched": dispatched, "skipped": skipped}


async def _custom(
    session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]
) -> dict[str, Any]:
    if params.get("scheduler_tick"):
        return await _scheduler_tick(session)

    action = str(params.get("action", "noop"))
    if action not in CUSTOM_ACTIONS:
        raise UpstreamError(f"Unsupported custom action '{action}'")

    if action == "touch":
        from app.services.audit import AuditService

        if tenant_id is None:
            raise UpstreamError("A tenant is required for the touch action")
        await AuditService(session).record(
            action="task.custom_executed",
            resource_type="Task",
            resource_id=params.get("task_id"),
            tenant_id=tenant_id,
            metadata={"action": action, "params": params},
        )
        await session.commit()

    return {
        "action": action,
        "payload": params,
        "executed_at": datetime.now(UTC).isoformat(),
        "tenant_id": str(tenant_id) if tenant_id else None,
    }


@celery_app.task(
    bind=True,
    name=TASK_CUSTOM,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=2,
)
def custom(self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None) -> dict:  # noqa: ANN001
    return execute_task(TASK_CUSTOM, _custom, job_id=job_id, tenant_id=tenant_id, params=params)


__all__ = ["CUSTOM_ACTIONS", "custom"]
