"""GitOps repositories: provider connections, sync, publish and webhooks."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import NotFoundError
from app.models.enums import Environment
from app.models.policy import GitRepository
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.policy import (
    GitBranch,
    GitCommit,
    GitRepositoryCreate,
    GitRepositoryOut,
    GitRepositoryUpdate,
    PolicyOut,
)
from app.services.git_sync import GitRepositoryService, GitSyncService

router = APIRouter(prefix="/git", tags=["GitOps"])
webhooks_router = APIRouter(prefix="/git", tags=["GitOps webhooks"])


class SyncResult(BaseModel):
    repository_id: uuid.UUID
    commit_sha: str | None
    updated: int
    created: int
    unchanged: int
    invalid: int
    errors: list[str]


class ImportBody(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    name: str | None = None
    environment: Environment = Environment.DEVELOPMENT
    ref: str | None = None


class PublishBody(BaseModel):
    branch: str | None = None
    message: str | None = None
    base_branch: str | None = None
    open_pull_request: bool = False
    pull_request_title: str | None = None


class PublishResult(BaseModel):
    commit_sha: str
    branch: str
    pull_request: dict | None = None


class WebhookSecretResponse(BaseModel):
    repository_id: uuid.UUID
    secret: str
    instructions: str


class FileContent(BaseModel):
    path: str
    ref: str
    content: str


# --------------------------------------------------------------------------- repositories
@router.get(
    "/repositories",
    response_model=PageResponse[GitRepositoryOut],
    dependencies=[Depends(require_permissions(P.GIT_READ))],
    summary="List Git repositories",
)
async def list_repositories(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    search: str | None = Query(None, max_length=128),
) -> PageResponse[GitRepositoryOut]:
    rows, total = await UnitOfWork(session, tenant_id).git_repos.list(
        search=search,
        search_fields=("name", "url"),
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "name",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, GitRepositoryOut)


@router.post(
    "/repositories",
    response_model=GitRepositoryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.GIT_WRITE))],
    summary="Connect a Git repository",
)
async def create_repository(
    payload: GitRepositoryCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> GitRepositoryOut:
    repository = await GitRepositoryService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return GitRepositoryOut.model_validate(repository)


@router.get(
    "/repositories/{repository_id}",
    response_model=GitRepositoryOut,
    dependencies=[Depends(require_permissions(P.GIT_READ))],
    summary="Get a Git repository",
)
async def get_repository(
    repository_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> GitRepositoryOut:
    return GitRepositoryOut.model_validate(
        await UnitOfWork(session, tenant_id).git_repos.get_or_404(repository_id)
    )


@router.patch(
    "/repositories/{repository_id}",
    response_model=GitRepositoryOut,
    dependencies=[Depends(require_permissions(P.GIT_WRITE))],
    summary="Update a Git repository",
)
async def update_repository(
    repository_id: uuid.UUID,
    payload: GitRepositoryUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> GitRepositoryOut:
    repository = await GitRepositoryService(session, tenant_id, principal.user_id).update(
        repository_id, payload
    )
    return GitRepositoryOut.model_validate(repository)


@router.delete(
    "/repositories/{repository_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.GIT_WRITE))],
    summary="Delete a Git repository",
)
async def delete_repository(
    repository_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await GitRepositoryService(session, tenant_id, principal.user_id).delete(repository_id)
    return Message(message="Repository disconnected")


@router.post(
    "/repositories/{repository_id}/sync",
    response_model=SyncResult,
    dependencies=[Depends(require_permissions(P.GIT_WRITE))],
    summary="Synchronise linked policies from Git",
)
async def sync_repository(
    repository_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
    branch: str | None = Query(None, max_length=100),
) -> SyncResult:
    outcome = await GitSyncService(session, tenant_id, principal.user_id).sync_repository(
        repository_id, branch=branch
    )
    return SyncResult(
        repository_id=outcome.repository_id,
        commit_sha=outcome.commit_sha,
        updated=outcome.updated,
        created=outcome.created,
        unchanged=outcome.unchanged,
        invalid=outcome.invalid,
        errors=outcome.errors,
    )


@router.get(
    "/repositories/{repository_id}/branches",
    response_model=list[GitBranch],
    dependencies=[Depends(require_permissions(P.GIT_READ))],
    summary="List repository branches",
)
async def list_branches(
    repository_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> list[GitBranch]:
    rows = await GitSyncService(session, tenant_id).branches(repository_id)
    return [GitBranch.model_validate(row) for row in rows]


@router.get(
    "/repositories/{repository_id}/commits",
    response_model=list[GitCommit],
    dependencies=[Depends(require_permissions(P.GIT_READ))],
    summary="List repository commits",
)
async def list_commits(
    repository_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    ref: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
) -> list[GitCommit]:
    rows = await GitSyncService(session, tenant_id).commits(repository_id, ref=ref, limit=limit)
    return [GitCommit.model_validate(row) for row in rows]


@router.get(
    "/repositories/{repository_id}/file",
    response_model=FileContent,
    dependencies=[Depends(require_permissions(P.GIT_READ))],
    summary="Read a file from the repository",
)
async def read_repository_file(
    repository_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    path: str = Query(..., min_length=1, max_length=512),
    ref: str | None = Query(None, max_length=100),
) -> FileContent:
    service = GitSyncService(session, tenant_id)
    repository = await service.uow.git_repos.get_or_404(repository_id)
    content = await service.read_file(repository_id, path, ref=ref)
    if content is None:
        raise NotFoundError(f"{path} not found in {repository.name}")
    return FileContent(path=path, ref=ref or repository.default_branch, content=content)


@router.post(
    "/repositories/{repository_id}/import",
    response_model=PolicyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.POLICY_WRITE))],
    summary="Import a file as a policy",
)
async def import_policy(
    repository_id: uuid.UUID,
    payload: ImportBody,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> PolicyOut:
    policy = await GitSyncService(session, tenant_id, principal.user_id).import_file(
        repository_id,
        payload.path,
        name=payload.name,
        environment=payload.environment,
        ref=payload.ref,
    )
    return PolicyOut.model_validate(policy)


@router.post(
    "/repositories/{repository_id}/webhook-secret",
    response_model=WebhookSecretResponse,
    dependencies=[Depends(require_permissions(P.GIT_WRITE))],
    summary="Rotate the webhook secret",
)
async def rotate_webhook_secret(
    repository_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> WebhookSecretResponse:
    secret = await GitRepositoryService(session, tenant_id, principal.user_id).rotate_webhook_secret(
        repository_id
    )
    return WebhookSecretResponse(
        repository_id=repository_id,
        secret=secret,
        instructions=(
            "Configure this value as the GitHub webhook secret (HMAC-SHA256), the GitLab "
            "secret token, or the X-OFME-Signature header for generic providers."
        ),
    )


@router.post(
    "/policies/{policy_id}/publish",
    response_model=PublishResult,
    dependencies=[Depends(require_permissions(P.POLICY_WRITE))],
    summary="Publish a policy to its repository",
)
async def publish_policy(
    policy_id: uuid.UUID,
    payload: PublishBody,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> PublishResult:
    result = await GitSyncService(session, tenant_id, principal.user_id).publish_policy(
        policy_id,
        branch=payload.branch,
        message=payload.message,
        base_branch=payload.base_branch,
        open_pull_request=payload.open_pull_request,
        pull_request_title=payload.pull_request_title,
    )
    return PublishResult(**result)


# --------------------------------------------------------------------------- webhooks
@webhooks_router.post(
    "/webhooks/{repository_id}",
    response_model=SyncResult,
    summary="Provider webhook receiver (signature validated)",
)
async def repository_webhook(
    repository_id: uuid.UUID,
    request: Request,
    session: SessionDep,
) -> SyncResult:
    repository: GitRepository | None = await session.get(GitRepository, repository_id)
    if repository is None or repository.deleted_at is not None:
        raise NotFoundError("Repository not found")

    body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    outcome = await GitSyncService(session, repository.tenant_id).handle_webhook(repository, body, headers)
    return SyncResult(
        repository_id=repository_id,
        commit_sha=outcome.get("commit"),
        updated=int(outcome.get("updated", 0)),
        created=0,
        unchanged=int(outcome.get("unchanged", 0)),
        invalid=int(outcome.get("invalid", 0)),
        errors=[],
    )
