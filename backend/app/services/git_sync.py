"""Git synchronisation: repository <-> policy records, webhooks, publishing."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.integrations.git.providers import FileChange, GitProvider, provider_for
from app.models.enums import Environment, PolicyStatus
from app.models.policy import GitRepository, Policy
from app.repositories import UnitOfWork
from app.schemas.policy import PolicyCreate
from app.services.audit import AuditService
from app.services.gitops import PolicyService, PolicyValidator

log = get_logger("ofme.git_sync")


@dataclass(slots=True)
class SyncOutcome:
    repository_id: uuid.UUID
    commit_sha: str | None
    updated: int = 0
    created: int = 0
    unchanged: int = 0
    invalid: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def _slug_from_url(url: str) -> tuple[str, str, str]:
    """Return (organisation, project, repo_slug) from a provider URL."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parts and parts[-1].endswith(".git"):
        parts[-1] = parts[-1][: -len(".git")]
    organisation = parts[0] if parts else ""
    project = parts[1] if len(parts) > 1 else ""
    repo_slug = "/".join(parts[:3]) if parts else ""
    return organisation, project, repo_slug


class GitSyncService:
    """Bidirectional synchronisation between Git repositories and policy records."""

    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.audit = AuditService(session)
        self.validator = PolicyValidator()

    # ------------------------------------------------------------------ provider
    async def _provider(self, repository: GitRepository) -> GitProvider:
        token = decrypt_secret(repository.credentials_encrypted) if repository.credentials_encrypted else ""
        organisation, project, slug = _slug_from_url(repository.url)
        provider = provider_for(
            repository.provider.value if hasattr(repository.provider, "value") else str(repository.provider),
            url=repository.url,
            token=token,
            organization=str((repository.settings or {}).get("organization") or organisation),
            project=str((repository.settings or {}).get("project") or project),
        )
        if not slug:
            raise BadRequestError(f"Unable to determine repository path from URL '{repository.url}'")
        return provider

    @staticmethod
    def repo_slug(repository: GitRepository) -> str:
        _organisation, _project, slug = _slug_from_url(repository.url)
        return slug

    async def branches(self, repository_id: uuid.UUID) -> list[dict[str, Any]]:
        repository = await self.uow.git_repos.get_or_404(repository_id)
        provider = await self._provider(repository)
        try:
            return await provider.list_branches(self.repo_slug(repository))
        finally:
            await provider.close()

    async def commits(
        self, repository_id: uuid.UUID, ref: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        repository = await self.uow.git_repos.get_or_404(repository_id)
        provider = await self._provider(repository)
        try:
            return await provider.list_commits(
                self.repo_slug(repository), ref or repository.default_branch, limit
            )
        finally:
            await provider.close()

    async def read_file(self, repository_id: uuid.UUID, path: str, ref: str | None = None) -> str | None:
        repository = await self.uow.git_repos.get_or_404(repository_id)
        provider = await self._provider(repository)
        try:
            return await provider.read_file(
                self.repo_slug(repository), path, ref or repository.default_branch
            )
        finally:
            await provider.close()

    # ------------------------------------------------------------------ pull
    async def sync_repository(self, repository_id: uuid.UUID, *, branch: str | None = None) -> SyncOutcome:
        repository = await self.uow.git_repos.get_or_404(repository_id)
        provider = await self._provider(repository)
        ref = branch or repository.default_branch
        outcome = SyncOutcome(repository_id=repository.id, commit_sha=repository.last_commit_sha)
        try:
            commits = await provider.list_commits(self.repo_slug(repository), ref, limit=1)
            head = commits[0]["sha"] if commits else None
            outcome.commit_sha = head

            policies = list(
                (
                    await self.session.execute(
                        select(Policy).where(
                            Policy.tenant_id == self.tenant_id,
                            Policy.repo_id == repository.id,
                            Policy.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for policy in policies:
                if not policy.path:
                    continue
                try:
                    content = await provider.read_file(self.repo_slug(repository), policy.path, ref)
                except Exception as exc:  # noqa: BLE001 - record per-file failure
                    outcome.errors.append(f"{policy.path}: {exc}")
                    continue
                if content is None:
                    outcome.errors.append(f"{policy.path}: not found on {ref}")
                    continue

                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if digest == policy.content_hash:
                    outcome.unchanged += 1
                    continue

                validation = self.validator.validate(content, policy.kind)
                policy.content = content
                policy.content_hash = digest
                policy.version += 1
                policy.validation_errors = [issue.model_dump() for issue in validation.errors]
                policy.validated_at = datetime.now(UTC)
                policy.status = PolicyStatus.VALIDATED if validation.valid else PolicyStatus.DRAFT
                outcome.updated += 1
                if not validation.valid:
                    outcome.invalid += 1

            repository.last_sync_at = datetime.now(UTC)
            repository.last_commit_sha = head
            await self.session.flush()
            await self.audit.record(
                action="git.repository_synced",
                resource_type="GitRepository",
                resource_id=repository.id,
                tenant_id=self.tenant_id,
                user_id=self.actor_id,
                after={
                    "commit": head,
                    "updated": outcome.updated,
                    "unchanged": outcome.unchanged,
                    "invalid": outcome.invalid,
                },
            )
            await self.session.commit()
        finally:
            await provider.close()
        log.info(
            "git.sync_completed",
            repository=repository.name,
            commit=outcome.commit_sha,
            updated=outcome.updated,
        )
        return outcome

    async def import_file(
        self,
        repository_id: uuid.UUID,
        path: str,
        *,
        name: str | None = None,
        environment: Environment = Environment.DEVELOPMENT,
        ref: str | None = None,
    ) -> Policy:
        repository = await self.uow.git_repos.get_or_404(repository_id)
        provider = await self._provider(repository)
        try:
            content = await provider.read_file(
                self.repo_slug(repository), path, ref or repository.default_branch
            )
        finally:
            await provider.close()
        if content is None:
            raise NotFoundError(f"'{path}' not found in {repository.name}")

        policy = await PolicyService(self.session, self.tenant_id, self.actor_id).create(
            PolicyCreate(
                name=name or path.rsplit("/", 1)[-1].rsplit(".", 1)[0][:255],
                environment=environment,
                repo_id=repository.id,
                path=path,
                content=content,
                description=f"Imported from {repository.name}:{path}",
            )
        )
        validation = self.validator.validate(content)
        if not validation.valid:
            policy.validation_errors = [issue.model_dump() for issue in validation.errors]
            policy.status = PolicyStatus.DRAFT
        else:
            policy.status = PolicyStatus.VALIDATED
            policy.validated_at = datetime.now(UTC)
        await self.session.commit()
        return policy

    # ------------------------------------------------------------------ push
    async def publish_policy(
        self,
        policy_id: uuid.UUID,
        *,
        branch: str | None = None,
        message: str | None = None,
        base_branch: str | None = None,
        open_pull_request: bool = False,
        pull_request_title: str | None = None,
    ) -> dict[str, Any]:
        policy = await self.uow.policies.get_or_404(policy_id)
        if policy.repo_id is None or not policy.path:
            raise BadRequestError("Policy is not linked to a repository path")

        repository = await self.uow.git_repos.get_or_404(policy.repo_id)
        provider = await self._provider(repository)
        target_branch = branch or repository.default_branch
        commit_message = message or f"chore(policy): publish {policy.name} v{policy.version}"
        try:
            sha = await provider.commit_files(
                self.repo_slug(repository),
                target_branch,
                commit_message,
                [FileChange(path=policy.path, content=policy.content, operation="update")],
                base_branch=base_branch,
            )
            result: dict[str, Any] = {"commit_sha": sha, "branch": target_branch}
            if open_pull_request and base_branch and target_branch != base_branch:
                pull = await provider.create_pull_request(
                    self.repo_slug(repository),
                    pull_request_title or f"Policy: {policy.name}",
                    f"Automated change generated by OFME for policy `{policy.name}` (v{policy.version}).",
                    target_branch,
                    base_branch,
                )
                result["pull_request"] = {
                    "number": pull.number,
                    "url": pull.url,
                    "state": pull.state,
                }
        finally:
            await provider.close()

        repository.last_commit_sha = result["commit_sha"]
        repository.last_sync_at = datetime.now(UTC)
        policy.status = PolicyStatus.REVIEW if open_pull_request else policy.status
        await self.session.flush()
        await self.audit.record(
            action="git.policy_published",
            resource_type="Policy",
            resource_id=policy.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"repository": repository.name, "branch": target_branch, "commit": result["commit_sha"]},
        )
        await self.session.commit()
        return result

    async def publish_many(
        self, policy_ids: list[uuid.UUID], *, branch: str | None = None, message: str | None = None
    ) -> dict[str, Any]:
        published = 0
        errors: list[str] = []
        for policy_id in policy_ids:
            try:
                await self.publish_policy(policy_id, branch=branch, message=message)
                published += 1
            except Exception as exc:  # noqa: BLE001 - continue with remaining policies
                errors.append(f"{policy_id}: {exc}")
        return {"published": published, "failed": len(errors), "errors": errors}

    # ------------------------------------------------------------------ webhooks
    async def handle_webhook(
        self,
        repository: GitRepository,
        body: bytes,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Validate the provider signature and trigger synchronisation."""
        secret = (
            decrypt_secret(repository.webhook_secret_encrypted) if repository.webhook_secret_encrypted else ""
        )
        lower = {key.lower(): value for key, value in headers.items()}
        signature = (
            lower.get("x-hub-signature-256") or lower.get("x-gitlab-token") or lower.get("x-ofme-signature")
        )
        if secret:
            if repository.provider.value in {"github", "gitlab"}:
                if not GitProvider.verify_webhook(secret, body, signature):
                    raise BadRequestError("Webhook signature validation failed")
            elif signature != secret:
                raise BadRequestError("Webhook token mismatch")

        try:
            payload = json.loads(body or b"{}")
        except ValueError as exc:
            raise BadRequestError("Webhook payload is not valid JSON") from exc

        ref = str(payload.get("ref") or "")
        branch = ref.replace("refs/heads/", "") if ref else repository.default_branch
        outcome = await self.sync_repository(repository.id, branch=branch)
        await self.audit.record(
            action="git.webhook_received",
            resource_type="GitRepository",
            resource_id=repository.id,
            tenant_id=self.tenant_id,
            actor=f"webhook:{repository.provider.value}",
            after={"branch": branch, "commit": outcome.commit_sha, "updated": outcome.updated},
        )
        await self.session.commit()
        return {
            "accepted": True,
            "repository_id": str(repository.id),
            "branch": branch,
            "commit": outcome.commit_sha,
            "updated": outcome.updated,
            "unchanged": outcome.unchanged,
            "invalid": outcome.invalid,
        }


class GitRepositoryService:
    """CRUD for provider connections (credentials are always sealed)."""

    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.audit = AuditService(session)

    async def create(self, payload) -> GitRepository:  # noqa: ANN001 - schema imported lazily by API layer
        from app.core.security import encrypt_secret

        exists = await self.session.execute(
            select(GitRepository).where(
                GitRepository.tenant_id == self.tenant_id,
                GitRepository.name == payload.name,
                GitRepository.deleted_at.is_(None),
            )
        )
        if exists.scalars().first():
            raise ConflictError(f"Repository '{payload.name}' already exists")

        secret_material = payload.token or payload.ssh_key or ""
        repository = GitRepository(
            tenant_id=self.tenant_id,
            name=payload.name,
            provider=payload.provider,
            url=payload.url,
            default_branch=payload.default_branch,
            auth_type=payload.auth_type,
            credentials_encrypted=encrypt_secret(secret_material) if secret_material else None,
            auto_sync=payload.auto_sync,
            sync_interval_minutes=payload.sync_interval_minutes,
            status="active",
            settings={},
        )
        self.session.add(repository)
        await self.session.flush()
        await self.audit.record(
            action="git.repository_created",
            resource_type="GitRepository",
            resource_id=repository.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": repository.name, "provider": repository.provider.value, "url": repository.url},
        )
        await self.session.commit()
        return repository

    async def update(self, repository_id: uuid.UUID, payload) -> GitRepository:  # noqa: ANN001
        from app.core.security import encrypt_secret

        repository = await self.uow.git_repos.get_or_404(repository_id)
        if payload.default_branch is not None:
            repository.default_branch = payload.default_branch
        if payload.token is not None:
            repository.credentials_encrypted = encrypt_secret(payload.token) if payload.token else None
        if payload.auto_sync is not None:
            repository.auto_sync = payload.auto_sync
        if payload.sync_interval_minutes is not None:
            repository.sync_interval_minutes = payload.sync_interval_minutes
        await self.session.flush()
        await self.session.commit()
        return repository

    async def delete(self, repository_id: uuid.UUID) -> None:
        repository = await self.uow.git_repos.get_or_404(repository_id)
        await self.uow.git_repos.delete(repository)
        await self.session.commit()

    async def rotate_webhook_secret(self, repository_id: uuid.UUID) -> str:
        import secrets

        from app.core.security import encrypt_secret

        repository = await self.uow.git_repos.get_or_404(repository_id)
        secret = secrets.token_urlsafe(32)
        repository.webhook_secret_encrypted = encrypt_secret(secret)
        await self.session.flush()
        await self.audit.record(
            action="git.webhook_secret_rotated",
            resource_type="GitRepository",
            resource_id=repository.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
        )
        await self.session.commit()
        return secret
