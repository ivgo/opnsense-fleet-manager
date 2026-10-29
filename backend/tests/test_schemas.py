"""Pydantic contract tests for the device-facing payloads."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.topology import (
    CommandResultPayload,
    DeviceCommandRequest,
    DeviceCommandStatus,
    DeviceCreate,
    HeartbeatPayload,
)
from app.schemas.ztp import EnrollmentRequest, EnrollmentTokenCreate


def test_device_create_accepts_dns_safe_name() -> None:
    payload = DeviceCreate(name="fw-branch-01.example")
    assert payload.api_port == 443
    assert payload.tags == []


@pytest.mark.parametrize("name", ["a", "firewall with spaces", "fw/01", "fw#1"])
def test_device_create_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError):
        DeviceCreate(name=name)


def test_device_create_rejects_out_of_range_port() -> None:
    with pytest.raises(ValidationError):
        DeviceCreate(name="fw-01", api_port=70_000)


def test_command_request_rejects_unknown_action() -> None:
    with pytest.raises(ValidationError):
        DeviceCommandRequest(action="reboot")  # type: ignore[arg-type]


def test_command_request_accepts_whitelisted_action() -> None:
    request = DeviceCommandRequest(action="sync_config", payload={"force": True})
    assert request.action == "sync_config"
    assert request.payload == {"force": True}


def test_command_request_rejects_oversized_payload() -> None:
    with pytest.raises(ValidationError):
        DeviceCommandRequest(action="ping", payload={"blob": "x" * 9000})


def test_heartbeat_accepts_command_results() -> None:
    payload = HeartbeatPayload(
        firmware_version="24.7.11",
        cpu_pct=12.5,
        command_results=[
            CommandResultPayload(
                id="cmd-1",
                action="ping",
                status="ok",
                message="pong",
                output={"agent_version": "1.0.0"},
                duration_ms=12,
            )
        ],
    )
    assert payload.cpu_pct == 12.5
    assert payload.command_results[0].status == "ok"


def test_heartbeat_rejects_more_than_fifty_results() -> None:
    results = [CommandResultPayload(id=f"cmd-{index}", action="ping", status="ok") for index in range(51)]
    with pytest.raises(ValidationError):
        HeartbeatPayload(command_results=results)


def test_heartbeat_rejects_out_of_range_metrics() -> None:
    with pytest.raises(ValidationError):
        HeartbeatPayload(cpu_pct=101)
    with pytest.raises(ValidationError):
        HeartbeatPayload(memory_pct=-1)


def test_command_status_parses_iso_timestamps() -> None:
    status = DeviceCommandStatus(
        device_id=uuid.uuid4(),
        pending=[
            {
                "id": "cmd-1",
                "action": "ping",
                "payload": {},
                "requested_at": datetime.now(UTC).isoformat(),
                "requested_by": None,
            }
        ],
        history=[],
        pending_count=1,
        last_result_at=None,
    )
    assert status.pending_count == 1


def test_enrollment_token_ttl_defaults_to_the_setting() -> None:
    from app.core.config import settings

    payload = EnrollmentTokenCreate()
    assert payload.ttl_minutes == settings.ENROLLMENT_TOKEN_TTL_MINUTES
    assert payload.discovery_method.value == "token"


@pytest.mark.parametrize("ttl", [4, 10_081])
def test_enrollment_token_ttl_is_bounded(ttl: int) -> None:
    with pytest.raises(ValidationError):
        EnrollmentTokenCreate(ttl_minutes=ttl)


@pytest.mark.parametrize("mac", ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF"])
def test_enrollment_token_accepts_common_mac_formats(mac: str) -> None:
    assert EnrollmentTokenCreate(device_mac=mac).device_mac == mac


def test_enrollment_token_rejects_a_malformed_mac() -> None:
    with pytest.raises(ValidationError):
        EnrollmentTokenCreate(device_mac="not-a-mac")


def test_enrollment_request_requires_a_token_and_serial() -> None:
    with pytest.raises(ValidationError):
        EnrollmentRequest(token="short", serial_number="ab")
    payload = EnrollmentRequest(token="x" * 32, serial_number="OPNsense-1234")
    assert payload.csr_pem is None
    assert payload.hardware_profile == {}
