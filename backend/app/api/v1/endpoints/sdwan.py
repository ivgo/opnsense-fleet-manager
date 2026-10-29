"""SD-WAN controller: topologies, tunnels, links, steering and route distribution."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.api.deps import (
    CurrentPrincipal,
    DeviceDep,
    PaginationDep,
    SessionDep,
    TenantDep,
    require_permissions,
)
from app.api.v1.endpoints._common import paginate
from app.core.exceptions import BadRequestError
from app.models.enums import SteeringStrategy
from app.rbac.permissions import P
from app.repositories import UnitOfWork
from app.schemas.common import Message, PageResponse
from app.schemas.sdwan import (
    LinkMeasurement,
    LinkOut,
    RouteOut,
    TopologyCreate,
    TopologyDeployRequest,
    TopologyDeployResult,
    TopologyGraph,
    TopologyOut,
    TopologyUpdate,
    TrafficPolicyOut,
    TunnelCreate,
    TunnelOut,
    VpnStatusOut,
    WireGuardKeyOut,
)
from app.services.audit import AuditService
from app.services.sdwan import (
    RouteManager,
    SdwanHealthService,
    SteeringService,
    TopologyService,
    TunnelProvisioner,
    VpnStatusService,
)

router = APIRouter(prefix="/sdwan", tags=["SD-WAN"])


class TrafficPolicyBody(BaseModel):
    topology_id: uuid.UUID
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    strategy: SteeringStrategy = SteeringStrategy.LOWEST_LATENCY
    match: dict = Field(default_factory=dict)
    preferred_link_ids: list[uuid.UUID] = Field(default_factory=list)
    priority: int = 100
    enabled: bool = True


# --------------------------------------------------------------------------- topologies
@router.get(
    "/topologies",
    response_model=PageResponse[TopologyOut],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List SD-WAN topologies",
)
async def list_topologies(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    search: str | None = Query(None, max_length=128),
) -> PageResponse[TopologyOut]:
    rows, total = await UnitOfWork(session, tenant_id).topologies.list(
        search=search,
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "name",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, TopologyOut)


@router.post(
    "/topologies",
    response_model=TopologyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Create a topology",
)
async def create_topology(
    payload: TopologyCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> TopologyOut:
    topology = await TopologyService(session, tenant_id, principal.user_id).create(payload)
    await session.commit()
    return TopologyOut.model_validate(topology)


@router.get(
    "/topologies/{topology_id}",
    response_model=TopologyOut,
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="Get a topology",
)
async def get_topology(topology_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> TopologyOut:
    return TopologyOut.model_validate(await UnitOfWork(session, tenant_id).topologies.get_or_404(topology_id))


@router.patch(
    "/topologies/{topology_id}",
    response_model=TopologyOut,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Update a topology",
)
async def update_topology(
    topology_id: uuid.UUID,
    payload: TopologyUpdate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> TopologyOut:
    topology = await TopologyService(session, tenant_id, principal.user_id).update(topology_id, payload)
    await session.commit()
    return TopologyOut.model_validate(topology)


@router.delete(
    "/topologies/{topology_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Delete a topology",
)
async def delete_topology(topology_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    topology = await uow.topologies.get_or_404(topology_id)
    if await uow.tunnels.for_topology(topology_id):
        raise BadRequestError("Delete the topology's tunnels first")
    await uow.topologies.delete(topology)
    await session.commit()
    return Message(message="Topology deleted")


@router.get(
    "/topologies/{topology_id}/graph",
    response_model=TopologyGraph,
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="Topology graph (nodes and links)",
)
async def topology_graph(topology_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> TopologyGraph:
    return await TopologyService(session, tenant_id).graph(topology_id)


@router.post(
    "/topologies/{topology_id}/deploy",
    response_model=TopologyDeployResult,
    dependencies=[Depends(require_permissions(P.SDWAN_DEPLOY))],
    summary="Plan and push tunnels and routes",
)
async def deploy_topology(
    topology_id: uuid.UUID,
    payload: TopologyDeployRequest,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> TopologyDeployResult:
    return await TunnelProvisioner(session, tenant_id, principal.user_id).provision_topology(
        topology_id,
        regenerate_keys=payload.regenerate_keys,
        dry_run=payload.dry_run,
    )


@router.get(
    "/topologies/{topology_id}/vpn-status",
    response_model=VpnStatusOut,
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="Poll VPN state from both ends of every tunnel",
    description=(
        "Reads WireGuard handshakes, OpenVPN instances and IPsec sessions from every "
        "device in the topology and refreshes the tunnel status."
    ),
)
async def vpn_status(topology_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> VpnStatusOut:
    return await VpnStatusService(session, tenant_id).refresh(topology_id)


@router.get(
    "/topologies/{topology_id}/wireguard-keys",
    response_model=list[WireGuardKeyOut],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List WireGuard public keys and tunnel addresses",
    description="Private keys are never returned by the API.",
)
async def list_wireguard_keys(
    topology_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> list[WireGuardKeyOut]:
    rows = await UnitOfWork(session, tenant_id).wireguard_keys.for_topology(topology_id)
    return [WireGuardKeyOut.model_validate(row) for row in rows]


@router.get(
    "/topologies/{topology_id}/routes",
    response_model=list[RouteOut],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="Routes installed by the controller",
)
async def topology_routes(
    topology_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> list[RouteOut]:
    rows, _ = await UnitOfWork(session, tenant_id).sdwan_routes.list(
        filters={"topology_id": topology_id}, size=1000
    )
    return [RouteOut.model_validate(row) for row in rows]


@router.post(
    "/topologies/{topology_id}/routes/sync/{device_id}",
    response_model=dict,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Recompute the route table of a device",
)
async def sync_topology_routes(
    topology_id: uuid.UUID,
    device_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
) -> dict:
    installed = await RouteManager(session, tenant_id).sync_routes(topology_id, device_id)
    await session.commit()
    return {"topology_id": str(topology_id), "device_id": str(device_id), "routes_installed": installed}


@router.get(
    "/topologies/{topology_id}/best-link",
    response_model=LinkOut | None,
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="Select the best link for a steering strategy",
)
async def best_link(
    topology_id: uuid.UUID,
    session: SessionDep,
    tenant_id: TenantDep,
    strategy: SteeringStrategy = Query(SteeringStrategy.LOWEST_LATENCY),
) -> LinkOut | None:
    link = await SteeringService(session, tenant_id).select_best_link(topology_id, strategy)
    return LinkOut.model_validate(link) if link is not None else None


@router.post(
    "/topologies/{topology_id}/failover",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Evaluate SLA violations and fail over",
)
async def evaluate_failover(topology_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> list[dict]:
    events = await SteeringService(session, tenant_id).evaluate_failover(topology_id)
    await session.commit()
    return events


# --------------------------------------------------------------------------- tunnels & links
@router.get(
    "/topologies/{topology_id}/tunnels",
    response_model=list[TunnelOut],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="Tunnels in a topology",
)
async def topology_tunnels(
    topology_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep
) -> list[TunnelOut]:
    rows = await UnitOfWork(session, tenant_id).tunnels.for_topology(topology_id)
    return [TunnelOut.model_validate(row) for row in rows]


@router.post(
    "/tunnels",
    response_model=TunnelOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Create a tunnel",
)
async def create_tunnel(
    payload: TunnelCreate,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> TunnelOut:
    tunnel = await TunnelProvisioner(session, tenant_id, principal.user_id).create_tunnel(payload)
    await session.commit()
    return TunnelOut.model_validate(tunnel)


@router.get(
    "/tunnels/{tunnel_id}",
    response_model=TunnelOut,
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="Get a tunnel",
)
async def get_tunnel(tunnel_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> TunnelOut:
    return TunnelOut.model_validate(await UnitOfWork(session, tenant_id).tunnels.get_or_404(tunnel_id))


@router.delete(
    "/tunnels/{tunnel_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Withdraw a tunnel",
)
async def delete_tunnel(tunnel_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    await RouteManager(session, tenant_id).withdraw(tunnel_id)
    uow = UnitOfWork(session, tenant_id)
    tunnel = await uow.tunnels.get_or_404(tunnel_id)
    await session.delete(tunnel)
    await session.commit()
    return Message(message="Tunnel withdrawn")


@router.get(
    "/links",
    response_model=PageResponse[LinkOut],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List WAN links",
)
async def list_links(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    topology_id: uuid.UUID | None = None,
) -> PageResponse[LinkOut]:
    rows, total = await UnitOfWork(session, tenant_id).links.list(
        filters={"topology_id": topology_id},
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "created_at",
        order=pagination.order,
    )
    return paginate(rows, total, pagination, LinkOut)


@router.post(
    "/links/{link_id}/measurements",
    response_model=LinkOut,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Record link telemetry",
)
async def record_measurement(
    link_id: uuid.UUID,
    payload: LinkMeasurement,
    session: SessionDep,
    tenant_id: TenantDep,
) -> LinkOut:
    link = await SdwanHealthService(session, tenant_id).record(
        link_id,
        latency_ms=payload.latency_ms,
        jitter_ms=payload.jitter_ms,
        loss_pct=payload.loss_pct,
        bandwidth_mbps=payload.bandwidth_mbps,
        status=payload.status,
    )
    await session.commit()
    return LinkOut.model_validate(link)


# --------------------------------------------------------------------------- traffic policies
@router.get(
    "/traffic-policies",
    response_model=PageResponse[TrafficPolicyOut],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List traffic steering policies",
)
async def list_traffic_policies(
    session: SessionDep,
    tenant_id: TenantDep,
    pagination: PaginationDep,
    topology_id: uuid.UUID | None = None,
) -> PageResponse[TrafficPolicyOut]:
    rows, total = await UnitOfWork(session, tenant_id).traffic_policies.list(
        filters={"topology_id": topology_id},
        page=pagination.page,
        size=pagination.size,
        sort=pagination.sort or "priority",
        order="asc",
    )
    return paginate(rows, total, pagination, TrafficPolicyOut)


@router.post(
    "/traffic-policies",
    response_model=TrafficPolicyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Create a traffic steering policy",
)
async def create_traffic_policy(
    payload: TrafficPolicyBody, session: SessionDep, tenant_id: TenantDep
) -> TrafficPolicyOut:
    uow = UnitOfWork(session, tenant_id)
    await uow.topologies.get_or_404(payload.topology_id)
    row = await uow.traffic_policies.create(
        topology_id=payload.topology_id,
        name=payload.name,
        description=payload.description,
        strategy=payload.strategy,
        match=payload.match,
        preferred_link_ids=[str(link_id) for link_id in payload.preferred_link_ids],
        priority=payload.priority,
        enabled=payload.enabled,
    )
    await session.commit()
    return TrafficPolicyOut.model_validate(row)


@router.delete(
    "/traffic-policies/{policy_id}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Delete a traffic steering policy",
)
async def delete_traffic_policy(policy_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> Message:
    uow = UnitOfWork(session, tenant_id)
    await session.delete(await uow.traffic_policies.get_or_404(policy_id))
    await session.commit()
    return Message(message="Traffic policy deleted")


# --------------------------------------------------------------------------- device IPsec
class IpsecPhase1Body(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    remote: str = Field(min_length=1, max_length=128)
    local: str | None = None
    src: str = Field(default="0.0.0.0", description="Local IPsec endpoint")  # noqa: S104
    dst: str = Field(default="0.0.0.0", description="Remote IPsec endpoint")  # noqa: S104
    tunnel_network: str = Field(default="", description="Comma-separated CIDR list")
    encryption: str = "aes256gcm16"
    hash: str = "sha256"
    lifetime: int = Field(86400, ge=60, le=864000)
    iketype: str = "main"
    protocol: str = "esp"
    enabled: bool = True


class IpsecPhase2Body(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    tunnel_network: str = Field(default="", description="Comma-separated CIDR list")
    encryption: str = "aes256gcm16"
    hash: str = "sha256"
    lifetime: int = Field(86400, ge=60, le=864000)
    pfs: bool = True
    protocol: str = "esp"
    enabled: bool = True


class IpsecTunnelOut(BaseModel):
    name: str
    remote: str
    local: str | None
    tunnel_network: str
    encryption: str
    hash: str
    lifetime: int
    enabled: bool


@router.get(
    "/devices/{device_id}/ipsec/tunnels",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List IPsec tunnels configured on the OPNsense host",
)
async def list_ipsec_tunnels(device: DeviceDep, session: SessionDep, tenant_id: TenantDep) -> list[dict]:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        response = await client.search_ipsec_tunnels()
    rows = response.get("rows") or response.get("tunnels") or []
    return [row for row in rows if isinstance(row, dict)]


@router.post(
    "/devices/{device_id}/ipsec/tunnels",
    response_model=IpsecTunnelOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Create an IPsec tunnel (phase1 + phase2) on the OPNsense host",
)
async def create_ipsec_tunnel(
    device_id: uuid.UUID,
    phase1: IpsecPhase1Body,
    phase2: IpsecPhase2Body,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> IpsecTunnelOut:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    device = await UnitOfWork(session, tenant_id).devices.get_or_404(device_id)
    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        await client.add_ipsec_phase1(phase1.model_dump())
        await client.add_ipsec_phase2(phase2.model_dump())
        await client.apply_ipsec_phase1()
        await client.apply_ipsec()

    await AuditService(session).record(
        action="ipsec.tunnel_created",
        resource_type="Device",
        resource_id=device.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
        after={"name": phase1.name, "remote": phase1.remote},
    )
    await session.commit()
    return IpsecTunnelOut(
        name=phase1.name,
        remote=phase1.remote,
        local=phase1.local,
        tunnel_network=phase1.tunnel_network,
        encryption=phase1.encryption,
        hash=phase1.hash,
        lifetime=phase1.lifetime,
        enabled=phase1.enabled,
    )


@router.post(
    "/devices/{device_id}/ipsec/apply",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Reconfigure IPsec on the OPNsense host",
)
async def apply_ipsec(
    device: DeviceDep, session: SessionDep, tenant_id: TenantDep, principal: CurrentPrincipal
) -> Message:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        await client.apply_ipsec_phase1()
        await client.apply_ipsec()
    await AuditService(session).record(
        action="ipsec.reconfigure",
        resource_type="Device",
        resource_id=device.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
    )
    await session.commit()
    return Message(message="IPsec reconfigure applied")


# device wireguard endpoints
class WireGuardServerBody(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    endpoint: str | None = None
    port: int = Field(51820, ge=1, le=65535)
    network: str = Field(default="10.0.0.0/24")
    enabled: bool = True
    description: str | None = None


@router.get(
    "/devices/{device_id}/wireguard/servers",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List WireGuard servers configured on the OPNsense host",
)
async def list_wireguard_servers(device: DeviceDep, session: SessionDep, tenant_id: TenantDep) -> list[dict]:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        response = await client.search_wireguard_servers()
    rows = response.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


@router.post(
    "/devices/{device_id}/wireguard/servers",
    response_model=WireGuardServerBody,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Create a WireGuard server on the OPNsense host",
)
async def create_wireguard_server(
    device_id: uuid.UUID,
    payload: WireGuardServerBody,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> WireGuardServerBody:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    device = await UnitOfWork(session, tenant_id).devices.get_or_404(device_id)
    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        await client.add_wireguard_server(payload.model_dump())
        await client.apply_wireguard()

    await AuditService(session).record(
        action="wireguard.server_created",
        resource_type="Device",
        resource_id=device.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
        after={"name": payload.name, "network": payload.network},
    )
    await session.commit()
    return payload


@router.delete(
    "/devices/{device_id}/wireguard/servers/{uuid}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Delete a WireGuard server from the OPNsense host",
)
async def delete_wireguard_server(
    device_id: uuid.UUID,
    uuid: str,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    device = await UnitOfWork(session, tenant_id).devices.get_or_404(device_id)
    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        await client.delete_wireguard_server(uuid)
        await client.apply_wireguard()

    await AuditService(session).record(
        action="wireguard.server_deleted",
        resource_type="Device",
        resource_id=device.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
        before={"uuid": uuid},
    )
    await session.commit()
    return Message(message="WireGuard server deleted")


@router.post(
    "/devices/{device_id}/wireguard/apply",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Reconfigure WireGuard on the OPNsense host",
)
async def apply_wireguard(
    device: DeviceDep, session: SessionDep, tenant_id: TenantDep, principal: CurrentPrincipal
) -> Message:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        await client.apply_wireguard()
    await AuditService(session).record(
        action="wireguard.reconfigure",
        resource_type="Device",
        resource_id=device.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
    )
    await session.commit()
    return Message(message="WireGuard reconfigure applied")


# device OpenVPN endpoints
class OpenVpnInstanceBody(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    mode: str = "server"
    protocol: str = "tcp"
    port: int = Field(1194, ge=1, le=65535)
    network: str = Field(default="10.0.0.0/24")
    enabled: bool = True
    description: str | None = None


@router.get(
    "/devices/{device_id}/openvpn/instances",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List OpenVPN instances configured on the OPNsense host",
)
async def list_openvpn_instances(device: DeviceDep, session: SessionDep, tenant_id: TenantDep) -> list[dict]:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        response = await client.search_openvpn_instances()
    rows = response.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


@router.post(
    "/devices/{device_id}/openvpn/instances",
    response_model=OpenVpnInstanceBody,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Create an OpenVPN instance on the OPNsense host",
)
async def create_openvpn_instance(
    device_id: uuid.UUID,
    payload: OpenVpnInstanceBody,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> OpenVpnInstanceBody:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    device = await UnitOfWork(session, tenant_id).devices.get_or_404(device_id)
    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        await client.add_openvpn_instance(payload.model_dump())
        await client.apply_openvpn()

    await AuditService(session).record(
        action="openvpn.instance_created",
        resource_type="Device",
        resource_id=device.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
        after={"name": payload.name, "network": payload.network},
    )
    await session.commit()
    return payload


@router.delete(
    "/devices/{device_id}/openvpn/instances/{uuid}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Delete an OpenVPN instance from the OPNsense host",
)
async def delete_openvpn_instance(
    device_id: uuid.UUID,
    uuid: str,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    device = await UnitOfWork(session, tenant_id).devices.get_or_404(device_id)
    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        await client.delete_openvpn_instance(uuid)
        await client.apply_openvpn()

    await AuditService(session).record(
        action="openvpn.instance_deleted",
        resource_type="Device",
        resource_id=device.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
        before={"uuid": uuid},
    )
    await session.commit()
    return Message(message="OpenVPN instance deleted")


@router.post(
    "/devices/{device_id}/openvpn/apply",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Reconfigure OpenVPN on the OPNsense host",
)
async def apply_openvpn(
    device: DeviceDep, session: SessionDep, tenant_id: TenantDep, principal: CurrentPrincipal
) -> Message:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        await client.apply_openvpn()
    await AuditService(session).record(
        action="openvpn.reconfigure",
        resource_type="Device",
        resource_id=device.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
    )
    await session.commit()
    return Message(message="OpenVPN reconfigure applied")


# device VLAN endpoints
class VlanBody(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    vlan: int = Field(ge=1, le=4094)
    interface: str
    description: str | None = None
    enabled: bool = True


@router.get(
    "/devices/{device_id}/vlans",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List VLANs configured on the OPNsense host",
)
async def list_device_vlans(device: DeviceDep, session: SessionDep, tenant_id: TenantDep) -> list[dict]:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        response = await client.search_vlans()
    rows = response.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


@router.post(
    "/devices/{device_id}/vlans",
    response_model=VlanBody,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Create a VLAN on the OPNsense host",
)
async def create_device_vlan(
    device_id: uuid.UUID,
    payload: VlanBody,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> VlanBody:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    device = await UnitOfWork(session, tenant_id).devices.get_or_404(device_id)
    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        await client.add_vlan(payload.model_dump())
        await client.apply_interfaces()

    await AuditService(session).record(
        action="vlan.created",
        resource_type="Device",
        resource_id=device.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
        after={"name": payload.name, "vlan": payload.vlan},
    )
    await session.commit()
    return payload


@router.delete(
    "/devices/{device_id}/vlans/{uuid}",
    response_model=Message,
    dependencies=[Depends(require_permissions(P.SDWAN_WRITE))],
    summary="Delete a VLAN from the OPNsense host",
)
async def delete_device_vlan(
    device_id: uuid.UUID,
    uuid: str,
    session: SessionDep,
    tenant_id: TenantDep,
    principal: CurrentPrincipal,
) -> Message:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    device = await UnitOfWork(session, tenant_id).devices.get_or_404(device_id)
    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        await client.delete_vlan(uuid)
        await client.apply_interfaces()

    await AuditService(session).record(
        action="vlan.deleted",
        resource_type="Device",
        resource_id=device.id,
        tenant_id=tenant_id,
        user_id=principal.user_id,
        before={"uuid": uuid},
    )
    await session.commit()
    return Message(message="VLAN deleted")


# device DHCP endpoints
@router.get(
    "/devices/{device_id}/dhcp/leases",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List DHCP leases reported by the OPNsense host",
)
async def list_dhcp_leases(device: DeviceDep, session: SessionDep, tenant_id: TenantDep) -> list[dict]:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        response = await client.search_dhcp_leases()
    rows = response.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


@router.get(
    "/devices/{device_id}/dhcp/relays",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List DHCP relay configurations on the OPNsense host",
)
async def list_dhcp_relays(device: DeviceDep, session: SessionDep, tenant_id: TenantDep) -> list[dict]:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        response = await client.search_dhcp_relays()
    rows = response.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


# device DNS endpoints
@router.get(
    "/devices/{device_id}/dns/records",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List DNS host records configured on the OPNsense host",
)
async def list_dns_records(device: DeviceDep, session: SessionDep, tenant_id: TenantDep) -> list[dict]:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        response = await client.search_dns_records()
    rows = response.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


@router.get(
    "/devices/{device_id}/dns/overrides",
    response_model=list[dict],
    dependencies=[Depends(require_permissions(P.SDWAN_READ))],
    summary="List DNS override entries configured on the OPNsense host",
)
async def list_dns_overrides(device: DeviceDep, session: SessionDep, tenant_id: TenantDep) -> list[dict]:
    from app.integrations.opnsense.client import client_for
    from app.services.devices import DeviceService

    base_url, key, secret = await DeviceService(session, tenant_id).credentials(device)
    async with client_for(base_url, key, secret) as client:
        response = await client.search_dns_overrides()
    rows = response.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]
