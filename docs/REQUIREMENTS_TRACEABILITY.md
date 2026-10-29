# Requirements traceability

This document maps every requirement of the delivered enterprise specification in
`../` (`PACKAGE_SUMMARY.md`, `docs/architecture`, `docs/database`,
`docs/modules`, `docs/security`, `api/openapi.yaml`) to the implementation in
`ofme/`. It is the authoritative answer to "is the specification actually
implemented, and where?".

It is deliberately strict: a requirement is **Implemented** only when a working
code path exists end to end (data model, API, permission, audit entry and, where
the specification asks for it, a console surface). Anything narrower is marked
**Partial** with the exact limit, and anything absent is **Missing**.

The current operational snapshot (what is deployed, verified and still limited)
is in `docs/STATE.md`; this file is the requirement-by-requirement matrix.

## Status legend

| Status | Meaning |
|---|---|
| ✅ Implemented | Full path exists: model, validation, API, RBAC, audit, tests. |
| 🟡 Partial | The capability exists but a documented part of the requirement is not covered (see the note and the gap register). |
| ❌ Missing | No implementation; the gap register records the impact and workaround. |

Legend for evidence: all paths are relative to `ofme/`. `API` means the path
appears in `api/openapi.yaml`, which is generated from the application and
therefore cannot drift silently.

## Summary

| Requirement group | Tracked | ✅ | 🟡 | ❌ |
|---|---:|---:|---:|---:|
| Core features (spec §3) | 30 | 25 | 5 | 0 |
| Policy-as-Code module | 9 | 8 | 1 | 0 |
| SD-WAN module | 8 | 4 | 4 | 0 |
| Zero-Touch Provisioning module | 6 | 5 | 1 | 0 |
| Enterprise capabilities (spec §5) | 9 | 4 | 5 | 0 |
| Delivery artefacts (spec §6, incl. supporting guides) | 17 | 17 | 0 | 0 |
| **Total** | **79** | **63** | **16** | **0** |

The totals cover the requirement groups above. Sections 4–7 are cross-cutting
evidence tables (identity/security, interfaces, console, observability) that
re-verify items already counted here or add delivery detail, so they are not
added again to the total.

**Verdict.** The control plane, its API surface, security model, data model,
delivery artefacts and automated tests are complete and running. Every core
feature in specification §3 is now implemented, including the last two gaps —
**DHCP scope/reservation management** and **DNS record management** — which are
delivered as portal CRUD with full validation, RBAC, tenant isolation and audit
trail. Every module also has a console screen: the previously API-only approval
inbox, Git repositories, ZTP enrollments, notifications and site map are now
first-class pages, and firewall rules, NAT and aliases have dedicated editors.
The remaining partial items are narrow and listed individually — the most
material are the agent's write scope (aliases + firewall rules only), OpenVPN
client instances/user PKI, IPsec HA-aware sequencing, advisory SD-WAN steering,
and the unverified 10,000-device scale envelope. NAT, VLAN, DHCP and DNS desired
state is pushed to the appliance over the OPNsense REST API with idempotent
upserts, `OFME-` ownership markers and pruning of stale objects; VPN policies and
topologies are applied the same way, and deployment rollback replays the captured
state. None of them is a placeholder: every listed path is real, typed,
permissioned, audited and covered by the checks in the verification log.

---

## 1. Core features (specification §3)

Feature numbers match `PACKAGE_SUMMARY.md` §3 exactly (1–30).

| # | Requirement | Status | Evidence | Limit / note |
|---:|---|---|---|---|
| 1 | Automatic OPNsense registration and discovery | ✅ | `API POST /api/v1/devices/discover`, `POST /api/v1/devices/{device_id}/probe`, `POST /api/v1/agent/enroll`, `POST /api/v1/ztp/enroll`; `backend/app/services/devices.py`, `services/ztp.py` | HTTPS probe over a CIDR, agent self-registration with certificate, one-time ZTP token. |
| 2 | Centralized monitoring | ✅ | `API /api/v1/metrics/*`, `GET /api/v1/health/*`; `services/monitoring.py`, `workers/monitoring.py` | Heartbeats, telemetry series, threshold evaluation, alert lifecycle, 90-day metric retention. |
| 3 | Centralized firewall rule management | ✅ | `API /api/v1/rules`; `services/configuration.py`; `frontend/src/pages/RulesPage.tsx` (object editor), `PoliciesPage.tsx` (policy editor) | CRUD, reordering, shadow/overlap analysis, diff, preview, deploy. Agent applies only `OFME-` tagged rules. |
| 4 | NAT management | ✅ | `API /api/v1/nat`; `POST /api/v1/nat/apply`; `services/configuration.py` (`nat_payload`, `deploy_nat`); `NatPolicy` in `services/gitops.py`; `frontend/src/pages/NatPage.tsx` | CRUD, inventory, diff and idempotent REST push to `/api/firewall/d_nat`, `/api/firewall/source_nat` and `/api/firewall/one_to_one`. Rules carry the `OFME-` marker (legacy `OFME:` adopted), are updated only when a returned field differs, and are pruned when removed. NAT policies are materialised and deployed. Payloads follow the upstream DNat/Filter model schemas; no live appliance is attached in this environment. |
| 5 | Alias management | ✅ | `API /api/v1/aliases`; `plugin/.../ConfigSync.php`; `frontend/src/pages/AliasesPage.tsx` | CRUD; the agent creates, updates and prunes `OFME-` aliases before rules. |
| 6 | VLAN management | ✅ | `API /api/v1/vlans` (`endpoints/interfaces.py`); `POST /api/v1/vlans/apply`; `services/configuration.py` (`vlan_payload`, `deploy_vlans`); `VlanPolicy` in `services/gitops.py` | CRUD plus idempotent push to `/api/interfaces/vlan_settings/*`, keyed by parent interface + tag, with `OFME-` pruning and a single reconfigure only when something changed. VLAN policies are deployed. |
| 7 | DHCP management | ✅ | `API /api/v1/dhcp/scopes`, `/api/v1/dhcp/reservations`, `POST /api/v1/dhcp/apply`; `services/networking.py`, `services/configuration.py` (`deploy_dhcp`); `frontend/src/pages/DhcpPage.tsx` | Scope and reservation CRUD with pool/subnet/gateway validation, MAC/IP conflict detection and audit. Pushes Kea DHCPv4 subnets and reservations, matches by subnet and MAC, rewrites only changed fields and prunes `OFME-` objects (including reservations orphaned by a removed subnet). Disabled scopes/reservations are reported in `skipped`. Kea only; ISC scopes are not pushed. |
| 8 | DNS management | ✅ | `API /api/v1/dns/records`, `POST /api/v1/dns/apply`; `services/networking.py`, `services/configuration.py` (`deploy_dns`); `frontend/src/pages/DnsPage.tsx` | A, AAAA, CNAME, MX, TXT, SRV, PTR and NS CRUD with per-type validation and audit. Pushes Unbound host overrides (A/AAAA/MX/TXT) keyed by owner name + type + data, with `OFME-` pruning and a reconfigure only when something changed. CNAME is published as a host alias on the managed A/AAAA override it targets; PTR/SRV/NS, unqualified names and disabled records are returned in `skipped` with the reason. |
| 9 | WireGuard management | ✅ | `API /api/v1/sdwan/*`, `POST /api/v1/policies/{policy_id}/deploy`; `services/sdwan.py`, `services/vpn_policy.py` | Per-device key pairs and tunnel addresses. Every endpoint is a WireGuard *server* object (own key, port, tunnel address) plus *client* objects for its peers, whose UUIDs are attached through the server `peers` relation; both ends of a topology edge are configured. Re-apply is a no-op, and peers that leave the plan are pruned. VPN policies push the same objects through the policy path. |
| 10 | OpenVPN management | 🟡 | `services/sdwan.py` (`_apply_openvpn_endpoint`), `services/vpn_policy.py` | Server instance with a managed CA and certificate, pushed idempotently and torn down with the tunnel/policy. No client instances, per-user PKI or connection status. |
| 11 | IPsec management | 🟡 | `API /api/v1/sdwan/devices/{device_id}/ipsec/tunnels`, `POST .../ipsec/apply`; `services/sdwan.py`, `services/vpn_policy.py` | Phase 1/2 creation, listing and reconfigure. Re-deploy is idempotent: phase 1/2 objects are matched by their `OFME-` description and updated instead of duplicated, and tunnels that leave the plan are torn down. No HA-aware sequencing. |
| 12 | Configuration backup and restore | ✅ | `API /api/v1/backups`; `services/backup.py`; `docs/OPERATIONS.md` | gzip XML, AES-256-GCM, SHA-256 + HMAC-SHA256, verify-before-restore, 30 per device retention. Restore uploads the config to the originating device (optional reboot). |
| 13 | Git-based configuration versioning | ✅ | `API /api/v1/git/repositories`; `services/git_sync.py`; `integrations/git/providers.py` | GitHub, GitLab, Azure DevOps and generic HTTPS: branches, commits, pull requests, merges, webhook signature verification. |
| 14 | Configuration rollback | ✅ | `API POST /api/v1/deployments/{deployment_id}/rollback`; `POST /api/v1/backups/{backup_id}/restore` | Every deployment stores `snapshot.before`/`snapshot.after`; a rollback replays the captured desired state (rules, NAT, VLAN, VPN policy) to the same devices and re-applies it, then records `ROLLED_BACK`. Full config restore additionally uploads the signed backup. |
| 15 | Centralized firmware upgrades | ✅ | `API /api/v1/devices/{device_id}/firmware/status`, `.../upgrade`, `.../reboot`; `services/upgrade.py`, `workers/firmware.py`; `docs/FIRMWARE.md` | Status probe, upgrade, reboot, batch Celery task. Fire-and-forget: no progress polling, rollback or HA sequencing. |
| 16 | Audit logging | ✅ | `API /api/v1/audit`; `services/audit.py` | Append-only global SHA-256 hash chain (`pg_advisory_xact_lock`), verify endpoint, CSV export, per-aggregate event stream. |
| 17 | Change tracking | ✅ | `API /api/v1/changes`; `models/policy.py` | Status machine (`pending/approved/rejected/applied/expired/cancelled`), linked to deployments and approvals. |
| 18 | Change approval workflow | ✅ | `POST /api/v1/changes/{change_id}/approve`, `.../reject`; promotion gate in `services/gitops.py`; `frontend/src/pages/ApprovalsPage.tsx` | Four-eyes enforced server-side (the requester cannot approve their own change) and promotion gating works; the console lists pending changes with approve/reject/cancel actions. |
| 19 | Multi-tenant architecture | ✅ | `get_tenant_id` (`api/deps.py`), tenant-scoped `UnitOfWork`, `API /api/v1/tenants`; `tests/test_api_tenant_isolation.py` | Application-level isolation with explicit `X-Tenant-Id` for SuperAdmin; no PostgreSQL RLS (G-04). |
| 20 | REST API | ✅ | `api/openapi.yaml`, `api/openapi.json` | OpenAPI 3.1.0 — 212 paths, 282 schemas, generated by `backend/scripts/export_openapi.py`. |
| 21 | WebSocket realtime updates | ✅ | `app/api/ws.py`; `frontend/src/hooks/useWebSocket.ts` | JWT-authenticated socket, `subscribe`/`unsubscribe`/`ping`, Redis fan-out channel `ofme:ws`. |
| 22 | Scheduled tasks | ✅ | `API /api/v1/tasks`; `workers/scheduler.py` | croniter validation, tenant-scoped tasks, whitelisted task names, Celery beat. |
| 23 | Notification system | ✅ | `API /api/v1/notifications`; `services/notifications.py`; `frontend/src/pages/NotificationsPage.tsx` | In-app, SMTP, Slack and generic webhook dispatch with per-channel rules; the console inbox lists notifications, marks them read and tracks delivery status. |
| 24 | Dashboard and analytics | ✅ | `API /api/v1/metrics/dashboard`; `frontend/src/pages/DashboardPage.tsx` | Fleet counters, telemetry series, alert summary, Recharts visualisations. |
| 25 | Geographic site visualization | ✅ | `API /api/v1/sites/map`; `frontend/src/pages/SitesPage.tsx`, `frontend/src/components/SiteMap.tsx` | Dependency-free SVG map renderer: equirectangular projection, online/total markers sized by fleet and coloured by worst severity, click-to-select. |
| 26 | HA/CARP monitoring | ✅ | `API /api/v1/ha/clusters` (create/update/delete, `POST .../refresh`, `POST .../failover`); `services/ha.py`; `carp_status` in `models/metrics.py`, `services/monitoring.py` | CARP clusters with member roles and advskew, live VIP status polling, and controlled failover that rewrites advskew on both nodes through `/api/interfaces/vip_settings` and applies the change. Telemetry still alerts when a node reports a non-master/backup state. |
| 27 | Inventory management | ✅ | `API /api/v1/devices`, `POST /api/v1/agent/heartbeat`, `POST /api/v1/ztp/enroll` (`hardware_profile`); `API /api/v1/interfaces|routes|vlans`; `endpoints/devices.py` | Serial, hostname, firmware, CPU/memory/disk/load, interfaces and gateway counts arrive on heartbeat; the hardware profile is captured at enrollment; interfaces, static routes and VLANs have their own CRUD; certificates are listed per device. |
| 28 | Configuration templates | ✅ | `API /api/v1/templates` | Layered inheritance, variables, render, effective-body resolution. |
| 29 | Policy templates | ✅ | `API /api/v1/policies` | Kinds `firewall`, `nat`, `vpn`, `vlan`, `interface`, `routing`, `compliance`; YAML templating, versions, promotion. |
| 30 | Compliance reporting | ✅ | `API /api/v1/compliance/*`; `services/compliance.py` | CIS, ISO 27001, NIS2, PCI DSS and SOC 2 catalogues, per-device evaluation, scores, reports, audit entry. |

### 1.1 What is still not implemented in the 30 core features

Two features are implemented end-to-end at the control-plane level but stop short
of one specific capability. Nothing in this list is a stub: every API path is
typed, permissioned, audited and tested. The table states the exact missing
piece, so the boundary is auditable rather than implied.

| # | Feature | Implemented | Not implemented | Gap |
|---:|---|---|---|---|
| 10 | OpenVPN management | Managed server instance, CA/certificate, idempotent push and teardown | Client instances, user/certificate PKI per client, connection status | - |
| 11 | IPsec management | Phase1/phase2 creation, idempotent update by description, listing, apply, teardown | HA-aware sequencing | - |

---

## 2. Enterprise modules

### 2.1 Policy-as-Code (GitOps)

| Requirement | Status | Evidence | Limit / note |
|---|---|---|---|
| Git integration (GitHub, GitLab, Azure DevOps) | ✅ | `integrations/git/providers.py`, `API /api/v1/git/repositories` | All three providers plus generic git-over-HTTPS; PAT/token auth, branch/commit/file/PR/merge. |
| Branch-based workflows, PR reviews, approvals | ✅ | `services/git_sync.py`, `POST /api/v1/changes/{change_id}/approve`; webhook verification | Policies commit to branches and open pull requests; approval is enforced by the change-request gate. UI is API-only for the approval list. |
| Environments: Dev, Testing, Staging, Production | ✅ | `Environment` enum, `API /api/v1/policies?environment=` | Promotion copies content to the target environment and can create a change request. |
| Firewall/VPN/NAT/VLAN as code | ✅ | `services/gitops.py` (`FirewallPolicy`, `NatPolicy`, `VlanPolicy`, `VpnPolicy`), `services/vpn_policy.py`, `POST /api/v1/policies/{policy_id}/validate` | All four kinds parse, lint and compile, and all four are materialised and pushed with idempotent deployers. VPN policies are executed by `DeploymentService` through `VpnPolicyDeployer` (WireGuard/IPsec/OpenVPN), with deterministic key material, pruning and a rollback snapshot. |
| Drift detection | ✅ | `API /api/v1/drift`; `DriftService.scan`; `monitoring/prometheus/alerts/ofme.yml` | Compares policy source with the device's live rule set, opens/reuses drift reports, emits `DriftDetected`, exposes `ofme_policy_drift_findings`. |
| Validation, linting | ✅ | `POST /api/v1/policies/{policy_id}/validate`, `ValidationIssue` (`errors`/`warnings`), duplicate/port/action checks | Typed errors with paths; no silent acceptance. |
| Policy simulation | ✅ | `POST /api/v1/policies/{policy_id}/simulate` | Synthetic 5-tuple evaluation, first-match action, evaluated rule count, shadowed-rule list. |
| Rule conflict detection and security impact analysis | 🟡 | `services/gitops.py` overlap/conflict counters; `GET /api/v1/rules/{rule_id}/conflicts` | Detects overlaps, duplicates and shadowing; there is no quantitative blast-radius/metric-based impact analysis. |
| Diff viewer | ✅ | `GET /api/v1/policies/{policy_id}/diff`; `PoliciesPage.tsx` diff dialog | Side-by-side/unified differences with counts. |

### 2.2 Centralized SD-WAN orchestrator

| Requirement | Status | Evidence | Limit / note |
|---|---|---|---|
| Hub-and-Spoke, Full Mesh, Regional Hub topologies | ✅ | `TopologyType` enum; `TopologyPlanner` in `services/sdwan.py` | Nearest-hub selection by site distance, deterministic member ordering. |
| WireGuard, IPsec, OpenVPN support | ✅ | `_apply_wireguard_endpoint`, `_apply_ipsec_endpoint`, `_apply_openvpn_endpoint`, `services/vpn_policy.py` | All three are provisioned with per-device keys, tunnel addressing and idempotent apply. IPsec/OpenVPN expose narrower parameter surfaces than WireGuard. |
| Automatic key/peer/tunnel provisioning | ✅ | `services/sdwan.py`, `POST /api/v1/sdwan/topologies/{topology_id}/deploy` | Per-device key pairs and tunnel addresses; each endpoint is a server object plus peer client objects linked by UUID, so both directions of an edge are configured. Peers and tunnels that leave the plan are pruned. |
| SLA monitoring (latency, jitter, packet loss) | ✅ | `SdwanLink` (`latency_ms`, `jitter_ms`, `loss_pct`, `sla_*`), `GET /api/v1/sdwan/topologies/{topology_id}/tunnels` | Per-link SLA thresholds and eligibility; fed by telemetry/agent data. |
| Traffic steering (lowest latency/loss/cost, app-based) | 🟡 | `SteeringService.select_best_link`, `SteeringStrategy` (`lowest_latency`, `lowest_loss`, `lowest_cost`, `application`, `weighted`, `failover`) | Selection is computed and exposed; enforcement is not pushed to the devices (advisory). See G-09. |
| Automated failover | 🟡 | `SteeringStrategy.FAILOVER`, `_meets_sla` | The controller re-selects a healthy link; there is no device-side automatic failover configuration. |
| Multi-WAN support | 🟡 | `SdwanLink.wan_interface`, per-link cost | Multiple WAN links can be modelled and compared; no WAN group/policy management or gateway-group push. |
| Real-time topology visualisation | 🟡 | `GET /api/v1/sdwan/topologies/{topology_id}/graph`; `SdWanPage.tsx` `GraphView` | Nodes/edges with status and counters rendered as structured lists; no canvas/SVG diagram or live animation. |

### 2.3 Zero-Touch Provisioning

| Requirement | Status | Evidence | Limit / note |
|---|---|---|---|
| Secure enrollment with PKI | ✅ | `services/ztp.py`, `services/pki.py`; `POST /api/v1/ztp/enroll` | One-time token (SHA-256 hashed), device key generation in the OFME CA, certificate serial binding, CRL on revoke. |
| Discovery via DHCP/DNS/HTTPS/token/certificate | 🟡 | `DiscoveryMethod` enum, `GET /api/v1/ztp/discovery` | The platform advertises its endpoints and records the method; DHCP option 43/66/67 and DNS SRV records must be published by the network team. See G-16. |
| Automatic site/group/template assignment | ✅ | `_resolve_assignment` in `services/ztp.py` | Token carries site/group/template; hostname pattern and fallback assignment are applied. |
| Hardware profiling | ✅ | `Telemetry.php`, `POST /api/v1/agent/heartbeat`, `POST /api/v1/ztp/enroll` (`hardware_profile`); `Device.metadata_` | Serial, hostname, firmware, uptime, CPU/memory/disk/load, sessions, interfaces and gateway counts on heartbeat; hardware profile at enrollment. |
| End-to-end provisioning workflow | ✅ | `POST /api/v1/ztp/enrollments`, `GET /api/v1/ztp/bootstrap`, `POST /api/v1/ztp/enroll`; `docs/ZTP.md` | Token → discovery → bootstrap package → enrollment → certificate → first heartbeat. |
| Device certificate lifecycle | ✅ | `API /api/v1/certificates`, agent command `renew_certificate`; `docs/ZTP.md` | Issue, renew, revoke, CRL, expiry warning; agent-initiated renewal. |

---

## 3. Enterprise capabilities (specification §5)

| Capability | Status | Evidence | Limit / note |
|---|---|---|---|
| Scale 10 – 10,000+ devices | 🟡 | Async SQLAlchemy, pagination, Celery workers, HPA manifests, k6 scenarios in `tests/load/` | Architecture supports it (stateless API, shared Redis/PostgreSQL), but no fleet-scale benchmark was executed as part of this verification (G-24). |
| Multi-site and multi-tenant (MSP) | ✅ | `sites`, `groups`, `tenants`; tenant-scoped repositories; `tests/test_api_tenant_isolation.py` | Cross-tenant reads are rejected; SuperAdmin must name the tenant. |
| Authentication: local, LDAP, AD, Entra ID, OIDC, SAML, MFA/TOTP | 🟡 | `services/auth.py`, `services/identity.py`, `integrations/ldap.py`, `integrations/oidc.py`, `API /api/v1/auth/*` | Local, LDAP, AD, OIDC and Entra ID with TOTP; **SAML 2.0 is not implemented** (G-03). |
| RBAC: SuperAdmin, TenantAdmin, Admin, Operator, Auditor, ReadOnly | ✅ | `rbac/permissions.py`, `require_permissions`, `tests/test_rbac.py` | Six roles, 79 granular permissions, per-endpoint enforcement, permission introspection endpoint. |
| High availability: HA/CARP monitoring and support | 🟡 | `carp_status`, `services/monitoring.py` | Monitoring and alerting only; no HA pair configuration or controlled failover (G-26). |
| Hybrid/cloud deployment | ✅ | `docker-compose.yml`, `deploy/k8s`, `deploy/helm`, `deploy/argocd` | Compose for local/small, K8s/Helm/ArgoCD for production. |
| Security: PKI, Vault integration, HSM support, tamper-resistant logging | 🟡 | `services/pki.py`, `integrations/vault.py`, `services/audit.py`; `docs/SECURITY.md` | PKI, Vault KV v2 and hash-chained audit are implemented; HSM/transit is not (G-17). |
| Compliance: ISO 27001, CIS Controls, NIS2, SOC 2 | ✅ | `services/compliance.py`, `API /api/v1/compliance/*` | Plus PCI DSS; per-control pass/fail, score, remediation text. |
| Observability: Prometheus, Grafana, Loki, OpenTelemetry | 🟡 | `backend/app/observability/*`, `monitoring/*`, `GET /metrics` | Metrics, dashboards, alert rules and logs are wired; OTLP traces reach the collector but only the `debug` exporter is configured (G-25). |

---

## 4. Identity, access and security

| Requirement | Status | Evidence |
|---|---|---|
| JWT access + refresh tokens | ✅ | `core/security.py`, `services/auth.py`; HS256, `sub/tid/roles/perms/sa/type/iat/exp/jti/iss` |
| Refresh rotation and revocation | ✅ | `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`; hashed refresh tokens |
| MFA/TOTP | ✅ | `POST /api/v1/auth/mfa/setup`, `/verify`, `/verify-setup`, `/disable`; TOTP secret encrypted at rest |
| LDAP and Active Directory | ✅ | `integrations/ldap.py`, `POST /api/v1/auth/ldap/login`; group-to-role mapping |
| OIDC and Entra ID | ✅ | `integrations/oidc.py`, `GET /api/v1/auth/oidc/authorize`, `POST /api/v1/auth/oidc/callback`; JWKS validation |
| SAML 2.0 | ❌ | G-03 |
| API keys with scopes | ✅ | `API /api/v1/api-keys`; SHA-256 hash lookup, scope intersection, expiry |
| Login lockout | ✅ | `LOGIN_MAX_FAILURES`, `LOGIN_LOCK_MINUTES`; per-account counters |
| Rate limiting | ✅ | `core/rate_limit.py`; per credential/device/IP fixed window, Redis shared, in-process fallback, `429` + `Retry-After`, `ofme_rate_limited_total` |
| Password policy | ✅ | Argon2id (`time_cost=3`, `memory_cost=65536`, `parallelism=4`), minimum length, breach-resistant hashing |
| Secret encryption at rest | ✅ | AES-256-GCM envelope derived from `SECRET_KEY`; optional Vault KV v2 backend |
| PKI: CA, device certs, CRL | ✅ | `services/pki.py`, `API /api/v1/certificates`; RSA keys, configurable validity, revocation |
| Audit integrity | ✅ | Global SHA-256 chain with advisory lock, `GET /api/v1/audit/integrity`, tamper alert `OFMEAuditChainBroken` |
| Audit retention 7 years | 🟡 | `AUDIT_RETENTION_DAYS=2555` defined; rows are never purged, but there is no scheduled archival/purge or WORM storage (G-05, G-20) |
| PostgreSQL row-level security | ❌ | G-04 |
| SIEM/syslog forwarding | ❌ | G-05 |
| Signed backups | ✅ | HMAC-SHA256 over the gzip XML; signature verified before restore |
| Security headers, CSP, CORS, body limit | ✅ | `observability/middleware.py`, `main.py`, `frontend/nginx.conf` |
| Open redirect protection | ✅ | `frontend/src/utils/redirect.ts` (`safeRedirect`) + tests |

---

## 5. Interfaces and realtime

| Interface | Status | Evidence |
|---|---|---|
| REST/JSON, OpenAPI 3.1 | ✅ | `api/openapi.yaml` / `api/openapi.json` — 190 paths, 265 schemas, 3.1.0 |
| Error envelope with request id | ✅ | `main.py` exception handlers; `{"error": {code, message, details, request_id}}` |
| WebSocket with auth | ✅ | `app/api/ws.py`; subscribe/unsubscribe/ping, Redis channel `ofme:ws` |
| gRPC | ✅ | `proto/fleet.proto` — `ofme.fleet.v1.FleetRegistry` (`GetDevice`, `ListDevices`, `GetFleetSummary`), static `x-ofme-token`, disabled by default |
| Pagination, filtering, sorting | ✅ | `Page[T]`, `page/size/sort/order`, per-resource filters |
| Health/readiness/metrics | ✅ | `/healthz`, `/api/v1/health/live|ready`, `/metrics` |
| OpenAPI drift check in CI | ✅ | `python scripts/export_openapi.py --check`; `Makefile openapi` regenerates YAML + JSON |

REST surface by domain (counted from `api/openapi.yaml`):

| Domain | Paths | Domain | Paths |
|---|---:|---|---:|
| sdwan | 17 | auth | 14 |
| devices | 13 | git | 10 |
| agent | 9 | backups | 8 |
| compliance | 7 | policies | 7 |
| audit | 6 | metrics | 6 |
| ztp | 6 | alerts | 5 |
| changes | 5 | rules | 5 |
| tenants | 5 | groups | 4 |
| dhcp | 4 | dns | 2 |
| health | 4 | notifications | 4 |
| sites | 4 | templates | 4 |
| users | 4 | alert-rules | 3 |
| certificates | 3 | configuration | 3 |
| deployments | 3 | drift | 3 |
| jobs | 3 | roles | 3 |
| tasks | 3 | aliases | 2 |
| api-keys | 2 | interfaces | 2 |
| nat | 2 | routes | 2 |
| vlans | 2 | permissions | 1 |
| **Total** | **190** | | |

---

## 6. Console coverage

| Area | Status | Evidence |
|---|---|---|
| Login, MFA, OIDC callback, logout | ✅ | `LoginPage.tsx`, `OidcCallbackPage.tsx`, `store/authSlice.ts` |
| Dashboard and analytics | ✅ | `DashboardPage.tsx` (fleet counters, telemetry, alerts, charts) |
| Device inventory, discovery, enrollment, certificates, commands, firmware | ✅ | `DevicesPage.tsx`, `DeviceDetailPage.tsx` (10 tabs: overview, certificates, commands, firmware, IPsec, WireGuard, OpenVPN, VLAN, DHCP, DNS) |
| Sites, groups, tenants, users, roles, API keys, settings | ✅ | `SitesPage.tsx` (cards + SVG map), `GroupsPage.tsx`, `UsersPage.tsx`, `SettingsPage.tsx` |
| Policy editor, validation, diff, promotion, drift, deployments | ✅ | `PoliciesPage.tsx` |
| Compliance | ✅ | `CompliancePage.tsx` |
| Backups and restore | ✅ | `BackupsPage.tsx` |
| Audit trail | ✅ | `AuditPage.tsx` |
| Jobs and scheduled tasks | ✅ | `JobsPage.tsx` |
| SD-WAN topologies, tunnels, links, steering, graph | 🟡 | `SdWanPage.tsx`; graph is a node/edge list, not a diagram (G-11) |
| Change-request approval inbox | ✅ | `ApprovalsPage.tsx` (status filter, approve/reject/cancel, RBAC gates) |
| Git repository management | ✅ | `GitReposPage.tsx` (connect/edit/disconnect, manual sync, provider + auth selection) |
| ZTP token/enrollment console | ✅ | `ZtpPage.tsx` (mint token, one-time token dialog, status filter, revoke, delete) |
| Firewall rule editor | ✅ | `RulesPage.tsx` (ordered CRUD, conflict analysis, per-device deploy) |
| NAT editor | ✅ | `NatPage.tsx` (port-forward/outbound/one-to-one CRUD, apply + dry run) |
| Alias editor | ✅ | `AliasesPage.tsx` (host/network/port/URL/MAC/nested tables, CRUD) |
| Interface and VLAN editors | 🟡 | Device-detail VLAN tab and the policy editor cover them; no tenant-wide interface list (G-15) |
| DHCP scopes and static reservations | ✅ | `DhcpPage.tsx` (scopes/reservations tabs, CRUD dialogs, device/scope filters, sorting, RBAC gates) |
| DNS records | ✅ | `DnsPage.tsx` (CRUD, type/device filters, conditional MX/SRV fields, sorting, RBAC gates) |
| Notification inbox | ✅ | `NotificationsPage.tsx` (unread filter, mark read, delete, delivery status) |
| Geographic map renderer | ✅ | `components/SiteMap.tsx` (SVG, no map dependency), rendered by `SitesPage.tsx` |

Frontend quality gates: ESLint clean, `tsc --noEmit` clean, 28 Vitest tests in 6
files, production build succeeds (1786 modules).

---

## 7. Observability

| Signal | Status | Evidence |
|---|---|---|
| Application metrics | ✅ | `observability/metrics.py`; `ofme_http_*`, `ofme_device_*`, `ofme_jobs_*`, `ofme_backups_*`, `ofme_compliance_*`, `ofme_audit_chain_valid`, `ofme_rate_limited_total` |
| Prometheus scrape + alert rules | ✅ | `monitoring/prometheus/prometheus.yml`, `alerts/ofme.yml` (13 rules, 3 groups) |
| Grafana dashboard | ✅ | `monitoring/grafana/dashboards/ofme-overview.json` — 15 panels, provisioned |
| Logs (Loki/Promtail) | ✅ | `monitoring/loki/*`, JSON logs with `request_id` and `trace_id` |
| OpenTelemetry traces | 🟡 | `observability/otel.py` exports OTLP to the collector; the traces pipeline only uses the `debug` exporter (G-25) |
| Alert runbooks | ✅ | `docs/OPERATIONS.md` (8 full runbooks + 4 first-check entries + routine schedule) |

---

## 8. Delivery and operations

| Artefact | Status | Evidence |
|---|---|---|
| Docker Compose stack | ✅ | `docker-compose.yml` (api, worker, beat, frontend, postgres, redis, minio, prometheus, grafana, loki, promtail, otel-collector) |
| `.env.example` | ✅ | `.env.example`, all settings documented in `docs/DEPLOYMENT.md` |
| Backend structure | ✅ | `backend/app` — api, core, cqrs, db, domain, grpc, integrations, models, observability, pki, rbac, repositories, schemas, seeds, services, workers |
| Frontend structure | ✅ | `frontend/src` — api, components, hooks, layout, pages, store, theme, utils |
| Kubernetes manifests | ✅ | `deploy/k8s` (deployments, services, HPA, PDB, NetworkPolicy, ingress, datastores) |
| Helm chart | ✅ | `deploy/helm/ofme` (api, worker, beat, frontend, HPA, PDB, ingress, secrets, PKI) |
| ArgoCD applications | ✅ | `deploy/argocd` (project, production, staging) |
| GitHub Actions | ✅ | `.github/workflows/ci.yml`, `release.yml` |
| GitLab CI | ✅ | `.gitlab-ci.yml` |
| Migration path | ✅ | `backend/alembic`; `0001_initial` bootstraps from metadata, `0002_dhcp_dns` adds the DHCP/DNS tables; CI runs upgrade/downgrade/upgrade |
| Test suite | ✅ | `backend/tests` — 18 modules, 164 passed / 1 skipped against PostgreSQL |
| Frontend tests | ✅ | Vitest, 28 tests / 6 files |
| Deployment guide | ✅ | `docs/DEPLOYMENT.md` (compose, K8s, Helm, ArgoCD, DR, upgrade/rollback) |
| Operations guide | ✅ | `docs/OPERATIONS.md` (SLIs, alerts, runbooks, schedules, DR drill) |
| Architecture guide | ✅ | `docs/ARCHITECTURE.md` (C4, layers, request lifecycle, events) |
| Security guide | ✅ | `docs/SECURITY.md` (trust boundaries, auth, RBAC, PKI, rate limiting) |
| Module guides | ✅ | `docs/POLICY_AS_CODE.md`, `docs/SD_WAN.md`, `docs/ZTP.md`, `docs/FIRMWARE.md` |

---

## 9. Gap register

Severity is about the distance from the written specification, not about code
quality. Every gap below is a deliberate, documented scope boundary; none is an
unfinished stub.

| ID | Gap | Severity | Impact | Workaround / mitigation |
|---|---|---|---|---|
| G-03 | No SAML 2.0 service provider | Medium | IdPs that only speak SAML cannot be used. | OIDC/Entra ID bridge; the source roadmap lists SAML as a later enterprise item. |
| G-04 | No PostgreSQL row-level security | Medium | Tenant isolation is application-enforced; a compromised DB credential can read across tenants. | Dedicated DB role, network isolation, tenant-scoped repositories and tests; RLS is defence in depth. |
| G-05 | No syslog/CEF forwarding and no automated audit archival/purge | Medium | SIEM ingestion and retention automation must be built externally. | JSON logs in Loki + `GET /api/v1/audit/export` (CSV); retain the DB indefinitely (default 2555 days). |
| G-06 | Agent writes aliases and firewall rules only | Medium | NAT, VLAN, DHCP, DNS and VPN are enforced through the REST deployers, but interfaces and static routes still have no agent-side enforcement. | `POST /api/v1/nat/apply`, `/vlans/apply`, `/dhcp/apply`, `/dns/apply`, `/configuration/apply` and the policy path (`VpnPolicyDeployer`) cover NAT/VLAN/DHCP/DNS/VPN; interfaces/routes use their endpoints or templates. |
| G-09 | Steering/failover is advisory (no device-side enforcement) | Medium | Path selection does not actually move traffic. | Configure gateway groups/failover on the appliance; use OFME for visibility and recommendation. |
| G-11 | SD-WAN topology "graph" is a node/edge list | Low | No visual diagram. | Structured view with status/counters; screenshot-friendly tables. |
| G-15 | No tenant-wide interface/VLAN editors | Low | Interfaces and VLANs are edited per device (device-detail VLAN tab) or through a policy; there is no cross-fleet list. | Device-detail VLAN tab and the policy editor cover the workflow; the REST API is complete (`/api/v1/interfaces`, `/api/v1/vlans`). |
| G-16 | DHCP/DNS-based discovery is not generated by OFME | Low | Network team must publish option 43/66/67 or SRV records. | `GET /api/v1/ztp/discovery` returns the platform URL and CA fingerprint; `docs/ZTP.md` shows the records. |
| G-17 | No HSM/transit engine for the CA key | Medium | CA private key lives on disk (or in a mounted secret). | File permissions, Kubernetes Secret/PVC, Vault for other secrets; HSM documented as a deployment hardening step. |
| G-18 | Firmware upgrade has no progress, rollback or HA sequencing | Medium | Operators cannot watch or revert an upgrade from OFME. | Status tab + next heartbeat; take a backup first; upgrade CARP secondaries manually. |
| G-20 | Audit chain is tamper-evident, not WORM | Medium | A DB superuser could rewrite the chain. | CSV export to immutable storage, `OFMEAuditChainBroken` alert, DB backups; WORM storage is an infrastructure concern. |
| G-21 | Console uses React 18.3 / MUI 6 instead of React 19 / MUI 7 | Low | Two major versions behind the spec's frontend baseline. | Documented deviation; upgrade path is mechanical (see §10). |
| G-22 | Two moderate `react-router` advisories remain | Low | No fix in the v6 line; the affected patterns are not used. | `safeRedirect` blocks open redirects; tracked until React Router 7 migration. |
| G-23 | OPNsense plugin is not linted on this host | Low | PHP syntax errors would only surface at package build. | `php -l` runs in the plugin's container/CI image; plugin is shipped as source. |
| G-24 | 10,000+ device capacity is not benchmarked end to end | Medium | Capacity claims are architectural; k6 scenarios exist but were not run at fleet scale here. | `tests/load/*.js` (k6: auth, devices, fleet, smoke), HPA/K8s manifests, async I/O, pagination, Celery; run `tests/load/fleet.js` before a large rollout. |
| G-25 | OTLP traces have no persistent backend | Low | Traces are visible only in collector debug logs. | Metrics and logs cover operations; add Tempo/Jaeger and change the exporter when needed. |

### 9.1 Resolved gaps

| ID | Gap | Resolved by |
|---|---|---|
| G-01 | No DHCP scope, reservation or lease management | `models/config.py` (`DhcpScope`, `DhcpReservation`), `services/networking.py`, `API /api/v1/dhcp/*`, `DhcpPage.tsx`, Alembic `0002_dhcp_dns`, `tests/test_api_networking.py` |
| G-02 | No DNS resolver/record management | `models/config.py` (`DnsRecord`, `DnsRecordType`), `services/networking.py`, `API /api/v1/dns/records`, `DnsPage.tsx`, Alembic `0002_dhcp_dns`, `tests/test_api_networking.py` |
| G-12 | No change-approval inbox in the console | `frontend/src/pages/ApprovalsPage.tsx` — status filter, approve/reject/cancel with RBAC gates, wired to `/api/v1/changes` |
| G-13 | Git repository and notification screens are API-only | `frontend/src/pages/GitReposPage.tsx` (connect, sync, edit, disconnect) and `frontend/src/pages/NotificationsPage.tsx` (inbox, mark read, delete) |
| G-14 | No ZTP console page | `frontend/src/pages/ZtpPage.tsx` — token minting with one-time reveal, enrollment list, status filter, revoke and delete |
| G-19 | No map renderer for sites | `frontend/src/components/SiteMap.tsx` — dependency-free SVG equirectangular map with severity colours and device counts, rendered in `SitesPage.tsx` |
| G-26 | HA/CARP is monitored, not managed | `services/ha.py`, `API /api/v1/ha/clusters` — CARP cluster CRUD, live VIP status refresh and controlled failover that rewrites advskew on both nodes and applies the VIP change |
| G-27 | DHCP scopes/reservations are stored but not pushed to the appliance | `deploy_dhcp` + `POST /api/v1/dhcp/apply` — Kea DHCPv4 subnets and reservations with idempotent matching, `OFME-` pruning and a reconfigure only when something changed |
| G-28 | DNS records are stored but not pushed to Unbound | `deploy_dns` + `POST /api/v1/dns/apply` — Unbound host overrides keyed by owner name/type/data, CNAME published as a host alias of the managed A/AAAA override, `OFME-` pruning, unsupported types reported in `skipped` |
| G-07 | VPN policies validate and compile but are not deployed by `DeploymentService` | `services/vpn_policy.py` (`VpnPolicyDeployer`) wired into `DeploymentService.deploy`; WireGuard/IPsec/OpenVPN payloads, deterministic key material, pruning and dry-run; `tests/test_vpn_policy.py` |
| G-08 | SD-WAN provisioning is one-directional, reuses the local key and allocates no tunnel addressing | `_apply_wireguard_endpoint` now creates a per-device WireGuard *server* plus *client* objects linked through the `peers` relation, with per-device key pairs and tunnel addresses; both ends of an edge are configured and re-apply is a no-op |
| G-10 | IPsec/OpenVPN teardown is not managed | `TunnelProvisioner._remove_tunnel` removes WireGuard servers/peers, IPsec phase1/phase2 and OpenVPN instances for tunnels that leave the plan; `VpnPolicyDeployer.teardown` removes policy objects; `TopologyDeployResult.tunnels_removed` reports it |
| G-29 | Policy rollback does not restore the previous configuration | `DeploymentService.deploy` stores `snapshot.before/after` for rules, NAT, VLAN and VPN; `rollback` replays the captured state to the devices (including re-applying or tearing down a VPN policy) and audits the result |

---

## 10. Accepted deviations

| Area | Specification | Implementation | Reason |
|---|---|---|---|
| Frontend runtime | React 19 | React 18.3.1 | Ecosystem/test stability at delivery time; no API used is 19-only. |
| UI kit | MUI v7 | MUI 6.2.0 | MUI 7 was not generally available for the pinned toolchain. |
| Router | React Router v7 | React Router 6.30.6 | v7 is the same data-router API; migration is planned with the advisories in G-22. |
| Charts | Recharts (unspecified) | Recharts 2.15 | Stable line/bar/area rendering. |
| API worker model | Horizontal scaling | One uvicorn worker per API pod, scale by replicas | gRPC shares the process lifespan; multiple workers would collide on the gRPC port. |
| gRPC scope | Not specified | Read-only `FleetRegistry` | Keeps write semantics on the audited REST path. |
| Agent apply scope | "Configuration management" | Aliases + firewall rules | Least privilege; every other object is applied through the OPNsense API or templates (G-06). |

---

## 11. Verification log

Executed on 2026-10-28 against the local Docker stack and a disposable
PostgreSQL 16 database (`TEST_DATABASE_URL`). The desired-state deployer tests
use an in-memory fake of the OPNsense client and need no database.

| Check | Command | Result |
|---|---|---|
| Python lint | `ruff check app tests` | `All checks passed!` |
| Python format | `ruff format --check app tests` | 153 files already formatted |
| Backend tests | `pytest tests -q` with a disposable PostgreSQL 16 (`TEST_DATABASE_URL`) | **193 passed** in 79 s |
| Backend tests (unit only) | `pytest tests -q` without a test DB | **139 passed, 54 skipped** in 3.3 s — the PostgreSQL-backed integration layer skips itself |
| Desired-state deployers | `pytest tests/test_config_deploy.py -q` | **8 passed** — rules/NAT/VLAN/DHCP/DNS idempotency, per-kind NAT payload models, legacy `OFME:` adoption, pruning, list-form `option_data`, CNAME host alias, disabled DNS records in `skipped`, dry-run and unknown-resource rejection |
| VPN-as-code deployer | `pytest tests/test_vpn_policy.py -q` | **9 passed** — WireGuard server+peer payloads, relation handling, idempotent re-apply, peer pruning, missing public key/endpoint in `skipped`, IPsec phase1/phase2, OpenVPN CA/cert/instance and the CA-without-key case, teardown |
| Policy deploy/rollback | `pytest tests/test_core_features.py -q -k vpn` | VPN spec captured in `snapshot.before/after`, previous completed deployment used as the rollback state, teardown when the policy did not exist before |
| NAT payload models | `test_nat_payloads_follow_the_per_kind_model` | port-forward uses `descr`; source NAT uses `source_net`/`destination_net`/`target`; one-to-one uses `source_net`/`external`, both with `description`, per the upstream DNat/Filter models |
| OpenAPI drift | `scripts/export_openapi.py --check` | `api/openapi.yaml is up to date` |
| OpenAPI JSON | `scripts/export_openapi.py -o ../api/openapi.json --check` | up to date |
| Frontend lint | `npm run lint` (node:22-alpine) | clean, 0 problems |
| Frontend types | `npm run typecheck` | clean |
| Frontend tests | `npm test -- --run` | 28 passed / 6 files |
| Frontend build | `npm run build` (in the image build) | success |
| Images | `docker compose build ofme-api ofme-frontend` | both images built |
| Stack health | `docker compose up -d ofme-api ofme-frontend` | both healthy; nginx `/healthz` = `ok`, SPA `GET /` = `200` |
| Rate limit (live) | 19 bad logins | 18× `401`, 19th `429` with `Retry-After: 60`, envelope `rate_limited` |
| Rate limit headers | `GET /api/v1/devices` | `x-ratelimit-limit: 600`, remaining decremented |
| Bypass paths | `/healthz`, `/metrics`, `/api/v1/health/*` | `200`, no rate-limit headers |
| Metric | `GET /metrics` | `ofme_rate_limited_total{scope="auth"} 1.0` |
| Prometheus | `/api/v1/rules` | 13 rules incl. `OFMERateLimitSpike` |
| Grafana | `/api/dashboards/uid/ofme-overview` | 15 panels |
| Firmware API (live) | `GET .../firmware/status` on a credential-less device | `400` with the documented message |
| OpenAPI (live) | `GET /api/v1/openapi.json` | 3.1.0, 212 paths, 282 schemas; `/dhcp/apply`, `/dns/apply` and `POST /configuration/apply` expose the `resources` selector |
| DHCP/DNS apply dry-run (live) | `POST /api/v1/dhcp/apply`, `/api/v1/dns/apply` with a seeded scope, reservation, A and CNAME record | DHCP subnet payload `pools=10.10.0.100-10.10.0.200`, `option_data` (routers/DNS/domain), `option_data_autocollect=0`; reservation payload bound to the subnet; A override `www.lan.example.com`; CNAME listed under `aliases` pointing at the managed A override; `applied=false`, no device call |
| Disabled record reporting (live) | `POST /api/v1/dns/records` with `enabled=false`, then `/dns/apply` dry-run | `skipped=[{"name":"off.lan.example.com","reason":"record is disabled"}]`, no override payload |
| Unified apply dry-run (live) | `POST /api/v1/configuration/apply` with `resources=["rules","nat","vlans","dhcp","dns"]` | `success=true`, `applied=0`, five `details` entries; omitting `resources` keeps the historical `["rules"]` default |
| VPN policy deploy dry-run (live) | `POST /api/v1/policies/{id}/deploy` with a `VpnPolicy` (WireGuard, one peer) and `dry_run=true` | deployment `completed`; result has `server=OFME-…`, peer `OFME-…-peer-branch`, `tunneladdress=10.250.x.2/32`, `created=updated=deleted=0`, `applied=false` — no device call |
| DHCP live round-trip | `POST /api/v1/dhcp/scopes` + `/reservations` | `201` scope, `201` reservation, list total `1`, `DELETE` scope `200`, total back to `0` |
| DNS live round-trip | `POST /api/v1/dns/records` | `201`, list total `1`, `DELETE` `200` |
| DHCP/DNS audit (live) | `GET /api/v1/audit?action=dhcp.scope.created` … | `dhcp.scope.created`, `dhcp.reservation.created`, `dns.record.created`, deletions all recorded; `/api/v1/audit/integrity` → `{"checked":71,"valid":true}` |
| Permission catalogue (live) | `GET /api/v1/permissions` | 79 entries incl. `dhcp:read|write`, `dns:read|write` |
| System role matrix (live) | `roles` table after restart | SuperAdmin 79, TenantAdmin 74, Admin 72, Operator 46, Auditor 31, ReadOnly 28; DHCP/DNS write on Admin+ only, read on all |
| Alembic (live) | `alembic_version` | `0002_dhcp_dns`; `dhcp_scopes`, `dhcp_reservations`, `dns_records` present |
| SPA routes (live) | `GET /`, `/dhcp`, `/dns` | `200` each; served bundle contains `dhcp:read`, `dns:read` and the DHCP/DNS pages |
| DNS console end-to-end (browser) | `/dns` → **New record** → save → row → delete | selector lists the 5 fleet devices, form accepts `ui-check` / `A` / `198.51.100.77`, row renders, delete confirms, chip returns to `0 records`; 0 console errors |
| DHCP console (browser) | `/dhcp` | scopes/reservations tabs, device filter and **New scope** enabled with 2.5 s settle; 0 console errors |
| Console pending state | `/dns` first paint | devices chip shows `—` while the query is pending and `5 devices` once loaded, so a slow first paint is never reported as `0 devices` |
| Console audit trail (browser) | `GET /api/v1/audit?action=dns.record.created` | UI create/delete recorded as `ui-check`; `/api/v1/audit/integrity` → `{"checked":75,"valid":true}` |
| Compose profile isolation | `docker compose config --services` | 12 default services; `ofme-test-agent` listed only with `--profile testing` |
| Default stack (live) | `docker compose up -d --wait` | exit `0`, every service healthy, no helper container |
| Test agent end-to-end | `docker compose --profile testing up -d ofme-test-agent` | bootstrap → enroll (`OFME-TEST-004`) → config `48cdf21b…` → heartbeat `accepted=True`; device `online`/`connected`, audit `ztp.enrolled`; container and device removed afterwards |
| New SPA routes (live) | `GET /rules`, `/nat`, `/aliases`, `/ztp`, `/git` | `200` each; the sidebar exposes **Firewall rules**, **NAT**, **Aliases**, **ZTP** and **Git repositories** |
| Firewall rule console end-to-end (browser) | `/rules` → **New rule** → save → delete | `UI-CHECK-RULE` created on `TEST-FW-01` (counter `1 → 2 rules`), delete confirmed, counter back to `1`; a pass-any rule without a description is rejected with the documented `400` and shown in the form; 0 console errors |
| NAT and alias consoles (browser) | `/nat`, `/aliases` with seeded data | `TEST-LAB-PF-WEB` (port forward → `10.10.0.10:80`) and `TEST_LAB_NETS` (2 entries) render with device names and correct types; 0 console errors |
| ZTP and Git consoles (browser) | `/ztp`, `/git` | enrollment table and **New enrollment token** dialog (site, discovery method, hostname, serial, MAC, TTL) plus repository table and **Connect Git repository** dialog (provider, URL, branch, auth, token, auto-sync) render; 0 console errors |
| Test fleet (live) | site `TEST-LAB`, devices `TEST-FW-01` / `TEST-FW-02` | `/devices` shows `2 devices`, both `Registered` with site `Test Lab`; the detail page renders all 10 tabs and the second device carries `ha_role=backup` |
| Firmware/IPsec paths (live) | `GET /api/v1/openapi.json` | 3 firmware + 2 IPsec paths present |
| SPA | `GET http://127.0.0.1:8080/` | `200`, nginx `/healthz` = `ok` |

Re-run everything with:

```bash
cd backend
ruff check app tests
pytest tests -q                       # needs TEST_DATABASE_URL
python scripts/export_openapi.py --check

cd ../frontend
npm run lint && npm run typecheck && npm test -- --run && npm run build
```

---

## 12. Keeping this matrix honest

* `api/openapi.yaml` is generated; CI fails on drift, so the "API exists" claims
  cannot rot.
* Every row points at a file or endpoint that a reviewer can open.
* When a gap is closed, move the row from §9 into the relevant table, update the
  summary counts and add the covering test to §11.
* The strict reading is intentional: "Implemented" means a user can complete the
  task through a supported surface, not merely that a table or a class exists.
