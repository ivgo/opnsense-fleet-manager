"""Shared helpers for endpoint modules."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from app.api.deps import Pagination
from app.core.pagination import page_meta
from app.schemas.common import PageMeta, PageResponse

M = TypeVar("M", bound=BaseModel)


def paginate(items: Sequence[Any], total: int, pagination: Pagination, schema: type[M]) -> Any:
    meta: PageMeta = page_meta(pagination.page, pagination.size, total)
    return PageResponse[schema](
        items=[schema.model_validate(item) for item in items],
        meta=meta,
    )


def page_meta_for(total: int, pagination: Pagination) -> PageMeta:
    return page_meta(pagination.page, pagination.size, total)
