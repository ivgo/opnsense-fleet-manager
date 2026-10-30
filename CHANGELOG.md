## [Unreleased]

### Added

#### Dashboard: WAN traffic columns in Fleet health table

- Added `in_bps` and `out_bps` fields to `DeviceHealth` schema (backend and frontend)
- Dashboard now shows RX (receive) and TX (transmit) throughput per device in the Fleet health section
- Traffic rates are fetched from the latest WAN interface metrics (last 30 minutes)
- Columns are hidden on smaller screens (`hideBelow: "md"`)
- Values formatted using existing `formatBits()` utility (e.g., "1.5 Gbps", "250 Mbps")

**Files modified:**

- `backend/app/schemas/operations.py`: Extended `DeviceHealth` with `in_bps`, `out_bps`
- `backend/app/services/monitoring.py`: `DashboardService.health()` fetches latest WAN traffic and merges into response
- `frontend/src/api/types.ts`: Extended `DeviceHealth` interface
- `frontend/src/pages/DashboardPage.tsx`: Added `traffic_in` (RX) and `traffic_out` (TX) columns

**API contract:**

- `GET /api/v1/metrics/health` now returns `in_bps` and `out_bps` per device (float, bits per second)
- Traffic rates represent the latest WAN interface throughput
- Devices without recent traffic data return `null` for both fields

#### pgBackRest PostgreSQL backup/restore

- Added pgBackRest API endpoints: `POST /api/v1/pgbackrest/backup`, `GET /api/v1/pgbackrest/info`, `POST /api/v1/pgbackrest/verify`, `POST /api/v1/pgbackrest/expire`
- Added pgBackRest Celery worker tasks executing CLI commands via Docker exec in PostgreSQL container
- Added integration tests covering API endpoints, permission checks, job queuing, and worker execution

#### IPsec VPN frontend management

- Added complete CRUD UI for IPsec Phase 1 (IKE) and Phase 2 (IPsec) configurations
- Type definitions for IPsec Phase 1 and Phase 2 payloads in `frontend/src/api/types.ts`
- API endpoints with create/update/delete/list operations in `frontend/src/api/endpoints.ts`
- Query keys for IPsec Phase 1 and Phase 2 data in `frontend/src/api/queryKeys.ts`
- Sidebar navigation entry "IPsec VPN" under Network section in `frontend/src/layout/Sidebar.tsx`
- Route `/ipsec` registered in `frontend/src/router.tsx`
- FormDialog for create/edit with validation and dropdown options for IKE types, auth methods, encryption, hash, DH groups, NAT traversal, modes, protocols
- ConfirmDialog for delete operations
- Apply configuration dialog with dry-run mode

#### Frontend tests

- Added tests for SettingsPage, SitesPage, UsersPage

### Fixed

#### Frontend nginx: stale upstream IP after container recreation (`frontend/nginx.conf`)

Every `/api/*` and `/ws` request proxied through the web console returned **502
Bad Gateway** whenever the API container was recreated (e.g. by `docker compose
up --build`, a migration, or a restart).

**Root cause.** nginx resolved the service name `ofme-api` once at config load and
cached the resulting IP forever. When the API container was recreated it got a
new IP, but nginx kept pointing at the old, dead address. Direct calls to
`:8000` worked because they bypass nginx entirely; the SPA proxies through nginx,
so the login page (and every other page) 502'd.

**Fix.** Added Docker's embedded DNS (`127.0.0.11`) with a short TTL and switched
the two proxy locations to a variable upstream so nginx re-resolves `ofme-api` on
every request:

```nginx
resolver 127.0.0.11 valid=30s ipv6=off;

location /api/ {
    set $api_upstream http://ofme-api:8000;
    proxy_pass $api_upstream;
    ...
}

location /ws {
    set $ws_upstream http://ofme-api:8000;
    proxy_pass $ws_upstream;
    ...
}
```

This also makes the stack robust to future container recreations and scaling
without manual intervention.

#### Dashboard: crash on first load when no compliance score exists (`frontend/src/pages/DashboardPage.tsx`)

The fleet overview threw
`Cannot read properties of null (reading 'toFixed')` and React's error boundary
rendered "Unexpected Application Error" on every fresh install.

**Root cause.** The "Compliance score" StatCard only guarded `summary`, not the
score field:

```tsx
value={summary ? `${summary.compliance_score.toFixed(1)}%` : "—"}
```

The backend schema declares the field as nullable
(`backend/app/schemas/operations.py:192` → `compliance_score: float | None = None`),
and a fresh install with no CIS run yet returns `compliance_score: null`. Because
the StatCard renders before the query finishes, `null.toFixed()` crashed the
whole dashboard.

**Fix.** Use the existing null-safe `formatPercent` helper (returns `"—"` for
`null`) and guard the tone comparison too:

```tsx
value={summary ? formatPercent(summary.compliance_score, 1) : "—"}
tone={
  !summary || summary.compliance_score === null
    ? "neutral"
    : summary.compliance_score >= 90 ? "success"
    : summary.compliance_score >= 70 ? "warning" : "error"
}
```

The dashboard now renders with "—" for the compliance score until a CIS scan
runs.