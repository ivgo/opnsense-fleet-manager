"""Zero-Touch Provisioning: enrollment tokens, device bootstrap and PKI binding."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.config import settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.models.enums import ZtpStatus
from app.models.ztp import ZtpEnrollment
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.ztp import (
    BootstrapPackage,
    DiscoveryInfo,
    EnrollmentOut,
    EnrollmentRequest,
    EnrollmentResponse,
    EnrollmentTokenCreate,
    EnrollmentTokenResponse,
)
from app.services.ztp import EnrollmentAgentService, EnrollmentService

router = APIRouter(prefix="/ztp", tags=["Zero-touch provisioning"])


class EnrollmentStatusUpdate(BaseModel):
    status: ZtpStatus


def _bootstrap_url(request: Request, token: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}{settings.API_V1_PREFIX}/ztp/bootstrap?token={token}"


async def _tenant_for_token(session: SessionDep, token: str) -> ZtpEnrollment:
    from app.services.ztp import _hash_token

    enrollment = await UnitOfWork(session, None).ztp.by_token_hash(_hash_token(token))
    if enrollment is None:
        raise AuthenticationError("Invalid enrollment token")
    return enrollment


# --------------------------------------------------------------------------- public
@router.get(
    "/discovery",
    response_model=DiscoveryInfo,
    summary="Discovery document consumed by unprovisioned devices",
)
async def discovery(request: Request, session: SessionDep) -> DiscoveryInfo:
    return await EnrollmentAgentService(session).discovery(base_url=str(request.base_url))


@router.get(
    "/bootstrap",
    response_model=BootstrapPackage,
    summary="Fetch the bootstrap package for an enrollment token",
)
async def bootstrap(session: SessionDep, token: str = Query(..., min_length=16)) -> BootstrapPackage:
    return await EnrollmentAgentService(session).bootstrap_package(token)


@router.post(
    "/enroll",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a device with a one-time token",
)
async def enroll(payload: EnrollmentRequest, request: Request, session: SessionDep) -> EnrollmentResponse:
    enrollment = await _tenant_for_token(session, payload.token)
    client_ip = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    service = EnrollmentService(session, enrollment.tenant_id)
    return await service.enroll(payload, source_ip=client_ip)


# --------------------------------------------------------------------------- administration
@router.get(
    "/enrollments",
    response_model=PageResponse[EnrollmentOut],
    dependencies=[Depends(require_permissions(P.ZTP_READ))],
    summary="List enrollment tokens",
)
async def list_enrollments(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    status_filter: ZtpStatus | None = Query(None, alias="status"),
) -> PageResponse[EnrollmentOut]:
    rows, total = await EnrollmentService(session, tenant_id).list(
        page=pagination.page,
        size=pagination.size,
        status=status_filter.value if status_filter else None,
    )
    return paginate(rows, total, pagination, EnrollmentOut)


@router.post(
    "/enrollments",
    response_model=EnrollmentTokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.ZTP_WRITE))],
    summary="Mint a one-time enrollment token",
)
async def create_enrollment(
    payload: EnrollmentTokenCreate,
    request: Request,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> EnrollmentTokenResponse:
    enrollment, token = await EnrollmentService(session, tenant_id, principal.user_id).create_token(payload)
    await session.commit()
    return EnrollmentTokenResponse(
        enrollment_id=enrollment.id,
        token=token,
        expires_at=enrollment.expires_at,
        bootstrap_url=_bootstrap_url(request, token),
        site_id=enrollment.site_id,
        template_id=enrollment.template_id,
    )


@router.get(
    "/enrollments/{enrollment_id}",
    response_model=EnrollmentOut,
    dependencies=[Depends(require_permissions(P.ZTP_READ))],
    summary="Get an enrollment",
)
async def get_enrollment(
    enrollment_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> EnrollmentOut:
    enrollment = await UnitOfWork(session, tenant_id).ztp.get_or_404(enrollment_id)
    return EnrollmentOut.model_validate(enrollment)


@router.patch(
    "/enrollments/{enrollment_id}",
    response_model=EnrollmentOut,
    dependencies=[Depends(require_permissions(P.ZTP_WRITE))],
    summary="Update the lifecycle state of an enrollment",
)
async def update_enrollment_status(
    enrollment_id: uuid.UUID,
    payload: EnrollmentStatusUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> EnrollmentOut:
    uow = UnitOfWork(session, tenant_id)
    enrollment = await uow.ztp.get_or_404(enrollment_id)
    if (
        payload.status in {ZtpStatus.COMPLETED, ZtpStatus.ENROLLED}
        and principal.user_id is not None
        and not principal.can(P.ZTP_APPROVE)
    ):
        from app.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("Approving an enrollment requires ztp:approve")
    enrollment.status = payload.status
    await session.commit()
    return EnrollmentOut.model_validate(enrollment)


@router.post(
    "/enrollments/{enrollment_id}/revoke",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.ZTP_WRITE))],
    summary="Revoke an enrollment token",
)
async def revoke_enrollment(
    enrollment_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    await EnrollmentService(session, tenant_id, principal.user_id).revoke(enrollment_id)
    await session.commit()
    return Message(message="Enrollment revoked")


@router.delete(
    "/enrollments/{enrollment_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.ZTP_WRITE))],
    summary="Delete an enrollment record",
)
async def delete_enrollment(enrollment_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    enrollment = await uow.ztp.get(enrollment_id)
    if enrollment is None:
        raise NotFoundError("Enrollment not found")
    await session.delete(enrollment)
    await session.commit()
    return Message(message="Enrollment deleted")
