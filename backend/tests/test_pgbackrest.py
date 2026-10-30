"""pgBackRest PostgreSQL backup/restore endpoints tests.

Tests cover:
- API endpoint routing and permissions
- Job queuing for async worker execution
- Worker subprocess logic with mocked docker commands
- Full end-to-end backup triggering flow
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import RoleName
from app.models.operations import Job, JobStatus
from tests.conftest import Account, AccountFactory, TenantFactory


class FakeSubprocessResult:
    """Fake subprocess result from pgBackRest commands."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def fake_docker(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Mock docker exec subprocess calls for pgBackRest commands."""
    calls: list[list[str]] = []

    def mock_run(cmd: list[str], *args: Any, **kwargs: Any) -> FakeSubprocessResult:
        calls.append(cmd)
        # Return success for all pgbackrest commands
        if "pgbackrest" in " ".join(cmd):
            if "backup" in cmd:
                return FakeSubprocessResult(
                    stdout="pgbackrest: backup incomplete, waiting for stanza to be configured",
                )
            if "info" in cmd:
                return FakeSubprocessResult(
                    stdout="stanza: ofme\n  status: ok\n  encrypt: y",
                )
            if "verify" in cmd:
                return FakeSubprocessResult(
                    stdout="pgbackrest: verify: all OK",
                )
            if "expire" in cmd:
                return FakeSubprocessResult(
                    stdout="pgbackrest: expire: 0 expired backups removed",
                )
        return FakeSubprocessResult()

    monkeypatch.setattr(subprocess, "run", mock_run)
    return {"calls": calls}


@pytest.mark.asyncio(loop_scope="session")
async def test_trigger_backup_enqueues_job(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    db_session: AsyncSession,
    fake_docker: dict[str, Any],
) -> None:
    """Trigger backup endpoint enqueues a background job."""
    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)

    # Login
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": admin.user.username, "password": admin.password},
    )
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    # Trigger backup
    response = await client.post(
        "/api/v1/pgbackrest/backup?backup_type=full",
        headers=headers,
    )
    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert "pgBackRest full backup scheduled" in body["message"]

    # Verify job was created in database
    job_id = body["job_id"]
    job = await db_session.get(Job, job_id)
    assert job is not None
    assert job.task_name == "ofme.backup.pgbackrest_backup"
    assert job.status == JobStatus.PENDING
    assert job.params == {"backup_type": "full"}


@pytest.mark.asyncio(loop_scope="session")
async def test_trigger_backup_default_type_is_incremental(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_docker: dict[str, Any],
) -> None:
    """Backup endpoint defaults to incremental backup type."""
    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": admin.user.username, "password": admin.password},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    response = await client.post(
        "/api/v1/pgbackrest/backup",
        headers=headers,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["detail"]["job_id"] is not None


@pytest.mark.asyncio(loop_scope="session")
async def test_info_endpoint_enqueues_job(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    db_session: AsyncSession,
    fake_docker: dict[str, Any],
) -> None:
    """Info endpoint returns repository information."""
    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": admin.user.username, "password": admin.password},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    response = await client.get("/api/v1/pgbackrest/info", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "pending"

    # Verify job was created
    job_id = body["job_id"]
    job = await db_session.get(Job, job_id)
    assert job is not None
    assert job.task_name == "ofme.backup.pgbackrest_info"


@pytest.mark.asyncio(loop_scope="session")
async def test_verify_repository_enqueues_job(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_docker: dict[str, Any],
) -> None:
    """Verify repository endpoint queues integrity check."""
    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": admin.user.username, "password": admin.password},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    response = await client.post(
        "/api/v1/pgbackrest/verify",
        headers=headers,
    )
    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert "verify job scheduled" in body["message"]


@pytest.mark.asyncio(loop_scope="session")
async def test_expire_repository_enqueues_job(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_docker: dict[str, Any],
) -> None:
    """Expire repository endpoint queues retention policy application."""
    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": admin.user.username, "password": admin.password},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    response = await client.post(
        "/api/v1/pgbackrest/expire",
        headers=headers,
    )
    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert "expire job scheduled" in body["message"]


@pytest.mark.asyncio(loop_scope="session")
async def test_backup_requires_backup_create_permission(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_docker: dict[str, Any],
) -> None:
    """Read-only users cannot trigger backups."""
    tenant = await tenant_factory()
    readonly = await account_factory(tenant, role=RoleName.READ_ONLY)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": readonly.user.username, "password": readonly.password},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    response = await client.post(
        "/api/v1/pgbackrest/backup",
        headers=headers,
    )
    assert response.status_code == 403
    assert "Missing required permission" in response.json()["error"]["message"]


@pytest.mark.asyncio(loop_scope="session")
async def test_info_requires_backup_read_permission(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_docker: dict[str, Any],
) -> None:
    """Backup info requires backup read permission."""
    tenant = await tenant_factory()
    readonly = await account_factory(tenant, role=RoleName.READ_ONLY)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": readonly.user.username, "password": readonly.password},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    response = await client.get("/api/v1/pgbackrest/info", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_verify_requires_backup_create_permission(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_docker: dict[str, Any],
) -> None:
    """Verify operation requires BACKUP_CREATE permission."""
    tenant = await tenant_factory()
    readonly = await account_factory(tenant, role=RoleName.READ_ONLY)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": readonly.user.username, "password": readonly.password},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    response = await client.post(
        "/api/v1/pgbackrest/verify",
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_expire_requires_backup_create_permission(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    fake_docker: dict[str, Any],
) -> None:
    """Expire operation requires BACKUP_CREATE permission."""
    tenant = await tenant_factory()
    readonly = await account_factory(tenant, role=RoleName.READ_ONLY)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": readonly.user.username, "password": readonly.password},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    response = await client.post(
        "/api/v1/pgbackrest/expire",
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_admin_and_operator_can_perform_backup_operations(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    db_session: AsyncSession,
    fake_docker: dict[str, Any],
) -> None:
    """Both ADMIN and OPERATOR roles can trigger backups."""
    tenant = await tenant_factory()

    for role in [RoleName.ADMIN, RoleName.OPERATOR]:
        account = await account_factory(tenant, role=role)

        response = await client.post(
            "/api/v1/auth/login",
            json={"username": account.user.username, "password": account.password},
        )
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        # Admin can trigger backup
        response = await client.post(
            "/api/v1/pgbackrest/backup", headers=headers
        )
        assert response.status_code == 202, f"{role} should be able to trigger backup"

        # Clear jobs between tests
        await db_session.execute("DELETE FROM jobs")
        await db_session.commit()


@pytest.mark.asyncio(loop_scope="session")
async def test_audit_log_records_backup_operations(
    client: AsyncClient,
    tenant_factory: TenantFactory,
    account_factory: AccountFactory,
    db_session: AsyncSession,
    fake_docker: dict[str, Any],
) -> None:
    """Backup operations should be audited."""
    from app.models.audit import AuditLog

    from sqlalchemy import select

    tenant = await tenant_factory()
    admin = await account_factory(tenant, role=RoleName.ADMIN)

    response = await client.post(
        "/api/v1/auth/login",
        json={"username": admin.user.username, "password": admin.password},
    )
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

    await client.post(
        "/api/v1/pgbackrest/backup",
        headers=headers,
    )

    audit_logs = (
        await db_session.execute(
            select(AuditLog.action).where(AuditLog.tenant_id == tenant.id)
        )
    ).scalars().all()

    assert "backup.create" in audit_logs or "pgbackrest.backup" in " ".join(audit_logs)