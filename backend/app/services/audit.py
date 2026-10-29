"""Tamper-evident audit trail + domain event persistence.

Every audit row stores ``prev_hash`` and ``entry_hash``; ``entry_hash`` is
``sha256(prev_hash || canonical_json(entry))``. Deleting or editing a row breaks
the chain and is detected by :meth:`AuditService.verify_chain`.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent
from app.core.logging import get_logger
from app.models.audit import AuditLog, DomainEventRecord
from app.models.enums import AuditResult

log = get_logger("ofme.audit")

_CHAIN_LOCK_KEY = 918_273_645


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash_entry(prev_hash: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(payload)).encode("utf-8")).hexdigest()


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: str | uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        actor: str | None = None,
        result: AuditResult = AuditResult.SUCCESS,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        method: str | None = None,
        path: str | None = None,
        status_code: int | None = None,
        before: dict | None = None,
        after: dict | None = None,
        error: str | None = None,
        metadata: dict | None = None,
    ) -> AuditLog:
        # Serialise chain appends across workers.
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CHAIN_LOCK_KEY})
        last = (
            await self.session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))
        ).scalar_one_or_none()
        prev_hash = last.entry_hash if last and last.entry_hash else "GENESIS"

        entry = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            result=result,
            ip_address=ip_address,
            user_agent=(user_agent or "")[:512] or None,
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            before=before,
            after=after,
            error=error,
            metadata_=metadata or {},
            prev_hash=prev_hash,
        )
        payload = {
            "tenant_id": str(tenant_id) if tenant_id else None,
            "user_id": str(user_id) if user_id else None,
            "actor": actor,
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "result": result.value if hasattr(result, "value") else str(result),
            "status_code": status_code,
            "before": before,
            "after": after,
            "error": error,
        }
        entry.entry_hash = _hash_entry(prev_hash, payload)
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def search(
        self,
        *,
        tenant_id: uuid.UUID | None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        user_id: uuid.UUID | None = None,
        result: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[AuditLog], int]:
        stmt = select(AuditLog)
        if tenant_id:
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if resource_type:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if resource_id:
            stmt = stmt.where(AuditLog.resource_id == resource_id)
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if result:
            stmt = stmt.where(AuditLog.result == result)
        if from_date:
            stmt = stmt.where(AuditLog.created_at >= from_date)
        if to_date:
            stmt = stmt.where(AuditLog.created_at <= to_date)

        total = (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    async def verify_chain(self, limit: int = 10_000) -> tuple[bool, int | None, str | None]:
        rows = (
            (await self.session.execute(select(AuditLog).order_by(AuditLog.id.asc()).limit(limit)))
            .scalars()
            .all()
        )
        previous = "GENESIS"
        for row in rows:
            payload = {
                "tenant_id": str(row.tenant_id) if row.tenant_id else None,
                "user_id": str(row.user_id) if row.user_id else None,
                "actor": row.actor,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "result": row.result.value if hasattr(row.result, "value") else str(row.result),
                "status_code": row.status_code,
                "before": row.before,
                "after": row.after,
                "error": row.error,
            }
            expected = _hash_entry(row.prev_hash or "GENESIS", payload)
            if row.prev_hash != previous or row.entry_hash != expected:
                return False, row.id, row.entry_hash
            previous = row.entry_hash or ""
        return True, None, previous if rows else None


class EventStoreService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, event: DomainEvent) -> DomainEventRecord:
        last = (
            await self.session.execute(
                select(DomainEventRecord)
                .where(
                    DomainEventRecord.aggregate_type == event.aggregate_type,
                    DomainEventRecord.aggregate_id == event.aggregate_id,
                )
                .order_by(DomainEventRecord.sequence.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        sequence = (last.sequence + 1) if last else 1
        previous_hash = last.event_hash if last else "GENESIS"
        body = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "tenant_id": event.tenant_id,
            "payload": event.payload,
            "sequence": sequence,
            "occurred_at": event.occurred_at.isoformat(),
        }
        record = DomainEventRecord(
            event_id=event.event_id,
            tenant_id=uuid.UUID(event.tenant_id) if event.tenant_id else None,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            event_type=event.event_type,
            sequence=sequence,
            payload=event.payload,
            previous_hash=previous_hash,
            event_hash=_hash_entry(previous_hash, body),
            occurred_at=event.occurred_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def for_aggregate(self, aggregate_type: str, aggregate_id: str) -> list[DomainEventRecord]:
        stmt = (
            select(DomainEventRecord)
            .where(
                DomainEventRecord.aggregate_type == aggregate_type,
                DomainEventRecord.aggregate_id == aggregate_id,
            )
            .order_by(DomainEventRecord.sequence.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())


async def persist_event_handler(event: DomainEvent) -> None:
    """Subscribed to the global event bus; persists every domain event."""
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        try:
            await EventStoreService(session).append(event)
            await session.commit()
        except Exception:  # noqa: BLE001 - never break business flow on telemetry
            await session.rollback()
            log.exception("event_store.persist_failed", event_type=event.event_type)


def utcnow() -> datetime:
    return datetime.now(UTC)
