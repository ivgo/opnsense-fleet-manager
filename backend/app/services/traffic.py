"""Interface traffic counters: normalisation and rate derivation.

OPNsense exposes monotonic byte counters per interface (``bytes received`` /
``bytes transmitted``). Rates are derived centrally from two consecutive
samples, so every ingestion path — REST polling and the PHP agent — only has to
report counters. This keeps the arithmetic, the counter-reset handling and the
gap policy in one place.

The module is pure: it never touches the database or the appliance.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

#: Two samples further apart than this cannot produce a meaningful rate (the
#: device was offline or the collector was paused). The samples are dropped
#: rather than smeared over hours.
MAX_SAMPLE_GAP_SECONDS = 7200

#: Sub-second intervals amplify rounding noise into spikes.
MIN_SAMPLE_GAP_SECONDS = 1.0

_MAX_INTERFACES = 256


def _counter(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = int(value)
    else:
        text = str(value).strip()
        if not text.isdigit():
            return None
        number = int(text)
    return number if number >= 0 else None


def normalise_counters(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalise a counters payload to ``{time, interfaces: {key: counters}}``.

    Accepts both the OPNsense ``/api/diagnostics/traffic/interface`` shape
    (``bytes received`` / ``bytes transmitted``) and the canonical heartbeat
    shape (``inbytes`` / ``outbytes``), so the REST poller and the agent share
    one representation.
    """
    if not isinstance(payload, dict):
        return None
    rows = payload.get("interfaces")
    if not isinstance(rows, dict):
        return None

    interfaces: dict[str, dict[str, Any]] = {}
    for key, row in rows.items():
        if len(interfaces) >= _MAX_INTERFACES:
            break
        if not isinstance(row, dict):
            continue
        inbytes = _counter(row.get("inbytes", row.get("bytes received")))
        outbytes = _counter(row.get("outbytes", row.get("bytes transmitted")))
        if inbytes is None or outbytes is None:
            continue
        name = str(row.get("name") or key).strip() or str(key)
        interfaces[str(key)] = {"name": name, "inbytes": inbytes, "outbytes": outbytes}

    if not interfaces:
        return None

    sample_time = payload.get("time")
    time_value: float | None = None
    if isinstance(sample_time, int | float) and not isinstance(sample_time, bool):
        time_value = float(sample_time)
    return {"time": time_value, "interfaces": interfaces}


def rate_points(
    previous: dict[str, Any] | None,
    previous_at: datetime | None,
    current: dict[str, Any] | None,
    now: datetime,
) -> list[dict[str, Any]]:
    """Derive bit-per-second rates from two counter samples.

    Returns one entry per interface and direction. The first sample of a device,
    a counter reset (negative delta) and a sampling gap above
    :data:`MAX_SAMPLE_GAP_SECONDS` produce no points instead of a fabricated
    value.
    """
    current_sample = normalise_counters(current)
    previous_sample = normalise_counters(previous)
    if current_sample is None or previous_sample is None or previous_at is None:
        return []

    elapsed = (now - previous_at).total_seconds()
    if elapsed < MIN_SAMPLE_GAP_SECONDS or elapsed > MAX_SAMPLE_GAP_SECONDS:
        return []

    previous_rows = previous_sample["interfaces"]
    points: list[dict[str, Any]] = []
    for key, row in current_sample["interfaces"].items():
        before = previous_rows.get(key)
        if before is None:
            continue
        for direction, field in (("in", "inbytes"), ("out", "outbytes")):
            delta = int(row[field]) - int(before[field])
            if delta < 0:
                # The interface was reset or the device rebooted; wait for the
                # next pair of samples.
                continue
            points.append(
                {
                    "interface": key,
                    "name": row["name"],
                    "direction": direction,
                    "bps": round(delta * 8 / elapsed, 2),
                }
            )
    return points
