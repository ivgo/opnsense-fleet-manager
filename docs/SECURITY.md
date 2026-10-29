# Security

OFME is a control plane for network security devices: a compromise of the
platform is a compromise of every managed firewall. This document describes what
the implementation actually enforces, where the trust boundaries are, and which
settings must change before an installation is exposed to the internet.

## Trust boundaries

```
browser ──TLS──► ingress ──► ofme-frontend (nginx, static SPA)
                    │
                    └─/api, /ws──► ofme-api ──► PostgreSQL
                                     ├──────► Redis (broker, cache, pub/sub)
                                     ├──────► S3 / MinIO (backups)
                                     └──────► OPNsense REST API (devices)

OPNsense + os-fleet-agent ──mTLS──► ingress ──► ofme-api /api/v1/agent
```

| Boundary | Authenticated by | Notes |
|---|---|---|
| Operator → console/API | JWT access token or `ofme_…` API key | TLS terminates at the ingress |
| Agent → `/api/v1/agent` | X.509 client certificate (fingerprint verified by the ingress) | Serial fallback only in `development`/`testing` |
| API/worker → PostgreSQL | Password from `DATABASE_URL` | Not TLS by default in compose; enable `sslmode` for managed databases |
| API/worker → S3 | Access key / instance role | Buckets are private; backup payloads are AES-256-GCM encrypted before upload and streamed through an authenticated API endpoint |
| API → OPNsense | Per-device API key + secret, AES-GCM encrypted at rest | `OPNsense_VERIFY_TLS=true` by default |
| Automation → gRPC | Static `x-ofme-token` | Off by default, read-only, must stay on a private network |

The platform assumes the ingress is the only component that can assert a client
certificate. If the API is reachable directly, the `X-Device-Cert-Fingerprint`
header is forgeable — that is why the service must not be published without a
proxy that strips client-supplied values for it.

## Authentication

### Passwords

* Argon2id via `argon2-cffi` with `time_cost=3`, `memory_cost=65536` (64 MiB),
  `parallelism=4`, `hash_len=32`, `salt_len=16` (`app/core/security.py`).
* Policy: at least `PASSWORD_MIN_LENGTH` (default 12) characters, one uppercase,
  one lowercase, one digit, one symbol. Enforced on create, change and reset.
* `password_needs_rehash()` is consulted after a successful login, so raising the
  Argon2 parameters upgrades hashes transparently on next sign-in.
* Failed logins increment `users.failed_login_attempts`; at
  `LOGIN_MAX_FAILURES` (5) the account is locked for `LOGIN_LOCK_MINUTES` (15).
  The counter resets on success and on an MFA completion.
* A successful password check with MFA enabled returns an `mfa_challenge` token
  (short-lived, `type=mfa_challenge`) instead of a session. The challenge cannot
  be used as an access token: `decode_token(..., expected_type="access")` rejects
  it.

### TOTP

* Secrets are 160-bit base32 (`pyotp.random_base32()`), stored **encrypted** in
  `users.mfa_secret_encrypted`; the provisioning URI is
  `otpauth://totp/OFME:<account>?issuer=OFME`.
* Verification accepts a ±1 step window (30 s steps) to tolerate clock skew.
* Ten single-use backup codes are generated at enrolment. Only SHA-256 hashes are
  stored in `users.mfa_backup_codes`; a used code is removed from the list.
* `ENABLE_MFA=true` is the default. It gates users who have enrolled; it does not
  force enrolment. Force it per tenant by policy, not by a global switch, so
  break-glass accounts remain usable.

### LDAP / Active Directory

* Service bind (`LDAP_BIND_DN` + `LDAP_BIND_PASSWORD`) performs the search, then
  the user's own credentials are used for the bind that proves identity — the
  password never reaches the application database.
* `LDAP_USE_TLS=true` and `Tls(validate=2)` mean the server certificate is
  validated against the system trust store. `ldaps://` is selected automatically
  when the URL scheme says so.
* Group DNs are mapped to OFME roles through `LDAP_ROLE_MAP`
  (`cn=ofme-admins,ou=groups,dc=example,dc=com=TenantAdmin;...`), case-insensitive
  on the DN. A user with no mapped group gets no elevated role.
* LDAP identities are reconciled into `users` with `auth_provider=ldap`; local
  password login for such a user is not possible.

### OIDC / Entra ID

* Authorization-code flow with `state` and `nonce`; both are stored in
  short-lived `oidc_state` tokens signed with the platform key, so a callback
  cannot be replayed across sessions.
* The ID token is verified against the provider's JWKS (`PyJWKClient`), with
  issuer, audience, `exp` and `nonce` checked (`app/integrations/oidc.py`). The
  discovery document is cached for one hour.
* Entra ID is the same implementation with the issuer
  `https://login.microsoftonline.com/<tenant>/v2.0` and the `groups` claim mapped
  to roles.
* Client secrets come from the environment (or Vault); they are never returned by
  an API.

## Tokens

### Access token

HS256 JWT signed with `SECRET_KEY`. Claims:

| Claim | Meaning |
|---|---|
| `sub` | user UUID |
| `tid` | tenant UUID (may be `null` for a tenant-less SuperAdmin) |
| `roles`, `perms` | role names and the flattened permission set at issue time |
| `sa` | SuperAdmin flag |
| `type` | `access` |
| `iat`, `exp` | issue/expiry, `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30) |
| `jti` | unique token id |
| `iss` | `APP_NAME` |

Decoding requires `exp`, `iat`, `sub` and `type`, validates the issuer, and
rejects any token whose `type` is not `access`. The `perms` claim is advisory for
the UI; every request re-derives permissions from the database
(`_user_principal`), so revoking a role takes effect on the next call rather than
at token expiry.

### Refresh token

Opaque to the client (a JWT with `type=refresh`, `jti`, `exp` =
`REFRESH_TOKEN_EXPIRE_DAYS`, default 7) but **stateful** on the server: only
`SHA-256(token)` is stored in `refresh_tokens.token_hash`.

Rotation is strict:

1. `POST /api/v1/auth/refresh` decodes the token, looks up the row by `jti`,
   rejects it if `revoked_at` is set or `token_hash` does not match, and checks
   `expires_at`.
2. The presented row is revoked, `replaced_by` is set to the new `jti`, and a new
   pair is issued.
3. Replaying a rotated token fails; presenting a token whose hash does not match
   its row revokes the whole session (defence against database tampering).

`POST /api/v1/auth/logout` revokes one session (with a refresh token) or all
sessions of the user (`all_sessions=true`). `GET /api/v1/auth/sessions` lists the
active refresh sessions with user agent and IP so a user can spot a stolen
session.

### API keys

* Format `ofme_<43-char urlsafe>`, generated with `secrets.token_urlsafe(32)`.
* Only `SHA-256(plaintext)` is stored (`api_keys.key_hash`), plus a 12-character
  `key_prefix` for identification. The plaintext is returned exactly once at
  creation.
* Lookup is by hash; comparison is constant-time.
* `scopes` is a permission list. When non-empty and not `["*"]`, the effective
  permission set is `user permissions ∩ scopes`. A SuperAdmin key is **not**
  silently widened: the intersection is skipped for SuperAdmin, but the key still
  carries `tenant_id` and can only act in that tenant.
* Expiry (`expires_in_days`) and revocation (`DELETE /api/v1/api-keys/{id}`) are
  enforced on every request; `last_used_at` is updated per call.
* Because an API key is a bearer credential, put it in a secret manager, scope it
  to the minimum, and prefer short expiries for CI.

## Authorisation

Permissions are strings (`domain:action`) declared once in `P`
(`app/rbac/permissions.py`); roles are named bundles in `ROLE_MATRIX` and are
seeded per tenant. Route guards are declared at the router:

```python
dependencies=[Depends(require_permissions(P.DEVICE_WRITE))]
```

`require_permissions(*perms)` is all-of by default and `any_of=True` for
alternatives. `require_superadmin()` gates platform-wide endpoints (tenant CRUD,
platform settings). The `Principal.can()` fast path returns `true` for a
SuperAdmin, but SuperAdmin is still tenant-scoped by `get_tenant_id`.

| Role | Permissions | Intended use |
|---|---|---|
| `SuperAdmin` | 79 (all) | Platform operators; must send `X-Tenant-Id` for tenant data |
| `TenantAdmin` | 74 | Full control inside one tenant, including users and API keys |
| `Admin` | 72 | Configuration and deployment, no tenant/user administration |
| `Operator` | 46 | Day-to-day device, policy and monitoring operations |
| `Auditor` | 31 | Read-only plus audit, compliance and drift review |
| `ReadOnly` | 28 | Read-only inventory, metrics and reports |

The matrix is code, so upgrades must not leave the database behind. On every
startup `sync_rbac_catalogue()` (`app/seeds/bootstrap.py`) inserts new permission
catalogue rows and re-aligns each `is_system` role with `ROLE_MATRIX`; custom
roles are never touched. Without this step a deployment installed before a
permission existed would keep the old list until the role was edited by hand.

Notable separations: `policy:approve` and `change:approve` are not implied by
`policy:write`; `backup:restore` is separate from `backup:create`;
`device:credentials` (read a device's OPNsense API secret) is granted only to
`SuperAdmin`, `TenantAdmin` and `Admin`; `platform:settings` and `tenant:delete`
are SuperAdmin-only.

### Tenant isolation

* Every tenant-scoped table carries `tenant_id NOT NULL` with
  `ON DELETE CASCADE`; repositories are constructed with a `UnitOfWork(session,
  tenant_id)` and always add the predicate.
* `get_tenant_id` is the only source of the effective tenant:
  * tenant-bound users: `X-Tenant-Id` is optional but, if present, must equal
    their own tenant (otherwise `TenantIsolationError`);
  * SuperAdmin: `X-Tenant-Id` is **mandatory** unless the account itself is bound
    to a tenant. Omitting it is an error, never a cross-tenant read.
* `get_device_for_principal` re-checks the tenant on every device-scoped path,
  and the gRPC facade filters by the explicit `tenant_id` in the request.
* Integration tests (`tests/test_api_tenant_isolation.py`,
  `tests/test_grpc.py`) assert that a second tenant sees nothing, including for
  direct object references.

## Agent identity (mTLS)

Device certificates are issued by the internal CA and bound to a tenant through
a private extension.

* Subject: `CN=device-<serial>`, organisation `OFME Managed Device`,
  with SANs for the hostname and management IP when known.
* Private extensions: `1.3.6.1.4.1.57264.1.1` (device) and
  `1.3.6.1.4.1.57264.1.2` (tenant UUID, readable with `ca.tenant_of()`).
* Key usage: digital signature + key encipherment; EKU client auth.
* Validity `PKI_DEVICE_VALIDITY_DAYS` (365). Rotation starts
  `PKI_RENEW_BEFORE_DAYS` (30) before expiry via
  `ofme.devices.rotate_certificates` and the agent's `renew_certificate` command.

`get_agent_device` (`app/api/v1/endpoints/agent.py`) accepts a request only when:

1. `X-Device-Id` names an existing, non-deleted device; **and**
2. the supplied fingerprint (colon/space-insensitive, lowercased) matches an
   `active` `device_certificates.fingerprint_sha256` for that device and the
   certificate is not past `valid_to`; or
3. in `development`/`testing` only, `X-Device-Serial` matches the device serial.

There is no shared agent password. A revoked certificate stops working on the
next request because the status is checked per request, not cached. The CRL is
available for external verifiers (`CertificateAuthority.build_crl`, seven-day
`next_update`).

The plugin never applies arbitrary commands: the agent picks up a whitelist
(`noop`, `ping`, `sync_config`, `renew_certificate`, `restart_agent`,
`collect_diagnostics`, `reload_firewall`, `update_telemetry`) and reports results
in the next heartbeat. Anything else is rejected server-side at enqueue time.

## Data protection

### At rest

* Credentials that must be replayed — device OPNsense API secrets, device
  private keys, TOTP secrets, WireGuard preshared keys — are encrypted with
  AES-256-GCM (`encrypt_secret`/`decrypt_secret`). The value is
  `base64(nonce[12] || ciphertext||tag)`.
* The key is `SHA-256(SECRET_KEY)`. This is envelope encryption with a single
  derived key, not a KMS hierarchy: rotating `SECRET_KEY` invalidates every
  encrypted column. Rotate deliberately (re-encrypt first) and keep the key in
  Vault/KMS rather than an `.env` file in production.
* Password hashes (Argon2id) and API-key/refresh-token hashes (SHA-256) are
  one-way; backups of the database do not expose plaintext credentials, but they
  do expose the material needed to decrypt device secrets if `SECRET_KEY` leaks.
  Store database dumps and `SECRET_KEY` separately.
* Backup artefacts are gzip XML in a private bucket with `SHA-256` checksum and
  HMAC-SHA256 signature (`sign_payload`). Both are verified before a restore;
  a mismatch aborts with "Backup signature invalid - restore aborted".

### In transit

* TLS terminates at the ingress. The Helm chart redirects HTTP → HTTPS
  (`ssl-redirect: "true"`), and the API sets HSTS in production.
* Response headers (`SecurityHeadersMiddleware`): `X-Content-Type-Options:
  nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
  strict-origin-when-cross-origin`, `Permissions-Policy` denying geolocation,
  microphone, camera and payment, `Cross-Origin-Opener-Policy: same-origin`,
  `Cross-Origin-Resource-Policy: same-site`, `Cache-Control: no-store`.
* API responses also carry a CSP (`default-src 'self'; script-src 'self';
  connect-src 'self' ws: wss:; frame-ancestors 'none'`). The SPA is served by
  nginx with its own policy.
* CORS is an explicit allow-list (`CORS_ORIGINS`), credentials enabled, methods
  and headers limited to what the console uses, preflight cached for 600 s.
* Request bodies are capped at 32 MiB (`BodySizeLimitMiddleware`) before parsing.

## Rate limiting

`RateLimitMiddleware` (`app/core/rate_limit.py`) enforces a fixed-window budget on
every API request except liveness/readiness, `/metrics`, the OpenAPI document,
`/docs`, `/redoc` and `/ws`.

| Bucket | Identity | Default budget |
|---|---|---|
| `api` | credential digest, `X-Device-Id` or client IP | `RATE_LIMIT_REQUESTS` = 600 per `RATE_LIMIT_WINDOW_SECONDS` = 60 s |
| `auth` | same | `RATE_LIMIT_AUTH_REQUESTS` = 20 per window |

* Authenticated traffic is keyed by a SHA-256 prefix of the presented
  `Authorization`/`X-API-Key` value, so one session cannot exhaust another and the
  raw credential never appears in Redis or logs.
* Device agents are keyed by `X-Device-Id`, so a fleet behind one NAT address gets
  a budget per firewall. Only trusted proxies can influence the IP fallback.
* `/api/v1/auth/*` (login, LDAP login, refresh, MFA verify, OIDC callback) uses the
  stricter `auth` bucket; the general bucket is untouched by it.
* Counters live in Redis (`INCR` + one `EXPIRE`), so the limit is shared by all
  API replicas. If Redis is unreachable the limiter degrades to an in-process
  counter, logs `ratelimit.redis_unavailable` and keeps enforcing per replica —
  it never fails open.
* Rejections return `429` with the standard error envelope, `Retry-After`,
  `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Window` and
  `X-RateLimit-Reset`, and increment `ofme_rate_limited_total{scope}`.

Set `TRUSTED_PROXY_IPS` to the ingress/LB CIDRs when the API runs behind a proxy;
otherwise every anonymous request is attributed to the proxy address. The bundled
nginx already overwrites `X-Real-IP`, which the limiter prefers over
`X-Forwarded-For`. Per-account lockout (`LOGIN_MAX_FAILURES`) still applies on top
of the per-IP/per-credential budget.

## Audit integrity

Every state change writes an `audit_logs` row inside the same transaction as the
change. `prev_hash` is the previous row's `entry_hash`;
`entry_hash = SHA-256(prev_hash || canonical_json(entry))`. Inserts take
`pg_advisory_xact_lock(918273645)`, so concurrent writers cannot fork the chain.

`GET /api/v1/audit/integrity` recomputes the chain and reports the first
divergence; the result also sets the `ofme_audit_chain_valid` gauge that backs
`OFMEAuditChainBroken`. `GET /api/v1/audit/export` produces a CSV of the filtered
trail for external retention, and `GET /api/v1/audit/events/{type}/{id}` replays
an aggregate's `domain_events` (per-aggregate sequence + hash chain).

The chain is tamper-**evident**, not tamper-proof: an attacker with database
write access and the application code could rebuild it. Ship the audit export to
append-only storage (S3 Object Lock, WORM bucket, SIEM) if that threat is in
scope. The application never deletes audit rows on a timer;
`AUDIT_RETENTION_DAYS` (2555) is documentation for the external retention job.

## Secrets management

| Secret | Where it belongs |
|---|---|
| `SECRET_KEY` | Vault/KMS, injected as an env var; ≥ 32 chars enforced in production |
| `DATABASE_URL`, `REDIS_URL`, `CELERY_*` | Kubernetes Secret / compose `.env`, never an image layer |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Instance role or secret; scope to the two buckets |
| `GRPC_SERVICE_TOKEN` | Secret, random ≥ 32 bytes, only when gRPC is enabled |
| `PKI_CA_KEY_PATH` (`ca.key`) | Secret volume, `0600`, never in an image or a Git repo |
| `BOOTSTRAP_ADMIN_PASSWORD` | One-time secret; delete after the first login |
| LDAP bind password, OIDC client secret, Git tokens | Vault (`VAULT_ENABLED=true`) or the platform secret |

Vault integration (`app/integrations/vault.py`) reads KV v2 at
`<mount>/data/<path>` and is used by configuration that opts in; enabling it does
not automatically migrate existing env secrets, so the cutover is deliberate.

The CA private key is the highest-value secret in the system: it can mint a
certificate for any device in any tenant. Keep it in an HSM/transit engine for
production, restrict `get secret ofme-pki` to the platform team, and plan CA
rotation as a re-enrolment event.

## Hardening checklist

Before exposing an installation:

- [ ] `ENVIRONMENT=production`, `DEBUG=false`, `ENABLE_DOCS=false`.
- [ ] `SECRET_KEY` ≥ 32 random bytes from a CSPRNG, stored in Vault/KMS.
- [ ] `ALLOWED_HOSTS` and `CORS_ORIGINS` set to the real hostnames (no `*`).
- [ ] TLS at the ingress with a valid certificate; HTTP redirected; HSTS on.
- [ ] Ingress strips client-supplied `X-Device-Cert-Fingerprint` and injects the
      value from the verified TLS session (`nginx.ingress.kubernetes.io/auth-tls-*`).
- [ ] The API Service is not exposed outside the cluster; only the ingress is.
- [ ] PostgreSQL and Redis are not reachable from untrusted networks; Redis has a
      password and TLS when it crosses a network boundary.
- [ ] S3 buckets are private, versioned and encrypted; lifecycle rules align with
      backup retention.
- [ ] `BOOTSTRAP_ADMIN_PASSWORD` removed after first login and replaced by an
      SSO-backed admin.
- [ ] MFA enforced for every administrative role.
- [ ] `GRPC_ENABLED=false` unless a consumer needs it; if enabled, a strong token,
      a NetworkPolicy and (ideally) mTLS.
- [ ] Prometheus `/metrics` reachable only from the monitoring namespace.
- [ ] `TRUSTED_PROXY_IPS` set to the ingress/LB CIDRs so rate limiting and audit
      rows see the real client address.
- [ ] Rate-limit budgets reviewed for the expected fleet size; the application
      limiter is per identity, so keep a WAF/ingress limit in front of
      `/api/v1/auth/*` as defence in depth.
- [ ] Audit export shipped to append-only storage; chain check scheduled.
- [ ] Backup restore rehearsed and the CA key escrowed offline.

## Known limitations

Recorded so operators do not assume protection that is not there:

* **Rate limiting is per identity, not per tenant.** The `api` and `auth`
  buckets are keyed by credential/device/IP. A tenant-wide quota and a global
  fleet-wide ceiling require an API gateway and are not implemented in-process.
* **Single symmetric key for encryption and JWT signing.** `SECRET_KEY` compromise
  allows both token forgery and decryption of stored device secrets. A KMS-backed
  split (separate signing key, data-encryption key) is the production upgrade.
* **HS256 only.** There is no asymmetric JWT option; services that share the
  secret can mint tokens.
* **The agent fingerprint is only as trustworthy as the ingress.** Direct access
  to the API bypasses mTLS.
* **Audit chain is tamper-evident, not immutable.** External WORM storage is
  required for a defensible trail.
* **The default compose stack is a development environment**: known passwords,
  plaintext datastores and MinIO on `latest`. It is not a production topology.
