"""Unit tests for the command whitelist and result reconciliation.

These functions are pure: they mutate a ``Device`` object in memory, which makes
them cheap to test and keeps the reconciliation logic honest without a database.
"""

from __future__ import annotations

import typing
import uuid
from datetime import UTC, datetime, timedelta

from app.models.topology import Device
from app.schemas.topology import CommandResultPayload, DeviceCommandAction
from app.services.devices import (
    COMMAND_ACTIONS,
    MAX_COMMAND_HISTORY,
    _merge_command_results,
)


def _device(pending: list[dict], history: list[dict] | None = None) -> Device:
    return Device(
        tenant_id=uuid.uuid4(),
        name="fw-01",
        metadata_={
            "pending_commands": pending,
            "command_history": history or [],
        },
    )


def test_command_actions_match_schema_literal() -> None:
    assert frozenset(typing.get_args(DeviceCommandAction)) == COMMAND_ACTIONS


def test_merge_removes_matching_pending_command() -> None:
    device = _device(
        pending=[
            {"id": "a", "action": "ping", "payload": {}},
            {"id": "b", "action": "noop", "payload": {}},
        ]
    )
    now = datetime.now(UTC)
    merged = _merge_command_results(
        device,
        [CommandResultPayload(id="a", action="ping", status="ok", message="pong")],
        now,
    )

    assert merged == 1
    metadata = device.metadata_
    assert [item["id"] for item in metadata["pending_commands"]] == ["b"]
    assert metadata["command_history"][0]["id"] == "a"
    assert metadata["command_history"][0]["status"] == "ok"
    assert metadata["last_command_result_at"] == now.isoformat()


def test_merge_replaces_existing_history_entry() -> None:
    device = _device(
        pending=[],
        history=[
            {
                "id": "a",
                "action": "ping",
                "status": "error",
                "message": "timeout",
                "received_at": "2024-01-01T00:00:00+00:00",
            }
        ],
    )
    _merge_command_results(
        device,
        [CommandResultPayload(id="a", action="ping", status="ok", message="pong")],
        datetime.now(UTC),
    )

    history = device.metadata_["command_history"]
    assert len(history) == 1
    assert history[0]["status"] == "ok"
    assert history[0]["message"] == "pong"


def test_merge_ignores_empty_results() -> None:
    device = _device(pending=[{"id": "a", "action": "ping", "payload": {}}])
    before = dict(device.metadata_)
    assert _merge_command_results(device, [], datetime.now(UTC)) == 0
    assert device.metadata_ == before


def test_merge_trims_history_to_maximum() -> None:
    history = [
        {
            "id": f"old-{index}",
            "action": "noop",
            "status": "ok",
            "received_at": (datetime.now(UTC) - timedelta(minutes=index)).isoformat(),
        }
        for index in range(MAX_COMMAND_HISTORY + 5)
    ]
    device = _device(pending=[], history=history)
    _merge_command_results(
        device,
        [CommandResultPayload(id="new", action="ping", status="ok")],
        datetime.now(UTC),
    )

    trimmed = device.metadata_["command_history"]
    assert len(trimmed) == MAX_COMMAND_HISTORY
    assert trimmed[-1]["id"] == "new"
    # The list is ordered oldest to newest; the six oldest entries fall off.
    assert trimmed[0]["id"] == "old-6"


def test_merge_ignores_non_dict_entries() -> None:
    device = _device(pending=[{"id": "a", "action": "ping", "payload": {}}, "garbage"])
    _merge_command_results(
        device,
        [CommandResultPayload(id="a", action="ping", status="ok")],
        datetime.now(UTC),
    )
    assert device.metadata_["pending_commands"] == []
