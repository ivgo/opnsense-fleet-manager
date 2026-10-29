"""Monitoring endpoint tests.

Regression guard for the dashboard aggregate: the summary counted rows through
``BaseRepository.count()`` for models that have no ``deleted_at`` column
(VPN tunnels, alerts, jobs), which raised ``AttributeError`` at runtime and made
the whole dashboard return HTTP 500 on a fresh installation.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

PATHS = (
    "/api/v1/metrics/summary",
    "/api/v1/metrics/dashboard",
    "/api/v1/metrics/health",
    "/api/v1/metrics/trends",
)


@pytest.mark.asyncio(loop_scope="session")
async def test_dashboard_endpoints_on_empty_tenant(client: AsyncClient, auth_headers) -> None:
    headers = await auth_headers()
    for path in PATHS:
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, f"{path}: {response.text}"


@pytest.mark.asyncio(loop_scope="session")
async def test_dashboard_summary_shape(client: AsyncClient, auth_headers) -> None:
    response = await client.get("/api/v1/metrics/summary", headers=await auth_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    for key in (
        "devices_total",
        "devices_online",
        "devices_offline",
        "sites_total",
        "policies_total",
        "tunnels_total",
        "open_alerts",
        "jobs_running",
    ):
        assert key in body
    assert body["devices_total"] == 0
