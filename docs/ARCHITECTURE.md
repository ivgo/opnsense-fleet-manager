# Architecture

OFME is a modular monolith: one deployable FastAPI process plus Celery workers,
with hard internal boundaries instead of network boundaries. Every module is a
Python package with one direction of dependency, which keeps a future split into
services mechanical rather than a rewrite.

## Layers

```
app/api/            HTTP + WebSocket delivery (routers, dependencies, schemas)
app/cqrs/           command/query buses and their handlers
app/services/       use cases: transactions, authorisation decisions, audit
app/repositories/   persistence per aggregate + UnitOfWork
app/models/         SQLAlchemy 2.x mappings (the schema source of truth)
app/domain/         framework-free rules (status transitions, policy compilation)
app/integrations/   outbound adapters: OPNsense API, S3, Git providers, LDAP, OIDC, Vault
app/workers/        Celery tasks (the same services, run outside the request cycle)
app/pki/            internal certificate authority
app/observability/  logging, metrics, tracing
```

Dependencies point inwards only:

```
api ──► cqrs ──► services ──► repositories ──► models
                   │
                   ├──► domain        (pure functions and value objects)
                   ├──► integrations  (I/O behind small interfaces)
                   └──► pki
workers ──► services (identical entry points, different trigger)
```

`api` never touches `repositories` directly, `services` never builds SQL by hand
for a list query, and `domain` imports nothing but the standard library.

## Request lifecycle

1. **Uvicorn → middleware.** `RequestContextMiddleware` assigns a request id,
   binds it to the structured logger and the OpenTelemetry span,
   `MetricsMiddleware` records latency and status, `CORSMiddleware`,
   `RateLimitMiddleware` (`app/core/rate_limit.py`, per-credential/device/IP
   fixed window with `429` + `Retry-After`) and the trusted-proxy handler run at
   the edge. `main.create_app()` registers them in a fixed order.
2. **Authentication.** `app/api/deps.py` resolves the bearer credential: a JWT
   access token (validated for signature, expiry, token type and tenant) or an
   `ofme_…` API key (looked up by SHA-256 hash, then intersected with its scopes).
3. **Tenant resolution.** `get_tenant_id` returns the principal's tenant. A
   SuperAdmin must name the tenant explicitly via `X-Tenant-Id`; forgetting the
   header is a 400, never a cross-tenant read.
4. **Authorisation.** `require_permissions("device:write", …)` compares the
   principal's permission set with the route's requirement. Roles are just named
   permission bundles (`app/rbac/permissions.py`).
5. **Validation.** Pydantic v2 request models; failures are normalised into the
   `{error: {code, message, details, request_id}}` envelope by the handler in
   `main.py` (non-serialisable `ctx` payloads are stringified instead of
   escalating to a 500).
6. **Use case.** The router calls a service with an `AsyncSession` and an explicit
   `tenant_id`. Services own the transaction boundary: they `flush()` to obtain
   identities, write the audit entry, publish domain events, and let the session
   dependency wrap everything in one commit.
7. **Audit + events.** `AuditService.record()` appends to the global hash chain.
   `EventBus` handlers enqueue background work and fan out to the WebSocket hub.
8. **Response.** `PageResponse[T]` for lists (one `meta` shape for the whole API),
   domain exceptions mapped by `OFMEError` handlers to RFC-shaped error bodies.

## CQRS

`app/cqrs/commands.py` defines a small in-process bus: commands are frozen
dataclasses with a handler that receives a session and a principal. The bus is
registered once at startup (`register_handlers()`), guarded so tests that import
the app repeatedly do not double-register.

Commands exist for operations that must be atomic across aggregates — device
enrolment, policy deployment, backup restore. Reads do **not** go through the
bus: routers call repositories or read services, which keeps the hot paths free
of indirection and the OpenAPI models explicit.

## Event-driven edges

* `app/core/events.py` — typed domain events (`DeviceRegistered`,
  `DeviceStatusChanged`, `PolicyDeployed`, `DriftDetected`, `TunnelStateChanged`,
  `BackupCompleted`, …) recorded in `domain_events` with a per-aggregate sequence
  number and hash chain, so the event log itself is tamper-evident.
* `app/api/ws.py` — the hub subscribes to the Redis channel `ofme:ws` and pushes
  `{"type": "event", "topic", "event", "data", "ts"}` frames to browsers. Because
  fan-out is Redis, any replica can serve any socket.
* `wire_event_forwarding()` connects the in-process bus to Redis at startup, so a
  worker that completes a backup notifies browsers connected to the API pods.

## Data layer

* SQLAlchemy 2.x async with `asyncpg`; Alembic uses the synchronous `psycopg` URL
  derived from `DATABASE_URL`.
* One `AsyncSession` per request (`app/db/session.py`), `expire_on_commit=False`
  to avoid implicit lazy loads after commit. Celery uses a per-task engine with
  `NullPool` (`app/workers/base.py`), because a pre-fork pool must not inherit
  sockets.
* All timestamps are timezone-aware UTC, generated in Python (`default=utcnow`)
  *and* declared with `server_default=func.now()`; the Python default prevents
  the post-UPDATE refresh that is illegal under asyncio.
* Enums are stored as `VARCHAR` with a `CHECK`-free `native_enum=False` mapping,
  which makes adding a value a code change instead of a migration dance.
* Tenant filtering is not a global filter hook: every repository method takes the
  `tenant_id` from the `UnitOfWork`, and integration tests assert that a second
  tenant sees nothing (`tests/test_api_tenant_isolation.py`).

See [DATABASE.md](DATABASE.md) for the tables, indexes and retention jobs.

## Networking desired state (DHCP and DNS)

`app/services/networking.py` owns the two networking aggregates. Both are
device-scoped, validated before they are stored, and audited like any other
configuration object:

* `DhcpScopeService` normalises the subnet (`ip_network(..., strict=False)`),
  rejects non-IPv4 and `/31`+ networks, verifies that pool bounds are usable
  unicast addresses inside the subnet, that the gateway is outside the dynamic
  pool, that DNS servers are valid IPs and that the domain name is a valid host
  name. Names and subnets are unique per device; deleting a scope soft-deletes
  its reservations in the same transaction.
* `DhcpReservationService` normalises MAC addresses to lower-case colon form,
  keeps the address inside the parent scope, forbids network/broadcast/gateway
  addresses, and enforces MAC- and IP-uniqueness within the scope.
* `DnsRecordService` validates per record type (A → IPv4, AAAA → IPv6, MX →
  priority, SRV → priority/weight/port, CNAME/MX/SRV/PTR/NS → host names),
  lower-cases and de-duplicates owner names, and enforces RFC 1034 CNAME
  exclusivity.

Uniqueness is also enforced by partial unique indexes (`WHERE deleted_at IS
NULL`) so a soft-deleted object does not block re-creation, and service-level
conflict checks produce `409` instead of relying on an `IntegrityError`. These
aggregates are currently control-plane only; pushing them into Kea/ISC and
Unbound is tracked as gaps G-27/G-28 in
[REQUIREMENTS_TRACEABILITY.md](REQUIREMENTS_TRACEABILITY.md).

## Delivery surfaces

| Surface | Location | Auth | Purpose |
|---|---|---|---|
| REST | `/api/v1` | JWT or API key | Console, automation, Terraform provider |
| OpenAPI 3.1 | `/api/v1/openapi.json`, `api/openapi.yaml` | same as REST | Generated from the app; never hand-edited |
| WebSocket | `/ws?token=…` | JWT or API key | Live fleet events |
| gRPC | `ofme.fleet.v1.FleetRegistry` | static `x-ofme-token` | Read-only inventory for reporting/SIEM |
| Agent API | `/api/v1/agent` | mTLS device certificate | Heartbeats, config fetch, command results |
| Metrics | `/metrics` | network policy | Prometheus scrape |

The gRPC facade is disabled by default (`GRPC_ENABLED=false`) and read-only on
purpose: writes stay on REST where the audit, approval and policy machinery
already lives.

## Scaling model

| Component | State | Scale by |
|---|---|---|
| `ofme-api` | none (JWT, no server session) | replicas / HPA on CPU |
| `ofme-worker` | none (task state in Redis + `jobs` table) | replicas; concurrency per pod |
| `ofme-beat` | one instance | Recreate strategy, single replica |
| PostgreSQL | all durable state | vertical first, then read replicas |
| Redis | broker, result backend, cache, pub/sub | managed cluster |
| S3/MinIO | backups, artefacts | managed bucket |

The API holds no sticky state, so the `Service` can round-robin freely; the only
socket state is the WebSocket connection itself, and it is stateless apart from
its Redis subscription.

## Why a modular monolith

* **Transactional correctness.** Policy deployment touches policies, deployments,
  devices, rules, audit and events. As separate services that would be a saga; in
  one process it is one transaction with a clear rollback.
* **Operational simplicity.** One image, one migration chain, one log schema.
* **Escape hatch.** `integrations/` and `domain/` have no ORM or HTTP imports, and
  the service layer already accepts explicit `tenant_id`/actor arguments, so a
  module can be extracted behind a queue or gRPC without changing its callers.

## Repository map

```
backend/app/
  api/          v1/endpoints/*.py, deps.py, ws.py
  cqrs/         bus.py, commands.py
  core/         config.py, security.py, events.py, exceptions.py, logging.py, pagination.py
  db/           base.py (mixins), session.py
  domain/       device.py, policy.py, topology.py
  grpc/         server.py, generated/
  integrations/ opnsense/, storage.py, git/, ldap.py, oidc.py, vault.py
  models/       identity, topology, config, policy, sdwan, ztp, operations, audit
  pki/          ca.py
  rbac/         permissions.py
  repositories/ base.py, devices.py, …
  schemas/      one module per API area
  services/     use cases listed above
  workers/      celery_app.py, dispatch.py, base.py, task modules
frontend/src/   pages, components, api, store, hooks, theme
plugin/os-fleet-agent/  OPNsense PHP plugin (src/, xml/, cli/, rc/)
```
