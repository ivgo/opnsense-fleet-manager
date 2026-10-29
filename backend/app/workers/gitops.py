"""GitOps worker: pull policy repositories and reconcile policy documents."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.repositories import UnitOfWork
from app.services.git_sync import GitSyncService
from app.workers.base import execute_task, resolve_tenants
from app.workers.celery_app import celery_app
from app.workers.dispatch import TASK_GIT_SYNC

log = get_logger("ofme.workers.gitops")

RETRYABLE = (UpstreamError, OperationalError, ConnectionError, TimeoutError)


async def _sync(session: AsyncSession, tenant_id: uuid.UUID | None, params: dict[str, Any]) -> dict[str, Any]:
    branch = params.get("branch")
    requested = params.get("repository_id")
    results: list[dict[str, Any]] = []

    for tid in await resolve_tenants(session, tenant_id):
        uow = UnitOfWork(session, tid)
        if requested:
            repository_ids = [uuid.UUID(str(requested))]
        else:
            repositories, _ = await uow.git_repos.list(size=200)
            repository_ids = [repository.id for repository in repositories if repository.status == "active"]

        service = GitSyncService(session, tid)
        for repository_id in repository_ids:
            try:
                outcome = await service.sync_repository(repository_id, branch=branch)
            except Exception as exc:  # noqa: BLE001 - one repository must not stop the sweep
                log.warning(
                    "gitops.sync_failed",
                    tenant=str(tid),
                    repository=str(repository_id),
                    error=str(exc),
                )
                results.append({"repository_id": str(repository_id), "error": f"{type(exc).__name__}: {exc}"})
                continue
            payload = asdict(outcome)
            payload["repository_id"] = str(outcome.repository_id)
            payload["tenant_id"] = str(tid)
            results.append(payload)
            log.info(
                "gitops.sync_completed",
                tenant=str(tid),
                repository=str(repository_id),
                updated=outcome.updated,
                invalid=outcome.invalid,
            )

    return {
        "repositories": results,
        "count": len(results),
        "updated": sum(int(item.get("updated", 0)) for item in results),
        "invalid": sum(int(item.get("invalid", 0)) for item in results),
        "errors": sum(1 for item in results if item.get("error")),
    }


@celery_app.task(
    bind=True,
    name=TASK_GIT_SYNC,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def sync_repository(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    return execute_task(TASK_GIT_SYNC, _sync, job_id=job_id, tenant_id=tenant_id, params=params)


__all__ = ["sync_repository"]
