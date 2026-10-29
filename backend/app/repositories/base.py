"""Generic async repository implementing the Repository pattern."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.base import Base
from app.models.identity import Tenant

ModelT = TypeVar("ModelT", bound=Base)

SORTABLE = {
    "created_at",
    "updated_at",
    "name",
    "status",
    "hostname",
    "last_seen_at",
    "severity",
    "starts_at",
    "ip_address",
    "mac_address",
    "subnet",
    "record_type",
    "lease_time_seconds",
    "ttl",
}


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]
    tenant_scoped: bool = True
    soft_delete: bool = True

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | None = None) -> None:
        self.session = session
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------ queries
    def query(self, *, include_deleted: bool = False) -> Select:
        stmt = select(self.model)
        if self.tenant_scoped and self.tenant_id is not None:
            stmt = stmt.where(self.model.tenant_id == self.tenant_id)  # type: ignore[attr-defined]
        if self.soft_delete and not include_deleted:
            stmt = stmt.where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return stmt

    async def get(self, entity_id: uuid.UUID | str, *, include_deleted: bool = False) -> ModelT | None:
        stmt = self.query(include_deleted=include_deleted).where(self.model.id == entity_id)  # type: ignore[attr-defined]
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_or_404(self, entity_id: uuid.UUID | str) -> ModelT:
        entity = await self.get(entity_id)
        if entity is None:
            raise NotFoundError(f"{self.model.__name__} {entity_id} not found")
        return entity

    async def find_one(self, **filters: Any) -> ModelT | None:
        stmt = self.query().filter_by(**filters)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        filters: dict[str, Any] | None = None,
        search: str | None = None,
        search_fields: Sequence[str] = ("name",),
        page: int = 1,
        size: int = 50,
        sort: str | None = None,
        order: str = "desc",
        include_deleted: bool = False,
    ) -> tuple[list[ModelT], int]:
        stmt = self.query(include_deleted=include_deleted)
        if filters:
            for key, value in filters.items():
                if value is None:
                    continue
                column = getattr(self.model, key, None)
                if column is None:
                    continue
                stmt = stmt.where(column == value)
        if search:
            clauses = [
                getattr(self.model, field).ilike(f"%{search}%")
                for field in search_fields
                if hasattr(self.model, field)
            ]
            if clauses:
                from sqlalchemy import or_

                stmt = stmt.where(or_(*clauses))

        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

        column_name = sort if sort in SORTABLE and hasattr(self.model, sort) else "created_at"
        column = getattr(self.model, column_name, None)
        if column is not None:
            stmt = stmt.order_by(column.desc() if order.lower() == "desc" else column.asc())

        stmt = stmt.offset((page - 1) * size).limit(size)
        items = list((await self.session.execute(stmt)).scalars().unique().all())
        return items, int(total)

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.query().filter_by(**filters).subquery())
        return int((await self.session.execute(stmt)).scalar_one())

    async def exists(self, **filters: Any) -> bool:
        return await self.find_one(**filters) is not None

    # ------------------------------------------------------------------ mutations
    def add(self, entity: ModelT) -> ModelT:
        if self.tenant_scoped and self.tenant_id is not None and getattr(entity, "tenant_id", None) is None:
            entity.tenant_id = self.tenant_id  # type: ignore[attr-defined]
        self.session.add(entity)
        return entity

    async def create(self, **values: Any) -> ModelT:
        if self.tenant_scoped and self.tenant_id is not None:
            values.setdefault("tenant_id", self.tenant_id)
        entity = self.model(**values)
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: ModelT, **values: Any) -> ModelT:
        for key, value in values.items():
            if hasattr(entity, key):
                setattr(entity, key, value)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelT, *, hard: bool = False) -> None:
        if hard or not self.soft_delete:
            await self.session.delete(entity)
        else:
            from app.db.base import utcnow

            entity.deleted_at = utcnow()  # type: ignore[attr-defined]
        await self.session.flush()

    async def delete_by_id(self, entity_id: uuid.UUID) -> None:
        entity = await self.get_or_404(entity_id)
        await self.delete(entity)

    async def purge(self) -> int:
        """Only used by SUPER_ADMIN maintenance operations."""
        stmt = delete(self.model)
        if self.tenant_scoped and self.tenant_id is not None:
            stmt = stmt.where(self.model.tenant_id == self.tenant_id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)


class TenantRepository(BaseRepository[Tenant]):
    model = Tenant
    tenant_scoped = False
    soft_delete = True
