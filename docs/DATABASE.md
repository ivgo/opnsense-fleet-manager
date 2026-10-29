# Database

PostgreSQL 16 is the only durable store apart from objects in S3. The ORM in
`backend/app/models/` is the schema source of truth: `alembic` revision `0001`
materialises `Base.metadata`, and every later revision is an explicit `op.*`
change (`0002_dhcp_dns` adds the DHCP/DNS tables).

## Conventions

| Concern | Rule |
|---|---|
| Primary keys | `UUID` (`uuid4`), generated in Python (`UUIDPrimaryKeyMixin`) |
| Tenancy | `tenant_id UUID NOT NULL` with `ON DELETE CASCADE` (`TenantScopedMixin`) |
| Timestamps | `created_at` / `updated_at`, `timestamptz`, UTC, Python + `server_default` |
| Soft delete | `deleted_at timestamptz NULL` on user-facing aggregates; repositories filter it |
| Enums | stored as `VARCHAR(…)` via `native_enum=False`; values are the `StrEnum` members |
| Documents | `JSONB` with `MutableDict`/`MutableList` so in-place changes are detected |
| Naming | `snake_case`, plural tables; indexes `ix_<table>_<cols>`; constraints `uq_…`, `ck_…` |

Money, percentages and scores are integers or `Numeric` where exactness matters;
float is limited to measurements (`latency_ms`, `jitter_ms`, `loss_pct`).

## Tables

### Identity and access — 7 tables

| Table | Purpose | Notable columns |
|---|---|---|
| `tenants` | isolation boundary, plan and quota | `slug` (unique), `status`, `plan`, `device_limit`, `settings` |
| `users` | local, LDAP and OIDC identities | `password_hash` (Argon2id), `auth_provider`, `external_id`, `is_superadmin`, `mfa_*`, `failed_login_attempts`, `locked_until` |
| `roles` | named permission bundles, per tenant | `name`, `is_system`, `permissions` (JSONB list) |
| `permissions` | catalogue for the UI and auditing | `code`, `category`, `is_dangerous` |
| `refresh_tokens` | rotating refresh sessions | `jti`, `token_hash`, `expires_at`, `revoked_at`, `replaced_by`, `ip_address`, `user_agent` |
| `api_keys` | machine credentials | `key_prefix`, `key_hash` (SHA-256), `scopes`, `expires_at`, `last_used_at` |
| `audit_logs` | tamper-evident action trail | `prev_hash`, `entry_hash`, `actor`, `action`, `before`, `after`, `request_id` |

### Inventory — 5 tables

| Table | Purpose | Notable columns |
|---|---|---|
| `sites` | physical locations | `code`, `address`, `latitude`, `longitude`, `timezone` |
| `device_groups` | hierarchical grouping | `parent_id`, `template_id`, `labels` |
| `devices` | the fleet | `name`, `hostname`, `serial_number`, `status`, `connection_status`, `is_ha`, `ha_role`, `tags`, `last_seen_at`, encrypted API credentials |
| `device_certificates` | issued agent identities | `serial_number`, `fingerprint_sha256`, `valid_from`, `valid_to`, `status`, `revoked_at` |
| `device_telemetry_snapshots` | latest per-device state | CPU/memory/disk, sessions, uptime, VPN and gateway counters, `interfaces`, `raw` |

### Configuration — 10 tables

| Table | Purpose | Notable columns |
|---|---|---|
| `firewall_rules` | firewall policy | `action`, `direction`, `interface`, `protocol`, `source`, `destination`, `source_port`, `destination_port`, `order_index`, `enabled` |
| `aliases` | reusable address/port sets | `name`, `type`, `content`, `enabled` |
| `nat_rules` | NAT and port forwards | `type`, `interface`, `protocol`, `source`, `destination`, `destination_port`, `target`, `target_port` |
| `interface_configs` | interface desired state | `name`, `physical_if`, `ip_address`, `subnet_bits`, `gateway` |
| `route_configs` | static routes | `network`, `gateway`, `interface`, `metric` |
| `vlan_configs` | VLAN interfaces | `vlan_id`, `parent_interface`, `description` |
| `dhcp_scopes` | DHCP pools per device | `subnet`, `pool_start`, `pool_end`, `gateway`, `dns_servers`, `domain_name`, `lease_time_seconds`, `options` |
| `dhcp_reservations` | static MAC→IP bindings | `scope_id`, `hostname`, `mac_address`, `ip_address` |
| `dns_records` | authoritative DNS records | `name`, `record_type`, `value`, `ttl`, `priority`, `weight`, `port` |
| `templates` | layered configuration templates | `kind`, `parent_id`, `body`, `variables` |

All of them are tenant-scoped, most are device- or group-scoped, and all carry
`version` or an audit trail so that a deployment can be traced to the object
version that produced it. `dhcp_scopes`, `dhcp_reservations` and `dns_records`
use partial unique indexes (`WHERE deleted_at IS NULL`) so a name, subnet, MAC or
record can be re-created after a soft delete. `templates.parent_id` expresses
inheritance; the body is rendered with Jinja2 `StrictUndefined` after the
ancestor chain is deep-merged.

### Policy as code — 4 tables

| Table | Purpose | Notable columns |
|---|---|---|
| `policies` | documents from Git or the UI | `repo_id`, `kind`, `environment`, `path`, `content`, `content_hash`, `version`, `status`, `target_selector`, `validation_errors` |
| `policy_deployments` | one attempt to apply a policy | `status`, `commit_sha`, `plan`, `target_device_ids`, `results`, `logs`, `started_at`, `completed_at`, `approved_by` |
| `drift_reports` | desired vs actual | `policy_id`, `status`, `differences` (JSONB), `desired_hash`, `actual_hash`, `detected_at`, `resolved_at` |
| `change_requests` | four-eyes approvals | `type`, `payload`, `status`, `required_approvals`, `approvals`, `requested_by`, `expires_at` |

### SD-WAN — 5 tables

`sdwan_topologies`, `sdwan_links`, `vpn_tunnels`, `sdwan_routes`,
`traffic_policies`. Tunnels hold the WireGuard `public_key` and an **encrypted**
`preshared_key_encrypted`; links carry the SLA measurements that drive steering.

### Zero-touch provisioning — 1 table

`ztp_enrollments`: `token_hash` + `token_hint` (the token itself is never stored),
device serial/MAC constraints, `status`, `discovery_method`, the created
`device_id`, `certificate_serial`, `expires_at`.

### Operations — 7 tables

| Table | Purpose |
|---|---|
| `backups` | `storage_key`, `checksum_sha256`, HMAC `signature`, size, firmware/config version |
| `jobs` | API-visible background work: `task_name`, `celery_task_id`, `status`, `progress`, `params`, `result`, `error` |
| `tasks` | tenant cron definitions: `kind`, `cron`, `payload`, `enabled`, `last_run_at`, `next_run_at` |
| `alerts` | active/resolved alerts with a `fingerprint` for de-duplication |
| `alert_rules` | metric, operator, threshold, duration, severity, channels |
| `notifications` | per-user inbox rows |
| `device_metrics` | time series (`metric_type`, `value`, `labels`, `recorded_at`) |

### Governance — 3 tables

`compliance_reports` (`framework`, `scope`, `score`, `controls`, `findings`,
`artifact_key`), `domain_events`, `audit_logs` (listed above).

## Indexes

Every `tenant_id` is indexed; composite indexes cover the query shapes the API
actually issues:

| Index | Table | Serves |
|---|---|---|
| `ix_devices_tenant_status` | devices | device list filtered by status |
| `ix_devices_tenant_site` | devices | site drill-down |
| `ix_devices_serial` | devices | serial lookup during discovery/enrolment |
| `ix_device_metrics_tenant_time` | device_metrics | series queries and the retention purge |
| `ix_device_metrics_lookup` | device_metrics | per-device metric lookup |
| `ix_audit_logs_tenant_time` | audit_logs | audit page, newest first |
| `ix_audit_logs_resource` | audit_logs | "what happened to this object" |
| `ix_drift_reports_tenant_device` | drift_reports | open drift per device |
| `ix_jobs_tenant_status` | jobs | job list and worker recovery |
| `uq_device_certificates_serial_number` | device_certificates | uniqueness of issued serials |

Long lists are always paginated with `LIMIT/OFFSET` (max `size=500`) and ordered
by an indexed column; there is no unbounded `SELECT *` endpoint.

## Audit hash chain

`audit_logs` is append-only at the application level. Each row stores
`prev_hash` (the previous row's `entry_hash`) and
`entry_hash = SHA-256(prev_hash || canonical_json(entry))`. Inserts take a
transaction-scoped advisory lock (`pg_advisory_xact_lock(918273645)`) so the chain
cannot fork under concurrent writers. `GET /api/v1/audit/integrity` recomputes
the chain and reports the first divergence; the `ofme_audit_chain_valid` gauge
backs the `OFMEAuditChainBroken` alert.

`domain_events` uses the same pattern *per aggregate*: `sequence` increments per
`(aggregate_type, aggregate_id)` and `event_hash` chains the aggregate's history.

## Migrations

```bash
cd backend
alembic upgrade head
alembic revision --autogenerate -m "add sdwan sla columns"   # review before commit
alembic downgrade -1
```

* `0001_initial` calls `Base.metadata.create_all` / `drop_all`; it is the
  reproducible baseline for a fresh database.
* `0002_dhcp_dns` uses `table.create(checkfirst=True)`: on a fresh database
  `0001` already created the DHCP/DNS tables from metadata, while databases
  initialised by an earlier release get them added without a failure.
* Later revisions must contain explicit `op.add_column`, `op.create_index`, … so
  they remain reviewable and reversible. `alembic/versions` is excluded from Ruff
  for that reason.
* CI runs `upgrade → downgrade base → upgrade` against a fresh PostgreSQL before
  the test suite; a migration that cannot round-trip fails the build.

## Retention

| Data | Mechanism | Default |
|---|---|---|
| `device_metrics` | `ofme.monitoring.purge_metrics` (03:30 daily) | `METRIC_RETENTION_DAYS` = 90 |
| `backups` | `apply_retention(keep_per_device=30)` after the nightly run | 90 days / 30 per device |
| `audit_logs` | never purged automatically | `AUDIT_RETENTION_DAYS` = 2555 (7 years) |
| `domain_events` | kept with the aggregate | – |
| `refresh_tokens` | expired/revoked rows pruned by the auth service | on login |

Audit rows are the exception: deleting them is a compliance decision, so the
platform exposes the retention setting and an export path but never drops them on
a timer.

## Database-level backup

The application backs up *devices*. Backing up the *platform* is a PostgreSQL
responsibility:

```bash
# logical, consistent, compresses well
docker compose exec -T postgres pg_dump -U ofme -d ofme --clean --if-exists \
  | gzip -9 > ofme-$(date -u +%Y%m%dT%H%M%SZ).sql.gz

# physical / PITR (managed PostgreSQL or patroni)
#   base backup + WAL archive, restore to a timestamp
```

Restore drill (quarterly, in a scratch namespace):

```bash
gunzip -c ofme-20260101T000000Z.sql.gz | docker compose exec -T postgres psql -U ofme -d ofme
# then: alembic upgrade head, verify /api/v1/audit/verify, log in, check the fleet count
```

The audit chain survives a logical dump because `prev_hash`/`entry_hash` are
stored values; the verification endpoint proves it after every restore.

## Capacity notes

* `shared_buffers` 25% of RAM, `effective_cache_size` 50–75%, `max_connections`
  ≥ `(api_replicas × 30) + (worker_replicas × concurrency + 10)`.
* The API pool is `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` per process; with uvicorn
  running one worker per pod the defaults (10 + 20) suffice for ~10 pods.
* `device_metrics` is the fastest-growing table: one row per metric per scrape.
  At 10 000 devices × 8 metrics × 1/minute that is ~115 M rows/month — reduce the
  scrape interval, or partition by month before reaching that scale.
