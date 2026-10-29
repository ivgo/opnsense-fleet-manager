"""Mint a one-time enrollment token for the test agent.

Usage: python scripts/mint_ztp_token.py

Reads BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD from the environment
(the same values .env uses), mints a token bound to the first site and group,
and prints the shell export line to paste into .env.

The token is one-time and must never be committed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.environ.get("OFME_API_BASE", "http://localhost:8000/api/v1")
USER = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@ofme.example.com")
PASSWORD = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
# Must match TEST_AGENT_SERIAL in .env: the agent reports this serial and the
# enrollment service rejects a payload that does not match the token.
SERIAL = os.environ.get("TEST_AGENT_SERIAL", "OFME-TEST-001")


def _req(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(  # noqa: S310 - scheme checked before opening
        f"{BASE}{path}", data=data, headers=headers, method=method
    )
    # The base URL is operator-supplied (OFME_API_BASE); reject file:/custom schemes.
    if urllib.parse.urlparse(req.full_url).scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported API scheme in {req.full_url!r}")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - scheme checked above
        return json.loads(resp.read() or b"{}")


def main() -> int:
    if not PASSWORD:
        print("BOOTSTRAP_ADMIN_PASSWORD is not set", file=sys.stderr)
        return 1

    login = _req("POST", "/auth/login", {"username": USER, "password": PASSWORD})
    token = login["access_token"]

    sites = _req("GET", "/sites", token=token)
    groups = _req("GET", "/groups", token=token)
    site_id = sites["items"][0]["id"]
    group_id = groups["items"][0]["id"]

    enrollment = _req(
        "POST",
        "/ztp/enrollments",
        {
            "site_id": site_id,
            "group_id": group_id,
            "device_serial": SERIAL,
            "ttl_minutes": 60,
            "discovery_method": "token",
        },
        token=token,
    )
    print(f"# device_serial={SERIAL}")
    print(f"ENROLLMENT_TOKEN={enrollment['token']}")
    print(f"BOOTSTRAP_URL={enrollment['bootstrap_url']}")
    print("Add ENROLLMENT_TOKEN=<token> to .env and run `make agent-up`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
