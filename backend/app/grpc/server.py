"""gRPC facade: ``ofme.fleet.v1.FleetRegistry``.

The service is an internal, read-only contract for automation that is easier to
express in RPC than in REST (reporting exporters, Terraform/Ansible providers,
SIEM connectors). It reuses the same SQLAlchemy models and tenant scoping as the
HTTP API; there is no second source of truth.

Security
--------
* disabled unless ``GRPC_ENABLED=true``;
* requires a static service token in the ``x-ofme-token`` metadata entry
  (``GRPC_SERVICE_TOKEN``); requests without it are rejected with
  ``UNAUTHENTICATED``;
* serves plaintext on the cluster network by default - terminate TLS in the
  service mesh, or set ``GRPC_TLS_CERT_PATH``/``GRPC_TLS_KEY_PATH``;
* every request names a tenant explicitly, and all queries are filtered by it.
"""

from __future__ import annotations

import asyncio
import hmac
import uuid
from datetime import UTC, datetime
from pathlib import Path

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from sqlalchemy import func, or_, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.grpc.generated import fleet_pb2, fleet_pb2_grpc
from app.models.enums import DriftStatus
from app.models.policy import DriftReport
from app.models.topology import Device

log = get_logger("ofme.grpc")

MAX_PAGE_SIZE = 500
_TOKEN_METADATA_KEY = "x-ofme-token"


def _timestamp(value: datetime | None) -> Timestamp | None:
    if value is None:
        return None
    stamp = Timestamp()
    stamp.FromDatetime(value if value.tzinfo else value.replace(tzinfo=UTC))
    return stamp


def _device_message(device: Device) -> fleet_pb2.DeviceInfo:
    return fleet_pb2.DeviceInfo(
        id=str(device.id),
        tenant_id=str(device.tenant_id),
        name=device.name,
        hostname=device.hostname or "",
        description=device.description or "",
        status=device.status.value,
        connection_status=device.connection_status.value,
        firmware_version=device.firmware_version or "",
        agent_version=device.agent_version or "",
        model=device.model or "",
        serial_number=device.serial_number or "",
        ip_address=device.ip_address or "",
        site_id=str(device.site_id) if device.site_id else "",
        group_id=str(device.group_id) if device.group_id else "",
        is_ha=bool(device.is_ha),
        ha_role=device.ha_role.value if device.ha_role else "",
        tags=[str(tag) for tag in (device.tags or [])],
        last_seen_at=_timestamp(device.last_seen_at),
        created_at=_timestamp(device.created_at),
        updated_at=_timestamp(device.updated_at),
    )


async def _authorize(context: grpc.aio.ServicerContext) -> None:
    supplied = ""
    for item in context.invocation_metadata():
        if item.key == _TOKEN_METADATA_KEY:
            supplied = item.value
            break
    if not supplied or not hmac.compare_digest(supplied, settings.GRPC_SERVICE_TOKEN):
        await context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid or missing service token")


async def _tenant_id(context: grpc.aio.ServicerContext, raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "tenant_id must be a UUID")
        raise  # pragma: no cover - abort() never returns


class FleetRegistryService(fleet_pb2_grpc.FleetRegistryServicer):
    async def GetDevice(self, request, context):  # noqa: N802, ANN001, ANN201
        await _authorize(context)
        tenant_id = await _tenant_id(context, request.tenant_id)
        try:
            device_id = uuid.UUID(request.device_id)
        except (ValueError, AttributeError, TypeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "device_id must be a UUID")

        async with async_session_factory() as session:
            device = (
                (
                    await session.execute(
                        select(Device).where(
                            Device.id == device_id,
                            Device.tenant_id == tenant_id,
                            Device.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .first()
            )
        if device is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "device not found in this tenant")
        return _device_message(device)

    async def ListDevices(self, request, context):  # noqa: N802, ANN001, ANN201
        await _authorize(context)
        tenant_id = await _tenant_id(context, request.tenant_id)
        page = max(int(request.page or 1), 1)
        size = min(max(int(request.size or 50), 1), MAX_PAGE_SIZE)

        filters = [Device.tenant_id == tenant_id, Device.deleted_at.is_(None)]
        if request.status:
            filters.append(Device.status == request.status)
        if request.search:
            pattern = f"%{request.search.strip()}%"
            filters.append(
                or_(
                    Device.name.ilike(pattern),
                    Device.hostname.ilike(pattern),
                    Device.serial_number.ilike(pattern),
                )
            )

        async with async_session_factory() as session:
            total = int(
                (await session.execute(select(func.count()).select_from(Device).where(*filters))).scalar_one()
            )
            rows = (
                (
                    await session.execute(
                        select(Device)
                        .where(*filters)
                        .order_by(Device.name.asc())
                        .offset((page - 1) * size)
                        .limit(size)
                    )
                )
                .scalars()
                .all()
            )

        pages = (total + size - 1) // size if size else 0
        return fleet_pb2.ListDevicesResponse(
            devices=[_device_message(device) for device in rows],
            page=page,
            size=size,
            total=total,
            pages=pages,
        )

    async def GetFleetSummary(self, request, context):  # noqa: N802, ANN001, ANN201
        await _authorize(context)
        tenant_id = await _tenant_id(context, request.tenant_id)

        async with async_session_factory() as session:
            status_rows = (
                await session.execute(
                    select(Device.status, func.count())
                    .where(Device.tenant_id == tenant_id, Device.deleted_at.is_(None))
                    .group_by(Device.status)
                )
            ).all()
            ha_devices = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Device)
                        .where(
                            Device.tenant_id == tenant_id,
                            Device.deleted_at.is_(None),
                            Device.is_ha.is_(True),
                        )
                    )
                ).scalar_one()
            )
            drift_findings = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(DriftReport)
                        .where(
                            DriftReport.tenant_id == tenant_id,
                            DriftReport.status == DriftStatus.OPEN,
                        )
                    )
                ).scalar_one()
            )

        counts = {status.value: int(count) for status, count in status_rows}
        total = sum(counts.values())
        return fleet_pb2.FleetSummary(
            total=total,
            online=counts.get("online", 0),
            offline=counts.get("offline", 0),
            error=counts.get("error", 0),
            maintenance=counts.get("maintenance", 0),
            unregistered=counts.get("unregistered", 0),
            registered=counts.get("registered", 0),
            ha_devices=ha_devices,
            drift_findings=drift_findings,
            generated_at=_timestamp(datetime.now(UTC)),
        )


async def start_server() -> grpc.aio.Server | None:
    """Start the gRPC server; returns ``None`` when the feature is disabled.

    TLS Configuration:
    - Server TLS: GRPC_TLS_CERT_PATH + GRPC_TLS_KEY_PATH
    - Client cert verification (mTLS): GRPC_TLS_CA_CERT_PATH + GRPC_REQUIRE_CLIENT_CERT
    - When GRPC_REQUIRE_CLIENT_CERT=true, clients must present a valid certificate
      signed by the CA specified in GRPC_TLS_CA_CERT_PATH.
    """

    if not settings.GRPC_ENABLED:
        return None
    if not settings.GRPC_SERVICE_TOKEN:
        log.error("grpc.disabled", reason="GRPC_SERVICE_TOKEN is empty")
        return None

    server = grpc.aio.server()
    fleet_pb2_grpc.add_FleetRegistryServicer_to_server(FleetRegistryService(), server)

    if settings.GRPC_TLS_CERT_PATH and settings.GRPC_TLS_KEY_PATH:
        certificate, private_key = await asyncio.gather(
            asyncio.to_thread(Path(settings.GRPC_TLS_CERT_PATH).read_bytes),
            asyncio.to_thread(Path(settings.GRPC_TLS_KEY_PATH).read_bytes),
        )

        if settings.GRPC_TLS_CA_CERT_PATH and settings.GRPC_REQUIRE_CLIENT_CERT:
            # mTLS: require client certificates signed by specified CA
            ca_cert = await asyncio.to_thread(Path(settings.GRPC_TLS_CA_CERT_PATH).read_bytes)
            credentials = grpc.ssl_server_credentials(
                ((private_key, certificate),),
                root_certificates=ca_cert,
                require_client_auth=True,
            )
            scheme = "mtls"
            log.info("grpc.tls_configured", mode="mtls", client_auth="required")
        elif settings.GRPC_TLS_CA_CERT_PATH:
            # Optional client cert verification
            ca_cert = await asyncio.to_thread(Path(settings.GRPC_TLS_CA_CERT_PATH).read_bytes)
            credentials = grpc.ssl_server_credentials(
                ((private_key, certificate),),
                root_certificates=ca_cert,
                require_client_auth=False,
            )
            scheme = "tls"
            log.info("grpc.tls_configured", mode="tls", client_auth="optional")
        else:
            # Server TLS only, no client cert verification
            credentials = grpc.ssl_server_credentials(((private_key, certificate),))
            scheme = "tls"
            log.info("grpc.tls_configured", mode="tls", client_auth="none")

        server.add_secure_port(settings.GRPC_BIND, credentials)
    else:
        server.add_insecure_port(settings.GRPC_BIND)
        scheme = "plaintext"
        if settings.GRPC_REQUIRE_CLIENT_CERT:
            log.warning("grpc.mtls_ignored", reason="GRPC_TLS_CERT_PATH or GRPC_TLS_KEY_PATH not set")

    await server.start()
    log.info("grpc.started", bind=settings.GRPC_BIND, transport=scheme)
    return server


async def stop_server(server: grpc.aio.Server | None) -> None:
    if server is None:
        return
    await server.stop(grace=10)
    log.info("grpc.stopped")


__all__ = ["FleetRegistryService", "start_server", "stop_server"]
