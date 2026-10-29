"""Operational jobs and tenant-owned schedules."""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

from croniter import croniter
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.enums import JobStatus
from app.models.operations import Task
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.operations import JobOut, TaskCreate, TaskOut, TaskUpdate
from app.workers.dispatch import (
    TASK_BACKUP_ALL,
    TASK_BACKUP_DEVICE,
    TASK_CERT_ROTATE,
    TASK_COMPLIANCE_RUN,
    TASK_CUSTOM,
    TASK_DRIFT_SCAN,
    TASK_FIRMWARE_REBOOT,
    TASK_FIRMWARE_UPGRADE,
    TASK_FOR_KIND,
    TASK_GIT_SYNC,
    TASK_HEARTBEAT_TIMEOUT,
    TASK_METRIC_COLLECT,
    TASK_METRIC_PURGE,
    TASK_POLICY_DEPLOY,
    TASK_SDWAN_HEALTH,
    TASK_REPORT,
    enqueue,
)

jobs_router = APIRouter(prefix="/jobs", tags=["Jobs"])
tasks_router = APIRouter(prefix="/tasks", tags=["Scheduled tasks"])

ALLOWED_TASKS = {
    TASK_BACKUP_ALL,
    TASK_BACKUP_DEVICE,
    TASK_COMPLIANCE_RUN,
    TASK_DRIFT_SCAN,
    TASK_POLICY_DEPLOY,
    TASK_METRIC_COLLECT,
    TASK_HEARTBEAT_TIMEOUT,
    TASK_CERT_ROTATE,
    TASK_METRIC_PURGE,
    TASK_GIT_SYNC,
    TASK_SDWAN_HEALTH,
    TASK_FIRMWARE_UPGRADE,
    TASK_FIRMWARE_REBOOT,
    TASK_REPORT,
    TASK_CUSTOM,
}

KIND_TASKS = TASK_FOR_KIND


class JobCreate(BaseModel):
    task_name: str = Field(min_length=3, max_length=128)
    params: dict = Field(default_factory=dict)


def _next_run(cron: str) -> datetime:
    if not croniter.is_valid(cron):
        raise BadRequestError(f"Invalid cron expression '{cron}'")
    return croniter(cron, datetime.now(UTC)).get_next(datetime)


# --------------------------------------------------------------------------- jobs
@jobs_router.get(
    "",
    response_model=PageResponse[JobOut],
    dependencies=[Depends(require_permissions(P.JOB_READ))],
    summary="List jobs",
)
async def list_jobs(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    status_filter: JobStatus | None = Query(None, alias="status"),
    task_name: str | None = Query(None, max_length=128),
) -> PageResponse[JobOut]:
    filters: dict[str, object] = {}
    if status_filter is not None:
        filters["status"] = status_filter
    if task_name:
        filters["task_name"] = task_name
    rows, total = await UnitOfWork(session, tenant_id).jobs.list(
        filters=filters,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "created_at",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, JobOut)


@jobs_router.post(
    "",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions(P.TASK_WRITE))],
    summary="Enqueue a background job",
)
async def create_job(
    payload: JobCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> JobOut:
    if payload.task_name not in ALLOWED_TASKS:
        raise BadRequestError(f"Unknown task '{payload.task_name}'")
    job = await enqueue(
        session,
        tenant_id=tenant_id,
        task_name=payload.task_name,
        params=payload.params,
        actor_id=principal.user_id,
    )
    return JobOut.model_validate(job)


@jobs_router.get(
    "/{job_id}",
    response_model=JobOut,
    dependencies=[Depends(require_permissions(P.JOB_READ))],
    summary="Get a job",
)
async def get_job(job_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> JobOut:
    return JobOut.model_validate(await UnitOfWork(session, tenant_id).jobs.get_or_404(job_id))


@jobs_router.post(
    "/{job_id}/cancel",
    response_model=JobOut,
    dependencies=[Depends(require_permissions(P.JOB_CANCEL))],
    summary="Cancel a pending or running job",
)
async def cancel_job(
    job_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> JobOut:
    job = await UnitOfWork(session, tenant_id).jobs.get_or_404(job_id)
    if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
        raise BadRequestError(f"Job is already {job.status.value}")
    if job.celery_task_id:
        with contextlib.suppress(Exception):
            from app.workers.celery_app import celery_app

            celery_app.control.revoke(job.celery_task_id, terminate=True, signal="SIGTERM")
    job.status = JobStatus.CANCELLED
    job.finished_at = datetime.now(UTC)
    job.error = "Cancelled by operator"
    await session.commit()
    return JobOut.model_validate(job)


# --------------------------------------------------------------------------- schedules
@tasks_router.get(
    "",
    response_model=PageResponse[TaskOut],
    dependencies=[Depends(require_permissions(P.TASK_READ))],
    summary="List scheduled tasks",
)
async def list_tasks(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    enabled: bool | None = Query(None),
) -> PageResponse[TaskOut]:
    filters: dict[str, object] = {}
    if enabled is not None:
        filters["enabled"] = enabled
    rows, total = await UnitOfWork(session, tenant_id).tasks.list(
        filters=filters,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "name",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, TaskOut)


@tasks_router.post(
    "",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.TASK_WRITE))],
    summary="Create a scheduled task",
)
async def create_task(
    payload: TaskCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> TaskOut:
    uow = UnitOfWork(session, tenant_id)
    if await uow.tasks.find_one(name=payload.name):
        raise BadRequestError(f"Task '{payload.name}' already exists")
    task = await uow.tasks.create(
        name=payload.name,
        kind=payload.kind,
        cron=payload.cron,
        payload=payload.payload,
        enabled=payload.enabled,
        next_run_at=_next_run(payload.cron) if payload.enabled else None,
        created_by=principal.user_id,
    )
    await session.commit()
    return TaskOut.model_validate(task)


@tasks_router.get(
    "/{task_id}",
    response_model=TaskOut,
    dependencies=[Depends(require_permissions(P.TASK_READ))],
    summary="Get a scheduled task",
)
async def get_task(task_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> TaskOut:
    return TaskOut.model_validate(await UnitOfWork(session, tenant_id).tasks.get_or_404(task_id))


@tasks_router.patch(
    "/{task_id}",
    response_model=TaskOut,
    dependencies=[Depends(require_permissions(P.TASK_WRITE))],
    summary="Update a scheduled task",
)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
) -> TaskOut:
    uow = UnitOfWork(session, tenant_id)
    task = await uow.tasks.get_or_404(task_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != task.name and await uow.tasks.find_one(name=data["name"]):
        raise BadRequestError(f"Task '{data['name']}' already exists")
    if "cron" in data:
        data["next_run_at"] = _next_run(data["cron"]) if data.get("enabled", task.enabled) else None
    if data.get("enabled") is False:
        data["next_run_at"] = None
    elif data.get("enabled") is True and task.next_run_at is None:
        data["next_run_at"] = _next_run(data.get("cron", task.cron))
    await uow.tasks.update(task, **data)
    await session.commit()
    return TaskOut.model_validate(task)


@tasks_router.delete(
    "/{task_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.TASK_WRITE))],
    summary="Delete a scheduled task",
)
async def delete_task(task_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    task: Task | None = await session.get(Task, task_id)
    if task is None or task.tenant_id != tenant_id:
        raise NotFoundError("Task not found")
    await session.delete(task)
    await session.commit()
    return Message(message="Scheduled task deleted")


@tasks_router.post(
    "/{task_id}/run",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permissions(P.TASK_WRITE))],
    summary="Run a scheduled task immediately",
)
async def run_task(
    task_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> JobOut:
    task = await UnitOfWork(session, tenant_id).tasks.get_or_404(task_id)
    task_name = task.payload.get("task_name") if isinstance(task.payload, dict) else None
    if not task_name:
        task_name = KIND_TASKS.get(task.kind, TASK_CUSTOM)
    if task_name not in ALLOWED_TASKS:
        raise BadRequestError(f"Unknown task '{task_name}'")
    job = await enqueue(
        session,
        tenant_id=tenant_id,
        task_name=task_name,
        params={**(task.payload or {}), "task_id": str(task.id)},
        actor_id=principal.user_id,
    )
    task.last_run_at = datetime.now(UTC)
    task.next_run_at = _next_run(task.cron) if task.enabled else None
    await session.commit()
    return JobOut.model_validate(job)
