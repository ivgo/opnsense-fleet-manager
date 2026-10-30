"""pgBackRest worker: PostgreSQL cluster backup/restore via pgBackRest CLI."""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from app.core.exceptions import UpstreamError
from app.core.logging import get_logger
from app.workers.base import execute_task
from app.workers.celery_app import celery_app
from app.workers.dispatch import TASK_BACKUP_POSTGRES

log = get_logger("ofme.workers.pgbackrest")


def _run_pgbackrest(*args: str) -> dict[str, Any]:
    """Run a pgBackRest command via docker exec on postgres container."""
    # Use docker exec to run pgbackrest inside the postgres container where
    # it can access the local PostgreSQL data directory without SSH.
    cmd = ["docker", "exec", "-u", "postgres", "ofme-postgres-1", "pgbackrest", *args]
    log.info("pgbackrest.command", command=" ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        log.error("pgbackrest.timeout", command=" ".join(cmd))
        raise UpstreamError(f"pgBackRest command timed out: {' '.join(cmd)}") from exc

    if result.returncode != 0:
        log.error(
            "pgbackrest.failed",
            command=" ".join(cmd),
            returncode=result.returncode,
            stderr=result.stderr,
        )
        raise UpstreamError(
            f"pgBackRest command failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    return {
        "command": " ".join(cmd),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "returncode": result.returncode,
    }


def _run_backup(backup_type: str = "incr") -> dict[str, Any]:
    """Execute a pgBackRest backup of the ofme stanza."""
    return _run_pgbackrest(
        "--stanza=ofme",
        f"--type={backup_type}",
        "backup",
    )


def _run_info() -> dict[str, Any]:
    """Get pgBackRest info for the ofme stanza."""
    return _run_pgbackrest("--stanza=ofme", "--log-level-console=info", "info")


def _run_verify() -> dict[str, Any]:
    """Verify pgBackRest repository integrity."""
    return _run_pgbackrest("--stanza=ofme", "--log-level-console=info", "verify")


def _run_expire() -> dict[str, Any]:
    """Apply retention policies to pgBackRest repository."""
    return _run_pgbackrest("--stanza=ofme", "--log-level-console=info", "expire")


async def _create(
    session: Any, tenant_id: Any, params: dict[str, Any]
) -> dict[str, Any]:
    """Run a pgBackRest backup of the PostgreSQL cluster."""
    backup_type = params.get("backup_type", "incr")
    if backup_type not in ("full", "diff", "incr"):
        raise UpstreamError(f"Invalid backup type: {backup_type}")

    result = await asyncio.to_thread(_run_backup, backup_type)
    return {
        "backup_type": backup_type,
        "command": result["command"],
        "output": result["stdout"],
        "status": "completed",
    }


async def _info(
    session: Any, tenant_id: Any, params: dict[str, Any]
) -> dict[str, Any]:
    """Get pgBackRest repository information."""
    result = await asyncio.to_thread(_run_info)
    return {
        "stanza": "ofme",
        "status": "ok",
        "output": result["stdout"],
    }


async def _verify(
    session: Any, tenant_id: Any, params: dict[str, Any]
) -> dict[str, Any]:
    """Verify pgBackRest repository integrity."""
    result = await asyncio.to_thread(_run_verify)
    return {
        "status": "verified",
        "output": result["stdout"],
    }


async def _expire(
    session: Any, tenant_id: Any, params: dict[str, Any]
) -> dict[str, Any]:
    """Apply retention policies to pgBackRest repository."""
    result = await asyncio.to_thread(_run_expire)
    return {
        "status": "expired",
        "output": result["stdout"],
    }


@celery_app.task(
    bind=True,
    name=TASK_BACKUP_POSTGRES,
    autoretry_for=(UpstreamError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=2,
)
def create(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    """Run a pgBackRest backup of the PostgreSQL cluster."""
    try:
        return execute_task(
            TASK_BACKUP_POSTGRES, _create, job_id=job_id, tenant_id=tenant_id, params=params
        )
    except SoftTimeLimitExceeded as exc:
        log.error("pgbackrest.timeout", job=job_id)
        raise UpstreamError("pgBackRest backup exceeded its time limit") from exc


# Task names for pgBackRest operations
TASK_PGBACKREST_INFO = "ofme.backup.pgbackrest_info"
TASK_PGBACKREST_VERIFY = "ofme.backup.pgbackrest_verify"
TASK_PGBACKREST_EXPIRE = "ofme.backup.pgbackrest_expire"


@celery_app.task(
    bind=True,
    name=TASK_PGBACKREST_INFO,
    autoretry_for=(UpstreamError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=1,
)
def info(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    """Get pgBackRest repository information."""
    try:
        return execute_task(
            TASK_PGBACKREST_INFO, _info, job_id=job_id, tenant_id=tenant_id, params=params
        )
    except SoftTimeLimitExceeded as exc:
        log.error("pgbackrest_info.timeout", job=job_id)
        raise UpstreamError("pgBackRest info exceeded its time limit") from exc


@celery_app.task(
    bind=True,
    name=TASK_PGBACKREST_VERIFY,
    autoretry_for=(UpstreamError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=1,
)
def verify(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    """Verify pgBackRest repository integrity."""
    try:
        return execute_task(
            TASK_PGBACKREST_VERIFY, _verify, job_id=job_id, tenant_id=tenant_id, params=params
        )
    except SoftTimeLimitExceeded as exc:
        log.error("pgbackrest_verify.timeout", job=job_id)
        raise UpstreamError("pgBackRest verify exceeded its time limit") from exc


@celery_app.task(
    bind=True,
    name=TASK_PGBACKREST_EXPIRE,
    autoretry_for=(UpstreamError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=1,
)
def expire(
    self, job_id: str | None = None, tenant_id: str | None = None, params: dict | None = None
) -> dict:  # noqa: ANN001
    """Apply retention policies to pgBackRest repository."""
    try:
        return execute_task(
            TASK_PGBACKREST_EXPIRE, _expire, job_id=job_id, tenant_id=tenant_id, params=params
        )
    except SoftTimeLimitExceeded as exc:
        log.error("pgbackrest_expire.timeout", job=job_id)
        raise UpstreamError("pgBackRest expire exceeded its time limit") from exc


__all__ = [
    "create",
    "info",
    "verify",
    "expire",
    "_run_info",
    "_run_verify",
    "_run_expire",
    "TASK_PGBACKREST_INFO",
    "TASK_PGBACKREST_VERIFY",
    "TASK_PGBACKREST_EXPIRE",
]