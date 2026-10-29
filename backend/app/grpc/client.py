"""gRPC client factory for the ``ofme.fleet.v1.FleetRegistry`` service.

Security
--------
* disabled unless ``GRPC_ENABLED=true``;
* requires a static service token in the ``x-ofme-token`` metadata entry
  (``GRPC_SERVICE_TOKEN``);
* supports TLS (server cert verification) and mTLS (client certificate
  authentication) via ``GRPC_TLS_CA_CERT_PATH``, ``GRPC_TLS_CERT_PATH``
  and ``GRPC_TLS_KEY_PATH``;
* every request names a tenant explicitly, and all queries are filtered by it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import grpc

from app.core.config import settings
from app.core.logging import get_logger
from app.grpc.generated import fleet_pb2, fleet_pb2_grpc

log = get_logger("ofme.grpc_client")

_TOKEN_METADATA_KEY = "x-ofme-token"


def _load_credentials():
    """Build gRPC channel credentials from configured TLS paths.

    Returns ``None`` when no TLS configuration is set (plaintext channel).
    """
    if settings.GRPC_TLS_CA_CERT_PATH and settings.GRPC_TLS_CERT_PATH and settings.GRPC_TLS_KEY_PATH:
        # mTLS: client presents a certificate signed by the CA
        root_cert = Path(settings.GRPC_TLS_CA_CERT_PATH).read_bytes()
        client_cert = Path(settings.GRPC_TLS_CERT_PATH).read_bytes()
        client_key = Path(settings.GRPC_TLS_KEY_PATH).read_bytes()
        return grpc.ssl_channel_credentials(
            root_certificates=root_cert,
            private_key=client_key,
            certificate_chain=client_cert,
        )
    if settings.GRPC_TLS_CA_CERT_PATH:
        # TLS with server cert verification only
        root_cert = Path(settings.GRPC_TLS_CA_CERT_PATH).read_bytes()
        return grpc.ssl_channel_credentials(root_certificates=root_cert)
    return None


async def get_channel() -> grpc.aio.Channel | None:
    """Create a gRPC channel with TLS/mTLS support.

    Returns ``None`` when gRPC is disabled or misconfigured.
    """
    if not settings.GRPC_ENABLED:
        log.debug("grpc.client_disabled")
        return None
    if not settings.GRPC_SERVICE_TOKEN:
        log.error("grpc.client_disabled", reason="GRPC_SERVICE_TOKEN is empty")
        return None

    credentials = _load_credentials()
    if credentials is not None:
        channel = grpc.aio.secure_channel(settings.GRPC_BIND, credentials)
        scheme = "mtls" if settings.GRPC_TLS_CERT_PATH and settings.GRPC_TLS_KEY_PATH else "tls"
    else:
        channel = grpc.aio.insecure_channel(settings.GRPC_BIND)
        scheme = "plaintext"

    log.info("grpc.channel_created", bind=settings.GRPC_BIND, transport=scheme)
    return channel


async def get_stub() -> fleet_pb2_grpc.FleetRegistryStub | None:
    """Return a ready-to-use FleetRegistry stub, or ``None`` when gRPC is off."""
    channel = await get_channel()
    if channel is None:
        return None
    return fleet_pb2_grpc.FleetRegistryStub(channel)


def _inject_token(metadata: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Add the service token to outbound gRPC metadata."""
    if settings.GRPC_SERVICE_TOKEN:
        metadata.append((_TOKEN_METADATA_KEY, settings.GRPC_SERVICE_TOKEN))
    return metadata


async def call_get_device(device_id: str, tenant_id: str) -> fleet_pb2.DeviceInfo | None:
    """Call GetDevice with TLS/mTLS support and service token auth."""
    stub = await get_stub()
    if stub is None:
        return None
    try:
        response = await stub.GetDevice(
            fleet_pb2.GetDeviceRequest(device_id=device_id, tenant_id=tenant_id),
            metadata=_inject_token([]),
        )
        return response
    except grpc.aio.AioRpcError as exc:
        log.error("grpc.call_failed", method="GetDevice", code=exc.code().name, error=str(exc))
        raise


async def call_list_devices(
    tenant_id: str,
    page: int = 1,
    size: int = 50,
    status: str = "",
    search: str = "",
) -> fleet_pb2.ListDevicesResponse | None:
    """Call ListDevices with TLS/mTLS support and service token auth."""
    stub = await get_stub()
    if stub is None:
        return None
    try:
        response = await stub.ListDevices(
            fleet_pb2.ListDevicesRequest(
                tenant_id=tenant_id,
                page=page,
                size=size,
                status=status,
                search=search,
            ),
            metadata=_inject_token([]),
        )
        return response
    except grpc.aio.AioRpcError as exc:
        log.error("grpc.call_failed", method="ListDevices", code=exc.code().name, error=str(exc))
        raise


async def call_get_fleet_summary(tenant_id: str) -> fleet_pb2.FleetSummary | None:
    """Call GetFleetSummary with TLS/mTLS support and service token auth."""
    stub = await get_stub()
    if stub is None:
        return None
    try:
        response = await stub.GetFleetSummary(
            fleet_pb2.GetFleetSummaryRequest(tenant_id=tenant_id),
            metadata=_inject_token([]),
        )
        return response
    except grpc.aio.AioRpcError as exc:
        log.error("grpc.call_failed", method="GetFleetSummary", code=exc.code().name, error=str(exc))
        raise


__all__ = [
    "get_channel",
    "get_stub",
    "call_get_device",
    "call_list_devices",
    "call_get_fleet_summary",
]