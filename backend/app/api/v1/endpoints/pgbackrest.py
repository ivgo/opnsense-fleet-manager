"""pgBackRest PostgreSQL cluster backup/restore endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
    """Get pgBackRest repository information for the ofme stanza."""
    from app.workers.pgbackrest import _run_info

    try:
        result = await session.run_in_threadpool(_run_info)
        return {
            "command": result["command"],
            "output": result["stdout"],
            "status": "ok",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"pgBackRest info failed: {exc}")


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
    """Verify pgBackRest repository integrity."""
    from app.workers.pgbackrest import _run_verify

    try:
        result = await session.run_in_threadpool(_run_verify)
        return Message(message="Repository verified", detail={"output": result["stdout"]})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"pgBackRest verify failed: {exc}")


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
    """Apply retention policies to pgBackRest repository (remove expired backups)."""
    from app.workers.pgbackrest import _run_expire

    try:
        result = await session.run_in_threadpool(_run_expire)
        return Message(message="Retention applied", detail={"output": result["stdout"]})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"pgBackRest expire failed: {exc}")


__all__ = ["router"]