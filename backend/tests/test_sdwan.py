"""Pure unit tests for SD-WAN planning and SLA evaluation (no database)."""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import BadRequestError
from app.models.enums import HealthStatus, SteeringStrategy, TopologyType, TunnelStatus
from app.models.sdwan import SdwanLink, SdwanTopology
from app.models.topology import Device, Site
from app.services.sdwan import SdwanHealthService, SteeringService, TopologyEngine, _lan_cidr


def _device(
    name: str,
    *,
    ip_address: str | None = None,
    metadata: dict | None = None,
    site: Site | None = None,
) -> Device:
    return Device(
        id=uuid.uuid4(),
        name=name,
        ip_address=ip_address,
        metadata_=metadata or {},
        site=site,
    )


def _topology(
    kind: TopologyType, hubs: list[Device], spokes: list[Device], **config: object
) -> SdwanTopology:
    return SdwanTopology(
        topology_type=kind,
        hub_device_ids=[str(device.id) for device in hubs],
        spoke_device_ids=[str(device.id) for device in spokes],
        configuration=dict(config),
    )


def _by_id(devices: list[Device]) -> dict[uuid.UUID, Device]:
    return {device.id: device for device in devices}


# --------------------------------------------------------------------------- planning
def test_hub_spoke_requires_a_hub() -> None:
    spoke = _device("spoke")
    topology = _topology(TopologyType.HUB_SPOKE, [], [spoke])
    with pytest.raises(BadRequestError):
        TopologyEngine.plan(topology, _by_id([spoke]))


def test_hub_spoke_plans_one_tunnel_per_spoke() -> None:
    hub = _device("hub", metadata={"lan_cidr": "10.10.0.0/24"})
    first = _device("spoke-a", metadata={"lan_cidr": "10.20.0.0/24"})
    second = _device("spoke-b", metadata={"lan_cidr": "10.30.0.0/24"})
    topology = _topology(TopologyType.HUB_SPOKE, [hub], [first, second], wan_interface="ix0")

    plans = TopologyEngine.plan(topology, _by_id([hub, first, second]))

    assert len(plans) == 2
    assert {plan.local_device_id for plan in plans} == {first.id, second.id}
    assert all(plan.remote_device_id == hub.id for plan in plans)
    assert all(plan.allowed_ips == ["10.10.0.0/24"] for plan in plans)
    assert all(plan.wan_interface == "ix0" for plan in plans)
    assert all(plan.priority == 100 and plan.cost == 10 for plan in plans)
    assert len({plan.name for plan in plans}) == 2


def test_hub_spoke_uses_only_the_first_hub() -> None:
    primary = _device("hub-primary")
    secondary = _device("hub-secondary")
    spoke = _device("spoke")
    topology = _topology(TopologyType.HUB_SPOKE, [primary, secondary], [spoke])

    plans = TopologyEngine.plan(topology, _by_id([primary, secondary, spoke]))

    assert len(plans) == 1
    assert plans[0].remote_device_id == primary.id


def test_full_mesh_creates_one_tunnel_per_pair_and_forces_wan() -> None:
    devices = [_device("a"), _device("b"), _device("c")]
    topology = _topology(TopologyType.FULL_MESH, devices, [], wan_interface="ix0")

    plans = TopologyEngine.plan(topology, _by_id(devices))

    assert len(plans) == 3
    assert {frozenset((plan.local_device_id, plan.remote_device_id)) for plan in plans} == {
        frozenset((devices[0].id, devices[1].id)),
        frozenset((devices[0].id, devices[2].id)),
        frozenset((devices[1].id, devices[2].id)),
    }
    assert all(plan.wan_interface == "wan" for plan in plans)


def test_full_mesh_needs_two_participants() -> None:
    only = _device("only")
    topology = _topology(TopologyType.FULL_MESH, [only], [])
    with pytest.raises(BadRequestError):
        TopologyEngine.plan(topology, _by_id([only]))


def test_regional_hub_meshes_hubs_and_picks_the_nearest_hub() -> None:
    frankfurt = Site(name="Frankfurt", code="fra", latitude=50.11, longitude=8.68)
    vienna = Site(name="Vienna", code="vie", latitude=48.21, longitude=16.37)
    hub_fra = _device("fra-hub", site=frankfurt)
    hub_vie = _device("vie-hub", site=vienna)
    munich = _device("munich", site=Site(name="Munich", code="muc", latitude=48.14, longitude=11.58))
    near_vienna = _device("vienna", site=Site(name="Vienna 2", code="vie2", latitude=48.20, longitude=16.40))
    topology = _topology(TopologyType.REGIONAL_HUB, [hub_fra, hub_vie], [munich, near_vienna])

    plans = TopologyEngine.plan(topology, _by_id([hub_fra, hub_vie, munich, near_vienna]))
    by_local = {plan.local_device_id: plan for plan in plans}

    hub_link = by_local[hub_fra.id]
    assert hub_link.remote_device_id == hub_vie.id
    assert hub_link.priority == 50 and hub_link.cost == 5
    assert by_local[munich.id].remote_device_id == hub_fra.id
    assert by_local[near_vienna.id].remote_device_id == hub_vie.id
    assert len(plans) == 3


def test_regional_hub_without_coordinates_falls_back_to_first_hub() -> None:
    hub_a = _device("hub-a")
    hub_b = _device("hub-b")
    spoke = _device("spoke")
    topology = _topology(TopologyType.REGIONAL_HUB, [hub_a, hub_b], [spoke])

    plans = TopologyEngine.plan(topology, _by_id([hub_a, hub_b, spoke]))
    spoke_plan = next(plan for plan in plans if plan.local_device_id == spoke.id)

    assert spoke_plan.remote_device_id == hub_a.id


def test_deleted_devices_are_ignored() -> None:
    hub = _device("hub")
    present = _device("present")
    missing = _device("missing")
    topology = _topology(TopologyType.HUB_SPOKE, [hub], [present, missing])

    plans = TopologyEngine.plan(topology, _by_id([hub, present]))

    assert len(plans) == 1
    assert plans[0].local_device_id == present.id


# --------------------------------------------------------------------------- addressing
def test_lan_cidr_prefers_explicit_metadata() -> None:
    device = _device("fw", ip_address="192.0.2.10", metadata={"lan_cidr": "10.50.0.0/16"})
    assert _lan_cidr(device) == "10.50.0.0/16"


def test_lan_cidr_accepts_lan_network_alias() -> None:
    device = _device("fw", metadata={"lan_network": "10.60.0.0/16"})
    assert _lan_cidr(device) == "10.60.0.0/16"


def test_lan_cidr_widens_the_management_ip_to_a_slash_24() -> None:
    device = _device("fw", ip_address="172.16.4.9")
    assert _lan_cidr(device) == "172.16.4.0/24"


def test_lan_cidr_falls_back_when_nothing_is_known() -> None:
    assert _lan_cidr(_device("fw")) == "10.255.255.0/24"
    assert _lan_cidr(_device("fw", ip_address="not-an-ip")) == "10.255.255.0/24"


# --------------------------------------------------------------------------- steering
def _link(**overrides: object) -> SdwanLink:
    values: dict[str, object] = {
        "status": TunnelStatus.ACTIVE,
        "latency_ms": 20.0,
        "loss_pct": 0.0,
        "sla_latency_ms": 150.0,
        "sla_loss_pct": 1.0,
        "cost": 10,
        "priority": 100,
        "bandwidth_mbps": 100.0,
    }
    values.update(overrides)
    return SdwanLink(**values)


def test_link_within_sla_is_eligible() -> None:
    assert SteeringService._meets_sla(_link()) is True


def test_inactive_link_is_not_eligible() -> None:
    assert SteeringService._meets_sla(_link(status=TunnelStatus.DOWN)) is False
    assert SteeringService._meets_sla(_link(status=TunnelStatus.PENDING)) is False


def test_latency_and_loss_violations_are_rejected() -> None:
    assert SteeringService._meets_sla(_link(latency_ms=151.0)) is False
    assert SteeringService._meets_sla(_link(loss_pct=1.01)) is False


def test_missing_measurements_count_as_passing_the_sla() -> None:
    assert SteeringService._meets_sla(_link(latency_ms=None, loss_pct=None)) is True


def test_exact_sla_boundary_is_accepted() -> None:
    assert SteeringService._meets_sla(_link(latency_ms=150.0, loss_pct=1.0)) is True


def test_health_mapping_uses_status_and_sla() -> None:
    assert SdwanHealthService._health(_link()) == HealthStatus.HEALTHY
    assert SdwanHealthService._health(_link(latency_ms=200.0)) == HealthStatus.DEGRADED
    assert SdwanHealthService._health(_link(status=TunnelStatus.DOWN)) == HealthStatus.UNHEALTHY


def test_steering_strategies_are_declared() -> None:
    assert {strategy.value for strategy in SteeringStrategy} == {
        "lowest_latency",
        "lowest_loss",
        "lowest_cost",
        "application",
        "weighted",
        "failover",
    }
