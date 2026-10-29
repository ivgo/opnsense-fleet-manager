# Operations

Day-two behaviour: what to watch, what the alerts mean, and what to do when they
fire. Every alert in `monitoring/prometheus/alerts/ofme.yml` links to an anchor in
this file.

## Service level indicators

| Indicator | Source | Target |
|---|---|---|
| API availability | `up{job="ofme-api"}` | 99.9% monthly |
| API error ratio | `ofme_http_requests_total{status=~"5.."}` / total | < 0.5% |
| API latency | `ofme_http_request_duration_seconds` | p95 < 500 ms, p99 < 1.5 s |
| Heartbeat acceptance | `ofme_device_heartbeats_total{result="ok"}` | > 99% of agents |
| Fleet freshness | `max(time() - ofme_device_last_seen_timestamp)` | < 5 min |
| Backup success | `ofme_backups_total{result="success"}` | > 98% per night |
| Audit integrity | `ofme_audit_chain_valid` | always 1 |
| Job failure | `ofme_jobs_finished_total{status="failed"}` | < 1% |
| Drift | `ofme_policy_drift_findings` | < 25 open |

The Grafana dashboard (`monitoring/grafana/dashboards/ofme-overview.json`) renders
all of these; the API also exposes a JSON view at
`GET /api/v1/metrics/dashboard?trend_hours=24&health_limit=100`.

## Health endpoints

| Endpoint | Use | Behaviour |
|---|---|---|
| `/api/v1/health/live` | liveness probe | always 200 while the event loop runs |
| `/api/v1/health/startup` | startup probe | 200 once the app is constructed |
| `/api/v1/health/ready` | readiness probe | 200 only if PostgreSQL, Redis, S3 and the PKI all answer; 503 otherwise, with per-component detail |
| `/api/v1/health/version` | build metadata | version, environment, Python version |
| `/metrics` | Prometheus scrape | protected at the network layer, not by auth |

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health/ready | jq
curl -fsS http://127.0.0.1:8000/metrics | grep '^ofme_'
```

Readiness deliberately includes object storage: without S3, backups fail and the
instance is not fully functional. `pki` is reported as `down` when the CA cannot
be loaded, which is a hard failure for enrolment.

## Alert runbooks

<a id="api-unavailable"></a>

### `OFMEApiDown` — api-unavailable

**Meaning:** Prometheus has not scraped `ofme-api` for 2 minutes.

1. Confirm scope: `up{job="ofme-api"}` for every instance — all instances or one?
2. Check the orchestrator:
   ```bash
   docker compose ps ofme-api
   docker compose logs --tail=200 ofme-api
   # or
   kubectl -n ofme get pods -l app.kubernetes.io/component=api
   kubectl -n ofme describe pod -l app.kubernetes.io/component=api
   kubectl -n ofme logs deploy/ofme-api --tail=200
   ```
3. Distinguish crash-loop from network:
   * `startup.pki_failed` / `startup.storage_failed` are non-fatal; the API still
     serves but readiness is 503.
   * An exception during module import means a bad image or missing config —
     roll back the tag.
   * `OOMKilled` in `describe` means the memory limit is too low for the fleet
     size; raise it before restarting.
4. If the pod is up but not scraped, check the Service, the ServiceMonitor/ scrape
   annotations and the NetworkPolicy allowing Prometheus.
5. If PostgreSQL is down, the API still answers `/health/live` but every real
   request is 500 — treat it as a database incident, not an API one.

Escalate to a rollback when the previous revision was healthy and the change
window matches the outage:
`helm rollback ofme <revision>` / `docker compose up -d` with the previous
`OFME_IMAGE_TAG`.

<a id="elevated-error-rate"></a>

### `OFMEHighErrorRate` — elevated-error-rate

**Meaning:** more than 5% of requests returned 5xx for 10 minutes.

1. Identify the route:
   ```promql
   topk(10, sum by (route) (rate(ofme_http_requests_total{status=~"5.."}[5m])))
   ```
   `route` is the matched template, not the raw path, so `/api/v1/devices/{device_id}`
   is one series.
2. Pull a failing request id from the logs (every response carries `X-Request-ID`
   and every log line `request_id`):
   ```bash
   docker compose logs ofme-api | grep -m5 '"status": 500'
   # Loki
   {container="ofme-api"} |= "http.unhandled_exception" | json | line_format "{{.request_id}} {{.error}}"
   ```
3. Common causes:
   * **Database pool exhaustion** — logs show `TimeoutError` from asyncpg or
     `QueuePool limit`. Check `pg_stat_activity`; lower `DB_POOL_SIZE` per pod or
     add pgbouncer.
   * **Upstream device errors surfaced as 500** — a device's API is unreachable or
     its credentials were rotated. Look for the device id in the error; the API
     should return 502 (`UpstreamError`) for those, so a 500 means a bug.
   * **Validation escaping as 500** — report it: `RequestValidationError` is
     normalised to 422 and should never be a 500.
   * **S3/MinIO outage** — backup and download endpoints fail; `/health/ready`
     shows `object_storage: down`.
4. If the error rate is caused by one tenant's automation, throttle it at the
   ingress rather than taking the platform down.

<a id="high-latency"></a>

### `OFMESlowRequests` — high-latency

**Meaning:** p95 above 1 s for 10 minutes.

1. Split by route:
   ```promql
   histogram_quantile(0.95, sum by (route, le) (rate(ofme_http_request_duration_seconds_bucket[5m])))
   ```
2. Usual suspects, in order:
   * **Dashboard aggregates** (`/metrics/dashboard`, `/metrics/summary`) on a large
     tenant: `device_metrics` and `devices` scans. Check
     `pg_stat_statements` for the top mean-exec-time query.
   * **Unindexed device search**: `/devices/search` uses a trigram/`ILIKE` path;
     a very short `q` with a large fleet is expensive.
   * **Audit list** with a wide date range: refine the filter or export instead.
   * **Argon2 login latency**: ~150–300 ms per login is expected; a burst of
     logins shows up as p95 on `/auth/login`, not as a database problem.
3. If PostgreSQL is the bottleneck: add the missing index from DATABASE.md, raise
   `shared_buffers`/`effective_cache_size`, or add a read replica for reporting.
4. If only one API replica is slow, check node CPU throttling (`container_cpu_cfs_throttled_seconds_total`).

<a id="devices-offline"></a>

### `OFMENoDeviceHeartbeats` — devices-offline

**Meaning:** zero accepted heartbeats for 15 minutes across the whole fleet.

1. Confirm it is platform-wide, not a metric gap:
   ```bash
   curl -fsS -H "Authorization: Bearer $TOKEN" \
     'http://localhost:8000/api/v1/devices/summary' | jq
   ```
2. Check ingest: `ofme_device_heartbeats_total` should be non-zero. If the metric
   is absent entirely, the counter is not being incremented (deploy problem).
3. Check the edge:
   * ingress 5xx/413/499 on `/api/v1/agent/heartbeat`;
   * mTLS misconfiguration — if the ingress stopped forwarding
     `X-Client-Cert-Fingerprint`, every agent gets 401 (see the next runbook);
   * certificate expiry of the **server** certificate (agents verify TLS).
4. Check a single agent from its device:
   ```bash
   # on the OPNsense box
   service os_fleet_agent status
   tail -n 100 /var/log/ofme-agent.log
   /usr/local/etc/rc.d/os_fleet_agent onestatus
   ```
5. If only one site is silent, it is a network path (NAT/firewall/VPN) — the
   platform side is fine.

<a id="heartbeat-rejections"></a>

### `OFMEHeartbeatRejections` — heartbeat-rejections

**Meaning:** more than 10% of heartbeat attempts were rejected for 15 minutes.

1. Break down by result:
   ```promql
   sum by (result) (rate(ofme_device_heartbeats_total[10m]))
   ```
   `result` is `ok` or the rejection reason class.
2. Correlate with the audit trail: `GET /api/v1/audit?action=device.heartbeat_rejected`
   shows the device and reason per attempt.
3. Causes:
   * **Certificate not active / expired** — `GET /api/v1/devices/{id}/certificates`.
     Rotate with `POST /api/v1/devices/{id}/certificates` or let
     `ofme.devices.rotate_certificates` run.
   * **Fingerprint mismatch** — a device restored from a backup kept the old key,
     or the ingress forwards the wrong header variable. Compare
     `openssl x509 -fingerprint -sha256 -noout -in device.crt` on the device with
     `device_certificates.fingerprint_sha256`.
   * **Clock skew** — the payload timestamps are validated; a device more than a
     few minutes off is rejected. Fix NTP on the device.
   * **Serial fallback in production** — a device without a certificate is
     rejected by design outside `development`/`testing`. Enrol it.
   * **Unknown device** — `X-Device-Id` names a deleted or foreign tenant's
     device; the agent state file was copied between boxes.

<a id="audit-chain-broken"></a>

### `OFMEAuditChainBroken` — audit-chain-broken

**Meaning:** `ofme_audit_chain_valid == 0`; the tamper-evident trail no longer
verifies.

1. Treat as a security incident **and** a data-integrity incident. Stop writes if
   you can: scale the API and workers to zero, or set the Service to no endpoints,
   so the trail stops moving.
2. Identify the first divergence:
   ```bash
   curl -fsS -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/v1/audit/integrity | jq
   ```
   The response names the first entry whose recomputed hash differs and the
   expected/actual values.
3. Preserve evidence before touching anything:
   ```bash
   docker compose exec -T postgres pg_dump -U ofme -d ofme --clean --if-exists \
     | gzip -9 > incident-audit-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
   ```
4. Causes, in likelihood order:
   * **Restore of a partial dump** — rows from a later transaction were restored
     without their predecessors. Compare `created_at`/`id` ordering around the
     break.
   * **Manual `UPDATE`/`DELETE` on `audit_logs`** — the chain is append-only by
     convention; any edit breaks it.
   * **Concurrent writers bypassing the advisory lock** — only possible if
     something writes audit rows outside `AuditService`.
   * **Clock/ordering bug** after an upgrade — check whether the break coincides
     with a deploy.
5. Recovery: restore the last consistent dump and replay the audit export, or
   document the break and continue with a new chain segment if the business
   accepts it. Never "fix" hashes in place; that destroys the evidentiary value.
6. After recovery, verify `/api/v1/audit/integrity`, confirm
   `ofme_audit_chain_valid == 1`, and export the segment to WORM storage.

<a id="backup-failures"></a>

### `OFMEBackupFailures` — backup-failures

**Meaning:** more than 20% of backup attempts failed in the last hour.

1. Identify the failure class from the jobs API:
   ```bash
   curl -fsS -H "Authorization: Bearer $TOKEN" \
     'http://localhost:8000/api/v1/jobs?status=failed&size=50' | jq '.items[] | {task_name, error}'
   ```
2. Check object storage first — it is the most common cause:
   * `GET /api/v1/health/ready` → `object_storage`;
   * credentials/expiry (`S3_ACCESS_KEY`), bucket policy, free space;
   * MinIO: `docker compose logs minio`.
3. Then device reachability: `ofme.backups.create` fails per device with
   `UpstreamError` when the OPNsense API is unreachable or the API key was
   rotated. Check `devices.last_seen_at` for the affected set.
4. Verify what did land:
   ```bash
   curl -fsS -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/v1/backups | jq '.items[] | {device_id, status, size_bytes}'
   ```
   Every stored object has a SHA-256 checksum and an HMAC signature; a restore
   verifies both (`POST /api/v1/backups/{id}/restore` with `dry_run=true` first).
5. Retention runs after the nightly sweep (`keep_per_device=30`,
   `apply_retention=true`). If storage is full because retention stopped, run
   `ofme.backups.run_scheduled` manually with retention enabled — do not delete
   objects by hand.

<a id="worker-backlog"></a>

### `OFMEJobFailures` — worker-backlog

**Meaning:** background jobs are failing faster than 0.2/s for 15 minutes, or the
queue is not draining.

1. Check the queue depth and worker state:
   ```bash
   docker compose exec redis redis-cli -n 1 llen ofme
   docker compose exec ofme-worker celery -A app.workers.celery_app:celery_app inspect active
   docker compose exec ofme-worker celery -A app.workers.celery_app:celery_app inspect reserved
   docker compose exec ofme-worker celery -A app.workers.celery_app:celery_app inspect stats
   ```
2. Look at the failures by task:
   ```promql
   topk(10, sum by (task) (rate(ofme_jobs_finished_total{status="failed"}[15m])))
   ```
3. Common patterns:
   * **Stuck on one device** — a device API times out at `OPNsense_TIMEOUT_SECONDS`
     (20 s); a hung worker slot per bad device. Confirm with `inspect active`.
   * **Database connections exhausted** — workers use a per-task `NullPool`
     engine; `max_connections` must cover `replicas × concurrency + API pool`.
   * **Result backend unreachable** — tasks execute but the `Job` row stays
     `running`; check `CELERY_RESULT_BACKEND` and Redis memory
     (`maxmemory-policy noeviction` is intentional).
   * **Task not registered** — a deploy shipped a task name that is not in
     `ALL_TASKS`; the dispatch whitelist rejects it before Celery, so look for
     `job.rejected` in the logs.
4. A single stuck job can be cancelled:
   `POST /api/v1/jobs/{id}/cancel` (sets the row to `cancelled`; Celery revoke is
   best-effort). For a wedged worker, restart the pod — tasks are idempotent and
   the `jobs` row is the source of truth.
5. Scale workers with `worker.replicaCount` / `worker.concurrency`, not by adding
   queues: everything runs on the single `ofme` queue.

### Other alerts

| Alert | First check |
|---|---|
| `OFMEExceptionBurst` | same as elevated-error-rate; this is the early signal |
| `OFMEWebSocketDrop` | Redis pub/sub (`ofme:ws`), ingress `/ws` upgrade, browser proxy |
| `OFMEPolicyDriftHigh` | `GET /api/v1/drift?status=open`; a recent manual change on devices |
| `OFMEComplianceScoreLow` | the newest report's failed controls; check whether a framework's facts are stale |

## Routine operations

### Daily

* Dashboard: offline devices, open alerts, drift count, last night's backups.
* `GET /api/v1/jobs?status=failed&size=50` — triage anything unexplained.
* Check certificate expiry: devices within `PKI_RENEW_BEFORE_DAYS` should renew
  automatically at 04:00.

### Weekly

* Review `audit_logs` for `permission`/`role`/`api_key` changes.
* Confirm the compliance sweep (Monday 05:00) produced reports for every enabled
  framework.
* Review `/api/v1/auth/sessions` for long-lived sessions and unusual user agents.
* Check database growth (`pg_database_size`) and `device_metrics` row count trend.

### Monthly

* Restore one backup to a lab device (or `dry_run=true` at minimum) and verify the
  signature end to end.
* Rotate API keys used by automation; confirm no key is older than policy.
* Review RBAC: users in `TenantAdmin`/`Admin`, dormant accounts, SuperAdmin count.
* Apply dependency and image updates; re-run `make check`.

### Quarterly

* Full disaster-recovery drill in a scratch namespace (restore dump, verify audit
  chain, enrol one device, restore one backup).
* Load test at the next fleet-size tier (`tests/load/README.md`).
* Review PKI: CA expiry (10 years), device certificate age distribution, CRL
  process.
* Tabletop the `audit-chain-broken` and CA-compromise scenarios.

## Logs

Structured JSON on stdout (`LOG_JSON=true`), collected by Promtail into Loki.
Every line carries `timestamp`, `level`, `event`, `request_id` (when in a
request), `tenant_id`, `user_id`.

```logql
# errors only
{container="ofme-api"} | json | level="error"

# one request end to end
{container="ofme-api"} | json | request_id="8f14e45fceea167a"

# rejected heartbeats with reasons
{container="ofme-api"} | json | event="agent.heartbeat_rejected"

# slow requests
{container="ofme-api"} | json | duration_ms > 1000
```

Key event names: `startup.*`, `shutdown.*`, `http.request`,
`http.unhandled_exception`, `pki.*`, `agent.heartbeat_rejected`,
`drift.device_unreachable`, `job.*`, `backup.*`, `policy.*`.

Common log fields by subsystem:

| Subsystem | Fields |
|---|---|
| HTTP | `method`, `path`, `route`, `status`, `duration_ms`, `client`, `user_agent` |
| Auth | `action`, `user`, `ip`, `reason` |
| Agent | `device`, `result`, `reason` |
| Workers | `task`, `job_id`, `device`, `duration_ms` |
| PKI | `subject`, `serial`, `fingerprint`, `not_after` |

## Metrics catalogue

Application metrics (prefix `ofme_`):

| Metric | Type | Labels |
|---|---|---|
| `ofme_http_requests_total` | counter | `method`, `route`, `status` |
| `ofme_http_request_duration_seconds` | histogram | `method`, `route` |
| `ofme_http_requests_in_flight` | gauge | – |
| `ofme_http_exceptions_total` | counter | `type` |
| `ofme_device_heartbeats_total` | counter | `result` |
| `ofme_websocket_connections` | gauge | – |
| `ofme_websocket_messages_total` | counter | – |
| `ofme_jobs_enqueued_total` | counter | `task` |
| `ofme_jobs_finished_total` | counter | `task`, `status` |
| `ofme_job_duration_seconds` | histogram | `task` |
| `ofme_backups_total` | counter | `result` |
| `ofme_backups_stored_bytes` | gauge | – |
| `ofme_policy_drift_findings` | gauge | – |
| `ofme_compliance_runs_total` | counter | `framework`, `status` |
| `ofme_compliance_score` | gauge | `framework` |
| `ofme_audit_chain_valid` | gauge | – |
| `ofme_rate_limited_total` | counter | `scope` (`api`/`auth`) |
| `ofme_cache_operations_total` | counter | `operation`, `result` |

`route` is always the template (`/api/v1/devices/{device_id}`), never a raw path,
so cardinality stays bounded.

A sustained rise in `ofme_rate_limited_total` means either a misconfigured
client (retry loop, missing backoff) or credential stuffing. Check the
`ratelimit.exceeded` log lines, which carry `scope`, the digested identity, the
path and the configured limit. If a legitimate integration is throttled, raise
`RATE_LIMIT_REQUESTS`/`RATE_LIMIT_AUTH_REQUESTS` rather than disabling the
limiter; if `ratelimit.redis_unavailable` appears, counters fall back to
per-replica memory and budgets become N× looser with N replicas.

## Scheduled work

Celery beat (single instance) drives:

| Schedule | Task | When |
|---|---|---|
| `heartbeat-timeout` | `ofme.monitoring.heartbeat_timeout` | every `HEARTBEAT_INTERVAL_SECONDS` (60 s) |
| `poll-devices` | `ofme.monitoring.collect` | every 5 min, 500 devices per run |
| `sdwan-health-sweep` | `ofme.sdwan.health_sweep` | every 5 min |
| `nightly-backups` | `ofme.backups.run_scheduled` | 02:00 daily, with retention |
| `purge-metrics` | `ofme.monitoring.purge_metrics` | 03:30 daily |
| `rotate-certificates` | `ofme.devices.rotate_certificates` | 04:00 daily |
| `policy-drift-scan` | `ofme.policies.drift_scan` | every 30 min |
| `weekly-compliance` | `ofme.compliance.run` | Monday 05:00 |
| `tenant-schedules` | `ofme.tasks.custom` (`scheduler_tick=true`) | every 60 s |

Tenant-defined schedules (`/api/v1/tasks`) are materialised by the last entry:
the tick compares `next_run_at` and enqueues the mapped task. Allowed kinds are
`backup`, `compliance_scan`, `firmware_upgrade`, `policy_deploy`, `drift_scan`,
`metric_collect` and `custom` (custom is limited to `noop`, `echo`, `touch`).

Run something now:

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"task_name":"ofme.backups.run_scheduled","params":{"apply_retention":true}}' \
  http://localhost:8000/api/v1/jobs | jq
```

The response is a `Job` in `pending`; poll `GET /api/v1/jobs/{id}` until
`completed`/`failed`.

## Backup and restore verification

```bash
# list the newest backups
curl -fsS -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/backups?size=20' | jq '.items[:5]'

# non-destructive restore check (downloads, verifies checksum + HMAC, no push)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dry_run":true}' \
  http://localhost:8000/api/v1/backups/$BACKUP_ID/restore | jq

# real restore (writes the config back to the device)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dry_run":false,"reboot":false}' \
  http://localhost:8000/api/v1/backups/$BACKUP_ID/restore | jq
```

A restore is refused when the signature does not verify. That is a signal to
investigate the object (storage corruption or a `SECRET_KEY` change), not to
retry.

## Scaling and tuning

| Symptom | Action |
|---|---|
| API CPU > 70% sustained | raise `api.replicaCount`/HPA max; keep one uvicorn worker per pod |
| p95 grows with fleet size, CPU low | database: indexes, `shared_buffers`, `pg_stat_statements` |
| Worker queue > 1000 for > 15 min | raise worker replicas/concurrency, or batch enqueues |
| `device_metrics` write amplification | lower scrape frequency or partition the table |
| Backup window overruns | raise worker concurrency; shard nightly runs per site |
| WebSocket connections > ~5 000/pod | add API replicas; verify Redis pub/sub latency |

Connection budget:

```
max_connections ≥ api_pods × (DB_POOL_SIZE + DB_MAX_OVERFLOW)
                + worker_pods × worker_concurrency
                + beat + migrations + operator sessions
```

With the defaults (10 + 20 per API pod, 4 per worker slot), 8 API pods and 8
workers × 8 slots need ~300 connections. Use pgbouncer beyond that.

## Incident response (short form)

1. **Declare and scope** — which tenant, which devices, read or write path.
2. **Stabilise** — roll back the last deploy, scale out, or shed load at the
   ingress. Do not delete data to make an alert go away.
3. **Preserve** — snapshot the database before any repair, capture the request id
   and audit entries.
4. **Eradicate** — rotate the affected credentials (`SECRET_KEY` rotation
   invalidates stored device secrets: re-encrypt, do not just change it), revoke
   API keys and refresh sessions, revoke device certificates.
5. **Recover** — verify `/health/ready`, `/audit/integrity`, heartbeats, one
   backup/restore, one policy deployment.
6. **Review** — timeline from audit + logs + `domain_events`, then close with
   concrete follow-ups.
