"""OFME test agent — a minimal stand-in for the real os-fleet-agent plugin.

Speaks the same HTTP contract the production agent uses
(backend/app/api/v1/endpoints/agent.py) so it can be enrolled and exercised
end-to-end against a running stack:

    GET  /agent/bootstrap?token=...     -> BootstrapPackage
    POST /agent/enroll                  -> EnrollmentResponse (device cert + CA)
    POST /agent/heartbeat               -> HeartbeatResponse
    GET  /agent/config                  -> desired configuration + config_hash
    GET  /agent/commands                -> CommandBatch
    POST /agent/telemetry               -> HeartbeatResponse

Env vars:
    OFME_BASE_URL       http(s)://host:port of the OFME API, e.g. http://ofme-api:8000
    ENROLLMENT_TOKEN    one-time bootstrap token minted via POST /ztp/enrollments
    SERIAL              device serial reported during enrollment (default OFME-TEST-001)
    INTERVAL            heartbeat seconds (default 60)

After enrollment the device authenticates subsequent requests with the
X-Device-Serial header (allowed in development/testing environments).
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("OFME_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("ENROLLMENT_TOKEN", "").strip()
SERIAL = os.environ.get("SERIAL", "OFME-TEST-001")
INTERVAL = float(os.environ.get("INTERVAL", "60"))

API = f"{BASE_URL}/api/v1"


def _post(path: str, body: dict, device_id: str | None = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Device-Serial": SERIAL,
    }
    if device_id:
        headers["X-Device-Id"] = device_id
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def _get(path: str, device_id: str | None = None) -> dict:
    headers = {"Accept": "application/json", "X-Device-Serial": SERIAL}
    if device_id:
        headers["X-Device-Id"] = device_id
    req = urllib.request.Request(
        f"{API}{path}",
        headers=headers,
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def enroll() -> dict:
    """Bootstrap then enroll, returning the EnrollmentResponse."""
    bootstrap = _get(f"/agent/bootstrap?token={urllib.parse.quote(TOKEN, safe='')}")
    print(f"[agent] bootstrap ok: device_name={bootstrap.get('device_name')}")

    payload = {
        "token": TOKEN,
        "serial_number": SERIAL,
        "hostname": f"{SERIAL}.test.ofme.local",
        "model": "OPNsense Test Fixture",
        "firmware_version": "24.1-test",
        "hardware_profile": {
            "cpu_cores": 4,
            "memory_mb": 8192,
            "disk_gb": 128,
            "management_ip": "127.0.0.1",
        },
    }
    response = _post("/agent/enroll", payload)
    print(
        f"[agent] enrolled: device_id={response['device_id']} "
        f"serial={response['certificate_serial']}"
    )
    return response


def heartbeat(device_id: str) -> dict:
    return _post(
        "/agent/heartbeat",
        {
            "serial_number": SERIAL,
            "hostname": f"{SERIAL}.test.ofme.local",
            "firmware_version": "24.1-test",
            "agent_version": "1.0.0-test",
            "uptime_seconds": 42,
            "cpu_pct": 12.0,
            "memory_pct": 48.0,
            "disk_pct": 31.0,
            "sessions": 0,
            "vpn_up": 0,
            "vpn_total": 0,
            "gateways_up": 1,
            "gateways_total": 1,
            "carp_status": "master",
            "command_results": [],
        },
        device_id=device_id,
    )


def fetch_config(device_id: str) -> dict:
    cfg = _get("/agent/config", device_id=device_id)
    print(
        f"[agent] config fetched: hash={cfg.get('config_hash', '')[:16]}... "
        f"rules={len(cfg.get('firewall_rules', []))} "
        f"aliases={len(cfg.get('aliases', []))}"
    )
    return cfg


def pull_commands(device_id: str) -> dict:
    batch = _get("/agent/commands", device_id=device_id)
    if batch.get("commands"):
        print(f"[agent] received {len(batch['commands'])} pending command(s)")
    return batch


def execute_command(cmd: dict) -> dict:
    """Simulate the real os-fleet-agent handling of a firmware command.

    The production agent maps these actions onto OPNsense plugin hooks:

    * ``firmware_upgrade`` -> ``/api/core/firmware/update`` (pkg upgrade)
    * ``firmware_reboot`` -> ``/api/core/system/reboot``

    The test agent cannot touch a real host, so it reports success and bumps the
    reported firmware version so operators can see the lifecycle path working.
    """
    action = cmd.get("action")
    payload = cmd.get("payload") or {}
    if action == "firmware_upgrade":
        target = payload.get("package") or "25.1"
        return {
            "id": cmd["id"],
            "action": action,
            "status": "success",
            "message": f"firmware upgrade to {target} simulated",
            "output": {"package": target, "firmware_version": target},
            "duration_ms": 120,
        }
    if action == "firmware_reboot":
        return {
            "id": cmd["id"],
            "action": action,
            "status": "success",
            "message": "reboot simulated",
            "output": {},
            "duration_ms": 5,
        }
    return {
        "id": cmd["id"],
        "action": action,
        "status": "error",
        "message": f"unsupported action {action!r}",
        "output": {},
        "duration_ms": 0,
    }


def run_commands(device_id: str) -> list[dict]:
    """Pull pending commands, execute them locally and report results."""
    batch = pull_commands(device_id)
    results: list[dict] = []
    for cmd in batch.get("commands", []):
        result = execute_command(cmd)
        results.append(result)
        print(f"[agent] executed {cmd.get('action')}: {result.get('status')}")
    return results


def main() -> None:
    if len(TOKEN) < 16:
        print(
            "[agent] ENROLLMENT_TOKEN is missing or shorter than 16 characters.\n"
            "[agent] Mint one with `make ztp-token`, export it, then run\n"
            "[agent] `docker compose --profile testing up -d ofme-test-agent`.",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"[agent] starting against {BASE_URL} as serial={SERIAL}")
    try:
        response = enroll()
    except Exception as exc:  # noqa: BLE001
        print(f"[agent] enrollment failed: {exc}", file=sys.stderr)
        sys.exit(1)

    device_id = str(response["device_id"])
    stop = False

    def _handle_signal(_sig, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    fetch_config(device_id)
    pull_commands(device_id)

    while not stop:
        try:
            results = run_commands(device_id)
            hb = heartbeat(device_id)
            hb_payload = {
                "serial_number": SERIAL,
                "hostname": f"{SERIAL}.test.ofme.local",
                "firmware_version": "24.1-test",
                "agent_version": "1.0.0-test",
                "uptime_seconds": 42,
                "cpu_pct": 12.0,
                "memory_pct": 48.0,
                "disk_pct": 31.0,
                "sessions": 0,
                "vpn_up": 0,
                "vpn_total": 0,
                "gateways_up": 1,
                "gateways_total": 1,
                "carp_status": "master",
                "command_results": results,
            }
            _post("/agent/heartbeat", hb_payload, device_id=device_id)
            print(
                f"[agent] heartbeat ok: accepted={hb.get('accepted')} "
                f"commands={len(hb.get('commands', []))} "
                f"results={len(results)}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[agent] heartbeat failed: {exc}", file=sys.stderr)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()