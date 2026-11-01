"""pgBackRest PostgreSQL cluster backup/restore endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    CurrentPrincipal,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.rbac.permissions import P
from app.workers.dispatch import TASK_BACKUP_POSTGRES, enqueue
from app.workers.pgbackrest import TASK_PGBACKREST_EXPIRE, TASK_PGBACKREST_INFO, TASK_PGBACKREST_VERIFY
from app.schemas.common import Message

router = APIRouter(prefix="/pgbackrest", tags=["pgBackRest"])


class PgBackRestBackupRequest:
    backup_type: str = Query("incr", pattern="^(full|diff|incr)$")


@router.post(
    "/backup",
    response_model=Message,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions(P.BACKUP_CREATE))],
    summary="Trigger a pgBackRest backup of the PostgreSQL cluster",
)
async def trigger_backup(
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
    backup_type: str = Query("incr", pattern="^(full|diff|incr)$"),
) -> Message:
    """Trigger a pgBackRest backup of the PostgreSQL cluster.

    - **full**: Full base backup (recommended weekly)
    - **diff**: Differential backup (daily)
    - **incr**: Incremental backup (default, frequent)
    """
    job = await enqueue(
        session,
        tenant_id=tenant_id,
        task_name=TASK_BACKUP_POSTGRES,
        params={"backup_type": backup_type},
        actor_id=principal.user_id,
    )
    return Message(message=f"pgBackRest {backup_type} backup scheduled", detail={"job_id": str(job.id)})


@router.get(
    "/info",
    dependencies=[Depends(require_permissions(P.BACKUP_READ))],
    summary="Get pgBackRest repository information",
)
async def get_info(
    session: SessionDep,
    tenant_id: TenantDep,
) -> dict[str, Any]:
    """Get pgBackRest repository information for the ofme stanza.

    Runs as an async job via the worker (which has docker socket access).
    Returns job ID for polling.
    """
    job = await enqueue(
        session,
        tenant_id=tenant_id,
        task_name=TASK_PGBACKREST_INFO,
        params={},
        actor_id=None,  # read-only operation
    )
    return {
        "job_id": str(job.id),
        "status": job.status.value,
        "message": "pgBackRest info job queued",
    }


@router.post(
    "/verify",
    response_model=Message,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions(P.BACKUP_CREATE))],
    summary="Verify pgBackRest repository integrity",
)
async def verify_repository(
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    """Verify pgBackRest repository integrity via async worker job."""
    job = await enqueue(
        session,
        tenant_id=tenant_id,
        task_name=TASK_PGBACKREST_VERIFY,
        params={},
        actor_id=principal.user_id,
    )
    return Message(
        message="pgBackRest verify job scheduled",
        detail={"job_id": str(job.id)}
    )


@router.post(
    "/expire",
    response_model=Message,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions(P.BACKUP_CREATE))],
    summary="Apply retention policies to pgBackRest repository",
)
async def expire_repository(
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    """Apply retention policies to pgBackRest repository (remove expired backups) via async worker job."""
    job = await enqueue(
        session,
        tenant_id=tenant_id,
        task_name=TASK_PGBACKREST_EXPIRE,
        params={},
        actor_id=principal.user_id,
    )
    return Message(
        message="pgBackRest expire job scheduled",
        detail={"job_id": str(job.id)}
    )


__all__ = ["router"]