# Load tests (k6)

Four scenarios that cover the paths a production tenant actually uses. They are
not part of the CI pipeline (they need a seeded deployment and take minutes);
run them before a release and whenever the fleet size or worker concurrency
changes.

## Install

```bash
# Linux/macOS
sudo apt-get install k6        # or: brew install k6
# Windows
choco install k6
```

## Prepare the target

1. Use a **dedicated tenant** and a dedicated account. The write tests create
   and delete devices, and the authentication test produces refresh sessions.
2. Prefer an API key (Settings → API keys) with `device:read`, `device:write`,
   `device:delete`, `device:exec`, `metric:read`, `audit:read`:

   ```bash
   export API_KEY=ofme_xxx
   ```

   A username/password pair also works, but the account must not have MFA
   enabled and must not be locked out by the failure counter.
3. Seed a representative fleet. For a 10 000-device run, restore a database
   dump from a comparable installation, or create devices in a loop through
   `POST /api/v1/devices` (a few thousand requests at 200 concurrency take
   minutes, not hours).

## Scenarios

| File | Purpose | Default shape |
|---|---|---|
| `smoke.js` | One user, every critical read path, fails on any non-200 | 1 iteration |
| `auth.js` | Login, refresh rotation, rejected credentials | 5 logins/s, 2 refresh/s, 2 min |
| `devices.js` | Create → read → patch → command → delete | 10 VUs ramping, 2 min |
| `fleet.js` | Dashboard + paginated inventory at scale | 50 VUs ramping, 5 min |

## Run

```bash
# Health and authentication first
k6 run -e BASE_URL=https://ofme.example.com -e API_KEY=$API_KEY tests/load/smoke.js

# Sizing run: 200 concurrent operators against the dashboard
k6 run -e BASE_URL=https://ofme.example.com -e API_KEY=$API_KEY \
       -e VUS=200 -e DURATION=10m tests/load/fleet.js
```

Makefile shortcuts (they default to `http://localhost:8000`):

```bash
make load-smoke
make load-fleet
```

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | API origin (no `/api/v1`) |
| `API_KEY` | – | Bearer API key; takes precedence over login |
| `USERNAME` | `admin@ofme.example.com` | Login user when no API key is set |
| `PASSWORD` | – | Login password |
| `TENANT` | – | Tenant slug for the login payload |
| `TENANT_ID` | – | `X-Tenant-Id` header for SuperAdmin API keys |
| `VUS` | 10 / 50 | Peak virtual users (`devices.js` / `fleet.js`) |
| `DURATION` | `2m` / `5m` | Sustain phase |
| `PAGE_SIZE` | 50 | Inventory page size |
| `SLEEP` | 0.5 | Think time in seconds (`fleet.js`) |

## Reading the results

* `ofme_device_list_duration`, `ofme_dashboard_duration`,
  `ofme_device_search_duration`, `ofme_audit_list_duration` — per-endpoint
  latency trends. The thresholds in each file encode the SLOs.
* `ofme_business_errors` — responses that were HTTP 2xx but did not match the
  contract (missing JSON, wrong shape). Watch this before `http_req_failed`.
* `http_req_failed` counts transport errors and 5xx only; a 401/403 storm shows
  up in `checks`, not here.

If `fleet.js` breaches its p95 while CPU stays below 70%, look at PostgreSQL
(`pg_stat_statements`) before adding API replicas: the inventory queries are
index-bound, and the dashboard aggregates are the usual suspect.
