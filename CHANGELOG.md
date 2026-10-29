# Changelog

All notable changes to OPNsense Fleet Manager Enterprise (OFME).

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
field:

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

#### RBAC: upgraded deployments kept stale permissions (`backend/app/services/identity.py`, `backend/app/seeds/bootstrap.py`, `backend/app/main.py`)

`_seed_roles` only ran when a tenant or the platform was first created, and it
skipped any role that already existed. Adding `dhcp:read|write` and
`dns:read|write` to `ROLE_MATRIX` therefore reached fresh installs only: an
existing deployment kept its old permission lists, so a TenantAdmin could not
see the new pages even though the API and the matrix declared the permission.

**Fix.** System roles are now re-aligned on every startup:

- `TenantService._seed_roles` updates `permissions` and `description` of an
  existing `is_system` row instead of skipping it.
- `RoleService.sync_system_roles()` returns the number of rows it repaired and
  never touches custom (non-system) roles.
- `sync_rbac_catalogue()` runs from `_bootstrap_platform()` with or without
  bootstrap credentials and logs `startup.rbac_synced`.

Verified: the live rows are now SuperAdmin 79, TenantAdmin 74, Admin 72,
Operator 46, Auditor 31, ReadOnly 28, and `sync_system_roles()` is idempotent
(0 updates on a second run). Regression tests in `tests/test_rbac_sync.py`.

#### Test agent broke `docker compose up --wait` (`docker-compose.yml`, `tests/agent/agent.py`, `backend/scripts/mint_ztp_token.py`)

`ofme-test-agent` lived in the default profile, so a plain
`docker compose up -d --wait` started it, it exited 1 for lack of an
`ENROLLMENT_TOKEN`, and the wait failed — a red stack for a helper nobody asked
for. With a token present but a stale serial it also surfaced as an opaque
`HTTP Error 422` / `409`.

- The service is now behind `profiles: ["testing"]`; `make agent-build/up/logs`
  pass `--profile testing`. Default `up -d --wait` ignores it.
- `agent.py` validates the token up front and prints an actionable message
  (mint with `make ztp-token`, then start the profile) instead of a bare HTTP
  error.
- `mint_ztp_token.py` honours `TEST_AGENT_SERIAL`, the same variable the compose
  service reads, so the token and the reported serial cannot drift apart.

Verified end-to-end: minted a token for `OFME-TEST-004`, enrolled, pulled the
desired config (hash `48cdf21b…`), sent heartbeats (`accepted=True`), device went
`online`/`connected`, audit action `ztp.enrolled` recorded, then the container
and the test device were removed and the fleet returned to 5 devices.

#### DNS console: a pending device query looked like an empty fleet (`frontend/src/pages/DnsPage.tsx`)

The header chip printed `0 devices` until the device query resolved, and the
**New record** button was disabled for that window, which reads as "no devices
exist" rather than "still loading".

**Fix.** Render `—` while the query is pending (`devicesQuery.isPending`) and the
count once it settles; the button stays disabled until the data is known.

#### Policy rollback advertised more than it does (`backend/app/api/v1/endpoints/policies.py`, `backend/app/services/gitops.py`)

`POST /api/v1/deployments/{deployment_id}/rollback` was summarised as
"Roll back a deployment" with no caveat, while it only transitions the
deployment to `ROLLED_BACK` and writes an audit entry. Deployments store no rule
snapshot, so no rule set is re-applied and the appliance keeps the newer
configuration.

**Fix.** The endpoint summary is now "Mark a deployment as rolled back and audit
it" and its description, plus the `DeploymentService.rollback` docstring, state
that the previous rule set is not re-applied and point at the two real recovery
paths (signed backup restore, earlier policy version). Behaviour is unchanged;
the contract is now honest. Recorded as gap **G-29** in
`docs/REQUIREMENTS_TRACEABILITY.md`.

### Added

#### IPsec tunnel management (`backend/app/integrations/opnsense/client.py`, `backend/app/services/sdwan.py`, `backend/app/api/v1/endpoints/sdwan.py`)

The fleet previously only read IPsec session state; there was no way to *create*
or *reconfigure* IPsec tunnels from OFME. The OPNsense client already had the
`/api/ipsec/*` endpoints wired but nothing called them.

- Full typed CRUD surface on the OPNsense client: `search_ipsec_tunnels`,
  `add_ipsec_tunnel`, `set_ipsec_tunnel`, `delete_ipsec_tunnel`, `apply_ipsec`,
  plus the phase1/phase2 equivalents (`backend/app/integrations/opnsense/client.py:189`).
- `TunnelProvisioner._apply_to_device` now dispatches on `VpnProtocol`:
  WireGuard, IPsec and OpenVPN each get their own builder. IPsec is provisioned
  as a phase1 + phase2 pair and applied through the standard OPNsense hooks
  (`backend/app/services/sdwan.py:458`).
- New REST endpoints under the SD-WAN router:
  - `GET /api/v1/sdwan/devices/{device_id}/ipsec/tunnels`
  - `POST /api/v1/sdwan/devices/{device_id}/ipsec/tunnels`
  - `POST /api/v1/sdwan/devices/{device_id}/ipsec/apply`
- The create endpoint takes phase1 and phase2 bodies, pushes both to the host,
  applies phase1 and reconfigures the IPsec service, and records an audit event.

This makes IPsec a first-class citizen alongside WireGuard in SD-WAN topologies
and in the device-level VPN menu.

#### OPNsense firmware lifecycle management (`backend/app/services/upgrade.py`, `backend/app/workers/firmware.py`, `backend/app/api/v1/endpoints/devices.py`)

The fleet can now read firmware status, trigger in-place upgrades and reboot hosts
through the OPNsense REST API. This closes the gap where the client already spoke
`/api/core/firmware/update` but nothing in OFME ever called it.

- `FirmwareUpgradeService.status()` — probes `/api/core/firmware/status` and
  `/api/core/firmware/info`, normalises the product/version fields and reports
  `needs_upgrade` / `upgrade_available` so operators get a single decision-ready
  payload (`backend/app/services/upgrade.py:47`).
- `FirmwareUpgradeService.upgrade(package=...)` and `.reboot()` — POST to
  `/api/core/firmware/update` and `/api/core/system/reboot`, audit every call and
  clear the cached `firmware_version` after an upgrade (it is only known again
  after the host reboots).
- New REST endpoints under the Devices router:
  - `GET /api/v1/devices/{device_id}/firmware/status`
  - `POST /api/v1/devices/{device_id}/firmware/upgrade`
  - `POST /api/v1/devices/{device_id}/firmware/reboot`
- New permissions `firmware:read`, `firmware:upgrade`, `firmware:reboot`. The
  upgrade/reboot permissions are granted to **OPERATOR** and above; read is
  granted to every role (`backend/app/rbac/permissions.py`).
- Device command whitelist now includes `firmware_upgrade` and
  `firmware_reboot`, so the same queue-and-pull path used for
  `reload_firewall` / `renew_certificate` can carry firmware actions to the
  agent (`backend/app/services/devices.py:48`,
  `backend/app/schemas/topology.py:193`).
- `TaskKind.FIRMWARE_UPGRADE` is now wired to a real Celery task
  (`ofme.firmware.upgrade`) instead of falling through to the generic custom
  executor. A sibling `ofme.firmware.reboot` task is also registered. Both run on
  the new `ofme-firmware` queue (`backend/app/workers/dispatch.py:26`,
  `backend/app/workers/celery_app.py`). Tenants can therefore schedule weekly
  upgrades through `/api/v1/tasks` exactly like backups or compliance scans.
- The test agent understands both commands and reports a synthetic result, so
  the full dispatch → pull → heartbeat → reconcile loop can be exercised
  (`tests/agent/agent.py:133`).

#### Test agent container (`tests/agent/`, `docker-compose.yml`, `Makefile`)

A minimal stand-in for the real `os-fleet-agent` OPNsense plugin so the
enrollment, heartbeat, config-fetch and command-pull paths can be exercised
end-to-end against a running stack without a FreeBSD box.

- `tests/agent/Dockerfile` + `tests/agent/agent.py` — a Python container that
  speaks the same HTTP contract as the production agent
  (`backend/app/api/v1/endpoints/agent.py`): `GET /agent/bootstrap`,
  `POST /agent/enroll`, `POST /agent/heartbeat`, `GET /agent/config`,
  `GET /agent/commands`, `POST /agent/telemetry`. It authenticates with the
  `X-Device-Serial` header (allowed in development/testing).
- `docker-compose.yml` — new `ofme-test-agent` service, build context
  `./tests/agent`, depends on a healthy API, gated behind the `testing` profile
  so the default stack never waits on it.
- `Makefile` — `agent-build`, `agent-up`, `agent-logs`, `agent-down`, and
  `ztp-token` (mints a one-time enrollment token via
  `backend/scripts/mint_ztp_token.py`).
- `.env.example` — `ENROLLMENT_TOKEN` / `TEST_AGENT_SERIAL` placeholders.

Verified: the profile-gated `make agent-up` enrolled a device (serial
`OFME-TEST-004`, status `online`), fetched its config and sent heartbeats; the
earlier run used `OFME-TEST-003`.

### Changed

- `frontend/nginx.conf` — DNS resolver + variable upstreams (see above).
- `frontend/src/pages/DashboardPage.tsx` — null-safe compliance score formatting.
- `docker-compose.yml` — added the `ofme-test-agent` service.
- `Makefile` — test agent targets.
- `.env.example` — test agent env placeholders.
- `docs/REQUIREMENTS_TRACEABILITY.md` — §1 feature numbers now match
  `PACKAGE_SUMMARY.md` §3, new §1.1 lists the exact missing piece for each of
  the 10 partial features, the NAT/VLAN/WireGuard/rollback notes were corrected
  after a code review, and gap G-29 was added.
- `PACKAGE_SUMMARY.md` — §3 now carries an implementation-status block
  (20 complete / 10 partial / 0 missing) that points at the traceability matrix.

### Added

#### Device-scoped management endpoints (`backend/app/api/v1/endpoints/sdwan.py`)

The IPsec device endpoints already existed (`/devices/{id}/ipsec/tunnels`,
`/devices/{id}/ipsec/apply`); this change extends the same pattern to the
remaining device-level services so every tab on the device detail page has a
real API to talk to instead of a read-only stub.

- **WireGuard** — `GET /devices/{id}/wireguard/servers` (list),
  `POST /.../wireguard/servers` (create, applies immediately),
  `DELETE /.../wireguard/servers/{uuid}` (delete + apply),
  `POST /.../wireguard/apply` (reconfigure). Uses the new
  `WireGuardServerBody` schema.
- **OpenVPN** — `GET /devices/{id}/openvpn/instances` (list),
  `POST /.../openvpn/instances` (create, applies immediately),
  `DELETE /.../openvpn/instances/{uuid}` (delete + apply),
  `POST /.../openvpn/apply` (reconfigure). Uses the new
  `OpenVpnInstanceBody` schema.
- **VLAN** — `GET /devices/{id}/vlans` (list),
  `POST /.../vlans` (create, applies interfaces),
  `DELETE /.../vlans/{uuid}` (delete + apply). Uses the new `VlanBody` schema.
- **DHCP** (read-only) — `GET /devices/{id}/dhcp/leases`,
  `GET /devices/{id}/dhcp/relays`. No OPNsense write API exists for DHCP
  configuration, so these are observation endpoints only.
- **DNS** (read-only) — `GET /devices/{id}/dns/records`,
  `GET /devices/{id}/dns/overrides`. Same rationale as DHCP.

Every endpoint:
- authenticates with the device's OPNsense API key/secret via
  `DeviceService(session, tenant_id).credentials(device)` and the
  `client_for(...)` context manager;
- is gated by `require_permissions(P.SDWAN_READ)` / `P.SDWAN_WRITE`;
- records an audit event (`wireguard.server_created`, `openvpn.instance_deleted`,
  `vlan.created`, etc.) with the device id, tenant id and principal id;
- commits the DB transaction after the audit record is written.

The OPNsense client (`backend/app/integrations/opnsense/client.py`) gained the
corresponding verbs earlier this session: `search/add/set/delete_wireguard_*`,
`apply_wireguard`, `search/add/set/delete_openvpn_*`, `apply_openvpn`,
`add/set/delete_vlan`, `apply_interfaces`, `search_dhcp_*`, `search_dns_*`.

### Implemented

#### Frontend device tabs (`frontend/src/pages/DeviceDetailPage.tsx`)

`DeviceDetailPage.tsx` now has ten tabs (Overview / Certificates / Commands /
Firmware / IPsec / WireGuard / OpenVPN / VLAN / DHCP / DNS). The six new
device-scoped tabs reuse the existing `DataTable`, `FormDialog`,
`ConfirmDialog`, `SectionCard` and `PermissionGate` components.

- **Firmware** — `firmwareStatus`, `upgradeFirmware`, `rebootDevice` wrappers
  were already present; the tab now shows the recorded product/series/version,
  an upgrade CTA when a newer release is available, and a reboot CTA.
- **IPsec** — read-only table of phase 1 + phase 2 tunnels. A `Manage` button
  (gated by `sdwan:write`) opens the existing SD-WAN device IPsec view.
- **WireGuard** — table of servers with `Add server` (gated by `sdwan:write`)
  and per-row delete. The create dialog asks for name, endpoint, port and
  network; the delete dialog confirms before calling the API.
- **OpenVPN** — same pattern as WireGuard: list, create (name, network, port),
  per-row delete.
- **VLAN** — list, create (name, VLAN ID, interface), per-row delete.
- **DHCP** — read-only table of leases reported by the host.
- **DNS** — read-only table of host records.

`frontend/src/api/endpoints.ts` gained `deviceSdwanApi`, an object with 14
device-scoped methods (`ipsecTunnels`, `createIpsecTunnel`, `applyIpsec`,
`wireguardServers`, `createWireguardServer`, `deleteWireguardServer`,
`applyWireguard`, `openvpnInstances`, `createOpenvpnInstance`,
`deleteOpenvpnInstance`, `applyOpenvpn`, `vlans`, `createVlan`,
`deleteVlan`, `dhcpLeases`, `dhcpRelays`, `dnsRecords`, `dnsOverrides`).
Each method targets `/sdwan/devices/{id}/...` and returns `unknown[]` or
`Message`, matching the live API contract.

#### RBAC gap

`P.SDWAN_READ` / `P.SDWAN_WRITE` are currently ADMIN-only (see
`backend/app/rbac/permissions.py`). Because the new device endpoints are
gated by those permissions, OPERATOR and AUDITOR roles cannot use the
WireGuard / OpenVPN / VLAN / IPsec / DHCP / DNS tabs at all. Either:
- grant `SDWAN_READ` to OPERATOR and AUDITOR (read-only tabs), or
- introduce new `WIREGUARD_READ` / `OPENVPN_READ` / `VLAN_READ` /
  `DHCP_READ` / `DNS_READ` permissions and gate the endpoints with those
  instead of `SDWAN_READ`.