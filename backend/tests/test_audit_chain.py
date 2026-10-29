"""Tamper-evident audit chain and domain event store tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.events import DomainEvent
from app.models.audit import AuditLog
from app.models.enums import AuditResult
from app.services.audit import AuditService, EventStoreService, _canonical, _hash_entry
from tests.conftest import TenantFactory


def test_canonical_json_is_stable() -> None:
    assert _canonical({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert _canonical({"a": [1, 2]}) == _canonical({"a": [1, 2]})


def test_hash_entry_is_sensitive_to_previous_hash() -> None:
    payload = {"action": "device.created"}
    assert _hash_entry("GENESIS", payload) != _hash_entry("other", payload)
    assert _hash_entry("GENESIS", payload) != _hash_entry("GENESIS", {"action": "device.deleted"})


@pytest.mark.asyncio(loop_scope="session")
async def test_audit_chain_verifies(db_session, tenant_factory: TenantFactory) -> None:
    tenant = await tenant_factory()
    service = AuditService(db_session)

    for index in range(3):
        await service.record(
            action=f"test.action.{index}",
            resource_type="Device",
            resource_id=uuid.uuid4(),
            tenant_id=tenant.id,
            actor="pytest",
            result=AuditResult.SUCCESS,
            after={"index": index},
        )
    await db_session.commit()

    ok, broken_id, head = await service.verify_chain()
    assert ok is True
    assert broken_id is None
    assert head

    rows = (await db_session.execute(select(AuditLog).order_by(AuditLog.id.asc()))).scalars().all()
    assert len(rows) == 3
    assert rows[0].prev_hash == "GENESIS"
    assert rows[1].prev_hash == rows[0].entry_hash
    assert rows[2].prev_hash == rows[1].entry_hash


@pytest.mark.asyncio(loop_scope="session")
async def test_audit_chain_detects_tampering(db_session, tenant_factory: TenantFactory) -> None:
    tenant = await tenant_factory()
    service = AuditService(db_session)
    for index in range(3):
        await service.record(
            action=f"test.action.{index}",
            resource_type="Device",
            tenant_id=tenant.id,
            actor="original",
        )
    await db_session.commit()

    rows = (await db_session.execute(select(AuditLog).order_by(AuditLog.id.asc()))).scalars().all()
    target = rows[1]
    target.actor = "tampered"
    await db_session.commit()

    ok, broken_id, _head = await service.verify_chain()
    assert ok is False
    assert broken_id == target.id


@pytest.mark.asyncio(loop_scope="session")
async def test_audit_chain_detects_deleted_tail(db_session, tenant_factory: TenantFactory) -> None:
    tenant = await tenant_factory()
    service = AuditService(db_session)
    for index in range(3):
        await service.record(action=f"test.action.{index}", resource_type="Device", tenant_id=tenant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(AuditLog).order_by(AuditLog.id.asc()))).scalars().all()
    await db_session.delete(rows[1])
    await db_session.commit()

    ok, broken_id, _head = await service.verify_chain()
    assert ok is False
    assert broken_id == rows[2].id


@pytest.mark.asyncio(loop_scope="session")
async def test_event_store_sequences_and_hashes(db_session, tenant_factory: TenantFactory) -> None:
    tenant = await tenant_factory()
    service = EventStoreService(db_session)
    aggregate_id = str(uuid.uuid4())

    for index in range(3):
        await service.append(
            DomainEvent(
                event_type="device.heartbeat",
                aggregate_type="Device",
                aggregate_id=aggregate_id,
                tenant_id=str(tenant.id),
                payload={"index": index},
            )
        )
    await db_session.commit()

    events = await service.for_aggregate("Device", aggregate_id)
    assert [event.sequence for event in events] == [1, 2, 3]
    assert events[0].previous_hash == "GENESIS"
    assert events[1].previous_hash == events[0].event_hash
    assert events[2].previous_hash == events[1].event_hash
    assert all(event.event_hash and len(event.event_hash) == 64 for event in events)


@pytest.mark.asyncio(loop_scope="session")
async def test_event_store_isolated_per_aggregate(db_session, tenant_factory: TenantFactory) -> None:
    tenant = await tenant_factory()
    service = EventStoreService(db_session)
    first = str(uuid.uuid4())
    second = str(uuid.uuid4())

    await service.append(
        DomainEvent(
            event_type="device.heartbeat",
            aggregate_type="Device",
            aggregate_id=first,
            tenant_id=str(tenant.id),
        )
    )
    await service.append(
        DomainEvent(
            event_type="device.heartbeat",
            aggregate_type="Device",
            aggregate_id=second,
            tenant_id=str(tenant.id),
        )
    )
    await db_session.commit()

    assert [event.sequence for event in await service.for_aggregate("Device", first)] == [1]
    assert [event.sequence for event in await service.for_aggregate("Device", second)] == [1]
