"""Interface traffic counters: normalisation, rate derivation and API queries.

The rate arithmetic is pure and unit-tested here. The API test drives two
heartbeats through the real ingest path so the counter hand-off between
snapshots, the ``traffic`` metric rows and the bucket queries are covered.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.models.enums import RoleName
from app.schemas.topology import HeartbeatPayload, TrafficSample
from app.services.monitoring import _bucket_seconds
from app.services.traffic import MAX_SAMPLE_GAP_SECONDS, normalise_counters, rate_points
from tests.conftest import AccountFactory, TenantFactory

PREVIOUS = {
    "time": 1_700_000_000.0,
    "interfaces": {"wan": {"name": "WAN", "inbytes": 1_000, "outbytes": 2_000}},
}


def _counters(inbytes: int, outbytes: int, name: str = "WAN") -> dict:
    return {
        "time": 1_700_000_010.0,
        "interfaces": {"wan": {"name": name, "inbytes": inbytes, "outbytes": outbytes}},
    }


def test_normalise_accepts_opnsense_and_heartbeat_keys() -> None:
    opnsense = {
        "time": 1_700_000_000.5,
        "interfaces": {
            "wan": {
                "name": "WAN",
                "bytes received": "1250000",
                "bytes transmitted": 250000,
            }
        },
    }
    sample = normalise_counters(opnsense)
    assert sample == {
        "time": 1_700_000_000.5,
        "interfaces": {"wan": {"name": "WAN", "inbytes": 1_250_000, "outbytes": 250_000}},
    }
    assert normalise_counters(PREVIOUS) is not None


def test_normalise_rejects_unusable_payloads() -> None:
    assert normalise_counters(None) is None
    assert normalise_counters({}) is None
    assert normalise_counters({"interfaces": []}) is None
    assert normalise_counters({"interfaces": {"wan": {"name": "WAN"}}}) is None
    assert normalise_counters({"interfaces": {"wan": {"bytes received": -1, "bytes transmitted": 5}}}) is None


def test_rate_points_need_a_previous_sample() -> None:
    now = datetime.now(UTC)
    assert rate_points(None, None, _counters(2_000, 3_000), now) == []
    assert rate_points(PREVIOUS, None, _counters(2_000, 3_000), now) == []


def test_rate_points_compute_bits_per_second() -> None:
    previous_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    now = previous_at + timedelta(seconds=10)
    points = rate_points(PREVIOUS, previous_at, _counters(1_251_000, 252_000), now)
    assert {(point["interface"], point["direction"]): point["bps"] for point in points} == {
        ("wan", "in"): 1_000_000.0,
        ("wan", "out"): 200_000.0,
    }
    assert all(point["name"] == "WAN" for point in points)


def test_rate_points_skip_counter_reset() -> None:
    previous_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    now = previous_at + timedelta(seconds=10)
    # Received wrapped around; transmitted still advanced.
    points = rate_points(PREVIOUS, previous_at, _counters(500, 3_000), now)
    assert [(point["interface"], point["direction"]) for point in points] == [("wan", "out")]


def test_rate_points_skip_long_gap() -> None:
    previous_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    now = previous_at + timedelta(seconds=MAX_SAMPLE_GAP_SECONDS + 1)
    assert rate_points(PREVIOUS, previous_at, _counters(2_000, 3_000), now) == []


def test_rate_points_skip_unknown_interface() -> None:
    previous_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    now = previous_at + timedelta(seconds=10)
    current = {
        "interfaces": {
            "wan": {"name": "WAN", "inbytes": 2_000, "outbytes": 3_000},
            "lan": {"name": "LAN", "inbytes": 9_000, "outbytes": 9_000},
        }
    }
    points = rate_points(PREVIOUS, previous_at, current, now)
    assert {point["interface"] for point in points} == {"wan"}


def test_heartbeat_payload_validates_traffic() -> None:
    payload = HeartbeatPayload.model_validate(
        {
            "traffic": {
                "time": 1_700_000_000.0,
                "interfaces": {"wan": {"name": "WAN", "inbytes": 10, "outbytes": 20}},
            }
        }
    )
    assert isinstance(payload.traffic, TrafficSample)
    assert payload.traffic.interfaces["wan"].inbytes == 10
    with pytest.raises(ValidationError):
        HeartbeatPayload.model_validate({"traffic": {"interfaces": {"wan": {"inbytes": -1, "outbytes": 0}}}})


def test_bucket_seconds_keep_the_series_bounded() -> None:
    assert _bucket_seconds(6) == 60
    assert _bucket_seconds(24) == 300
    assert _bucket_seconds(168) == 900
    assert _bucket_seconds(720) == 3600


async def _admin_headers(client: AsyncClient, tenant, account) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": account.user.username, "password": account.password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio(loop_scope="session")
async def test_traffic_endpoints_after_two_heartbeats(
    client: AsyncClient, tenant_factory: TenantFactory, account_factory: AccountFactory
) -> None:
    tenant = await tenant_factory()
    account = await account_factory(tenant, role=RoleName.ADMIN)
    headers = await _admin_headers(client, tenant, account)

    device = (await client.post("/api/v1/devices", headers=headers, json={"name": "fw-traffic"})).json()

    async def heartbeat(inbytes: int, outbytes: int) -> None:
        response = await client.post(
            f"/api/v1/devices/{device['id']}/heartbeat",
            headers=headers,
            json={
                "hostname": "fw-traffic",
                "traffic": {
                    "time": datetime.now(UTC).timestamp(),
                    "interfaces": {"wan": {"name": "WAN", "inbytes": inbytes, "outbytes": outbytes}},
                },
            },
        )
        assert response.status_code == 200, response.text

    await heartbeat(1_000, 2_000)
    # The rate needs a measurable interval between the two counter samples.
    await asyncio.sleep(1.1)
    await heartbeat(126_000, 52_000)

    series = await client.get(
        f"/api/v1/metrics/devices/{device['id']}/traffic",
        headers=headers,
        params={"interface": "wan", "hours": 24},
    )
    assert series.status_code == 200, series.text
    body = series.json()
    assert body["interface"] == "wan"
    assert body["interfaces"] == [{"key": "wan", "name": "WAN"}]
    assert len(body["points"]) == 1
    point = body["points"][0]
    assert point["in_bps"] > 0
    assert point["out_bps"] > 0

    fleet = await client.get(
        "/api/v1/metrics/traffic", headers=headers, params={"interface": "wan", "hours": 24}
    )
    assert fleet.status_code == 200, fleet.text
    fleet_body = fleet.json()
    assert len(fleet_body["points"]) == 1
    assert len(fleet_body["devices"]) == 1
    current = fleet_body["devices"][0]
    assert current["device_id"] == device["id"]
    assert current["name"] == "fw-traffic"
    assert current["interface_name"] == "WAN"
    assert current["in_bps"] > 0
    assert current["out_bps"] > 0
