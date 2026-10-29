"""Idempotent platform bootstrap executed during API startup.

The bootstrap only runs when ``BOOTSTRAP_ADMIN_PASSWORD`` is provided, which keeps
production deployments free of implicit credentials. It creates the default tenant,
the system role catalogue, the permission catalogue and a SuperAdmin account.
"""

from __future__ import annotations

from typing import Any

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.services.identity import SystemBootstrapService

log = get_logger("ofme.seeds")

_ADMIN_EMAIL = TypeAdapter(EmailStr)


async def bootstrap_if_configured() -> dict[str, Any] | None:
    if not settings.BOOTSTRAP_ADMIN_PASSWORD:
        log.info("seed.skipped", reason="BOOTSTRAP_ADMIN_PASSWORD not set")
        return None

    # The account is serialised through `CurrentUser.email: EmailStr`, so an
    # address with a special-use TLD (`.local`, `.test`, …) would make every
    # login response fail with a 500. Reject it here with an explicit message.
    try:
        admin_email = str(_ADMIN_EMAIL.validate_python(settings.BOOTSTRAP_ADMIN_EMAIL))
    except ValidationError as exc:
        log.error(
            "seed.invalid_admin_email",
            email=settings.BOOTSTRAP_ADMIN_EMAIL,
            error=exc.errors()[0]["msg"],
        )
        return None

    async with async_session_factory() as session:
        result = await SystemBootstrapService(session).run(
            admin_email=admin_email,
            admin_password=settings.BOOTSTRAP_ADMIN_PASSWORD,
            tenant_slug=settings.DEFAULT_TENANT_SLUG,
            tenant_name="Default Tenant",
        )

    log.info(
        "seed.completed",
        tenant=result["tenant_slug"],
        admin_created=result["admin_created"],
        password_set=result["password_set"],
    )
    return result


async def sync_rbac_catalogue() -> dict[str, int]:
    """Align the permission catalogue and built-in roles with the code matrix.

    Runs on every startup, with or without bootstrap credentials. Without it an
    upgraded deployment keeps the role rows it was installed with, so
    permissions added in a later release would never reach existing users.
    """
    from app.services.identity import RoleService

    async with async_session_factory() as session:
        try:
            service = RoleService(session, None)
            permissions_created = await service.sync_permission_catalogue()
            roles_updated = await service.sync_system_roles()
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return {"permissions_created": permissions_created, "roles_updated": roles_updated}


__all__ = ["bootstrap_if_configured", "sync_rbac_catalogue"]
