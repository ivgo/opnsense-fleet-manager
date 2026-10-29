"""Configuration templates: versioned bodies, inheritance and variable rendering."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentPrincipal,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import BadRequestError
from app.models.enums import TemplateKind
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.config import (
    TemplateCreate,
    TemplateOut,
    TemplateRenderRequest,
    TemplateRenderResponse,
    TemplateUpdate,
)
from app.services.configuration import TemplateService

router = APIRouter(prefix="/templates", tags=["Templates"])


@router.get(
    "",
    response_model=PageResponse[TemplateOut],
    dependencies=[Depends(require_permissions(P.TEMPLATE_READ))],
    summary="List templates",
)
async def list_templates(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    kind: TemplateKind | None = None,
    is_active: bool | None = Query(None),
    search: str | None = Query(None, max_length=128),
) -> PageResponse[TemplateOut]:
    filters: dict[str, object] = {"kind": kind}
    if is_active is not None:
        filters["is_active"] = is_active
    rows, total = await UnitOfWork(session, tenant_id).templates.list(
        filters=filters,
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "name",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, TemplateOut)


@router.post(
    "",
    response_model=TemplateOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.TEMPLATE_WRITE))],
    summary="Create a template",
)
async def create_template(
    payload: TemplateCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> TemplateOut:
    uow = UnitOfWork(session, tenant_id)
    if await uow.templates.find_one(name=payload.name):
        raise BadRequestError(f"Template '{payload.name}' already exists")
    if payload.parent_id is not None and await uow.templates.get(payload.parent_id) is None:
        raise BadRequestError("Parent template does not exist")
    template = await TemplateService(session, tenant_id, principal.user_id).create(**payload.model_dump())
    await session.commit()
    return TemplateOut.model_validate(template)


@router.get(
    "/{template_id}",
    response_model=TemplateOut,
    dependencies=[Depends(require_permissions(P.TEMPLATE_READ))],
    summary="Get a template",
)
async def get_template(template_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> TemplateOut:
    template = await UnitOfWork(session, tenant_id).templates.get_or_404(template_id)
    return TemplateOut.model_validate(template)


@router.patch(
    "/{template_id}",
    response_model=TemplateOut,
    dependencies=[Depends(require_permissions(P.TEMPLATE_WRITE))],
    summary="Update a template",
)
async def update_template(
    template_id: uuid.UUID,
    payload: TemplateUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> TemplateOut:
    uow = UnitOfWork(session, tenant_id)
    template = await uow.templates.get_or_404(template_id)
    data = payload.model_dump(exclude_unset=True)
    if "parent_id" in data and data["parent_id"] == template.id:
        raise BadRequestError("A template cannot inherit from itself")
    if data.get("parent_id") is not None and await uow.templates.get(data["parent_id"]) is None:
        raise BadRequestError("Parent template does not exist")
    template.version += 1
    await uow.templates.update(template, **data)
    await session.commit()
    return TemplateOut.model_validate(template)


@router.delete(
    "/{template_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.TEMPLATE_WRITE))],
    summary="Delete a template",
)
async def delete_template(template_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    await uow.templates.delete(await uow.templates.get_or_404(template_id))
    await session.commit()
    return Message(message="Template deleted")


@router.post(
    "/{template_id}/render",
    response_model=TemplateRenderResponse,
    dependencies=[Depends(require_permissions(P.TEMPLATE_READ))],
    summary="Render a template with variables",
)
async def render_template(
    template_id: uuid.UUID,
    payload: TemplateRenderRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> TemplateRenderResponse:
    uow = UnitOfWork(session, tenant_id)
    template = await uow.templates.get_or_404(template_id)
    rendered = await TemplateService(session, tenant_id, principal.user_id).render(
        template, payload.variables
    )
    return TemplateRenderResponse(**rendered)


@router.get(
    "/{template_id}/effective",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.TEMPLATE_READ))],
    summary="Effective body including inherited layers",
)
async def effective_template(template_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> dict:
    uow = UnitOfWork(session, tenant_id)
    template = await uow.templates.get_or_404(template_id)
    return await TemplateService(session, tenant_id).inherited_body(template)
