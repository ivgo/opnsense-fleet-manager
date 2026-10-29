"""Contract tests for the internal gRPC facade.

The server is started on an ephemeral loopback port and exercised with the
generated stub, so the metadata handling, tenant scoping and pagination in
``app/grpc/server.py`` are covered end to end against PostgreSQL.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import grpc
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.grpc.generated import fleet_pb2, fleet_pb2_grpc
from app.grpc.server import FleetRegistryService, start_server
from app.models.enums import ConnectionStatus, DeviceStatus, DriftStatus
from app.models.identity import Tenant
from app.models.policy import DriftReport
from app.models.topology import Device

SERVICE_TOKEN = "grpc-test-token-0123456789abcdef"
TENANT_HEADER = ("x-ofme-token", SERVICE_TOKEN)

TenantFactory = Callable[..., Coroutine[Any, Any, Tenant]]


@pytest_asyncio.fixture
async def channel(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[grpc.aio.Channel]:
    monkeypatch.setattr(settings, "GRPC_ENABLED", True)
    monkeypatch.setattr(settings, "GRPC_SERVICE_TOKEN", SERVICE_TOKEN)
    monkeypatch.setattr(settings, "GRPC_TLS_CERT_PATH", "")
    monkeypatch.setattr(settings, "GRPC_TLS_KEY_PATH", "")

    server = grpc.aio.server()
    fleet_pb2_grpc.add_FleetRegistryServicer_to_server(FleetRegistryService(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    client = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    try:
        yield client
    finally:
        await client.close()
        await server.stop(grace=0)


@pytest_asyncio.fixture
async def stub(channel: grpc.aio.Channel) -> fleet_pb2_grpc.FleetRegistryStub:
    return fleet_pb2_grpc.FleetRegistryStub(channel)


async def _device(
    session_factory: async_sessionmaker[AsyncSession],
    tenant: Tenant,
    *,
    name: str,
    status: DeviceStatus = DeviceStatus.ONLINE,
    is_ha: bool = False,
    serial: str | None = None,
) -> Device:
    async with session_factory() as session:
        device = Device(
            tenant_id=tenant.id,
            name=name,
            hostname=f"{name}.example.test",
            serial_number=serial or f"SN-{uuid.uuid4().hex[:10].upper()}",
            status=status,
            connection_status=ConnectionStatus.CONNECTED,
            is_ha=is_ha,
            tags=["branch", "emea"],
            last_seen_at=datetime.now(UTC),
        )
        session.add(device)
        await session.commit()
        return device


@pytest.mark.asyncio(loop_scope="session")
async def test_requests_without_token_are_rejected(stub: fleet_pb2_grpc.FleetRegistryStub, tenant_factory):
    tenant = await tenant_factory()

    with pytest.raises(grpc.aio.AioRpcError) as missing:
        await stub.GetFleetSummary(fleet_pb2.GetFleetSummaryRequest(tenant_id=str(tenant.id)))
    assert missing.value.code() == grpc.StatusCode.UNAUTHENTICATED

    with pytest.raises(grpc.aio.AioRpcError) as wrong:
        await stub.GetFleetSummary(
            fleet_pb2.GetFleetSummaryRequest(tenant_id=str(tenant.id)),
            metadata=(("x-ofme-token", "not-the-token"),),
        )
    assert wrong.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio(loop_scope="session")
async def test_tenant_id_must_be_a_uuid(stub: fleet_pb2_grpc.FleetRegistryStub):
    with pytest.raises(grpc.aio.AioRpcError) as invalid:
        await stub.GetFleetSummary(
            fleet_pb2.GetFleetSummaryRequest(tenant_id="acme"), metadata=(TENANT_HEADER,)
        )
    assert invalid.value.code() == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.asyncio(loop_scope="session")
async def test_get_device_is_scoped_to_the_requested_tenant(
    stub: fleet_pb2_grpc.FleetRegistryStub,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
):
    tenant = await tenant_factory(name="Northwind")
    other = await tenant_factory(name="Contoso")
    device = await _device(session_factory, tenant, name="fw-north-01", is_ha=True)

    response = await stub.GetDevice(
        fleet_pb2.GetDeviceRequest(tenant_id=str(tenant.id), device_id=str(device.id)),
        metadata=(TENANT_HEADER,),
    )
    assert response.name == "fw-north-01"
    assert response.tenant_id == str(tenant.id)
    assert response.status == "online"
    assert response.is_ha is True
    assert response.tags == ["branch", "emea"]
    assert response.last_seen_at.seconds > 0

    with pytest.raises(grpc.aio.AioRpcError) as foreign:
        await stub.GetDevice(
            fleet_pb2.GetDeviceRequest(tenant_id=str(other.id), device_id=str(device.id)),
            metadata=(TENANT_HEADER,),
        )
    assert foreign.value.code() == grpc.StatusCode.NOT_FOUND

    with pytest.raises(grpc.aio.AioRpcError) as unknown:
        await stub.GetDevice(
            fleet_pb2.GetDeviceRequest(tenant_id=str(tenant.id), device_id=str(uuid.uuid4())),
            metadata=(TENANT_HEADER,),
        )
    assert unknown.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio(loop_scope="session")
async def test_list_devices_paginates_filters_and_hides_other_tenants(
    stub: fleet_pb2_grpc.FleetRegistryStub,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
):
    tenant = await tenant_factory(name="Fabrikam")
    other = await tenant_factory(name="Tailspin")
    await _device(session_factory, tenant, name="fw-a-01", status=DeviceStatus.ONLINE)
    await _device(session_factory, tenant, name="fw-a-02", status=DeviceStatus.OFFLINE)
    await _device(session_factory, tenant, name="fw-a-03", status=DeviceStatus.ONLINE)
    await _device(session_factory, other, name="fw-b-01", status=DeviceStatus.ONLINE)

    first = await stub.ListDevices(
        fleet_pb2.ListDevicesRequest(tenant_id=str(tenant.id), page=1, size=2),
        metadata=(TENANT_HEADER,),
    )
    assert first.total == 3
    assert first.pages == 2
    assert first.page == 1
    assert first.size == 2
    assert [device.name for device in first.devices] == ["fw-a-01", "fw-a-02"]

    second = await stub.ListDevices(
        fleet_pb2.ListDevicesRequest(tenant_id=str(tenant.id), page=2, size=2),
        metadata=(TENANT_HEADER,),
    )
    assert [device.name for device in second.devices] == ["fw-a-03"]

    online = await stub.ListDevices(
        fleet_pb2.ListDevicesRequest(tenant_id=str(tenant.id), status="online"),
        metadata=(TENANT_HEADER,),
    )
    assert online.total == 2
    assert {device.status for device in online.devices} == {"online"}

    searched = await stub.ListDevices(
        fleet_pb2.ListDevicesRequest(tenant_id=str(tenant.id), search="A-02"),
        metadata=(TENANT_HEADER,),
    )
    assert searched.total == 1
    assert searched.devices[0].name == "fw-a-02"

    clamped = await stub.ListDevices(
        fleet_pb2.ListDevicesRequest(tenant_id=str(tenant.id), page=0, size=10_000),
        metadata=(TENANT_HEADER,),
    )
    assert clamped.page == 1
    assert clamped.size == 500


@pytest.mark.asyncio(loop_scope="session")
async def test_fleet_summary_counts_status_ha_and_open_drift(
    stub: fleet_pb2_grpc.FleetRegistryStub,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_factory,
):
    tenant = await tenant_factory(name="Woodgrove")
    online = await _device(session_factory, tenant, name="fw-w-01", is_ha=True)
    await _device(session_factory, tenant, name="fw-w-02", status=DeviceStatus.OFFLINE)
    await _device(session_factory, tenant, name="fw-w-03", status=DeviceStatus.REGISTERED)

    async with session_factory() as session:
        session.add(
            DriftReport(
                tenant_id=tenant.id,
                device_id=online.id,
                status=DriftStatus.OPEN,
                differences=[{"path": "firewall.rules", "expected": 3, "actual": 2}],
                detected_at=datetime.now(UTC),
                notes="One rule missing",
            )
        )
        await session.commit()

    summary = await stub.GetFleetSummary(
        fleet_pb2.GetFleetSummaryRequest(tenant_id=str(tenant.id)), metadata=(TENANT_HEADER,)
    )
    assert summary.total == 3
    assert summary.online == 1
    assert summary.offline == 1
    assert summary.registered == 1
    assert summary.error == 0
    assert summary.maintenance == 0
    assert summary.unregistered == 0
    assert summary.ha_devices == 1
    assert summary.drift_findings == 1
    assert summary.generated_at.seconds > 0


@pytest.mark.asyncio(loop_scope="session")
async def test_start_server_is_disabled_without_flag_or_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "GRPC_ENABLED", False)
    monkeypatch.setattr(settings, "GRPC_SERVICE_TOKEN", SERVICE_TOKEN)
    assert await start_server() is None

    monkeypatch.setattr(settings, "GRPC_ENABLED", True)
    monkeypatch.setattr(settings, "GRPC_SERVICE_TOKEN", "")
    assert await start_server() is None
