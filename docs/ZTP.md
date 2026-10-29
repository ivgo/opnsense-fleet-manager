# Zero-touch provisioning

ZTP turns an unconfigured OPNsense box into a registered device with a client
certificate, a site/group/template assignment and a bootstrap package, without an
operator logging into it. The implementation is `backend/app/services/ztp.py`,
the routers `backend/app/api/v1/endpoints/ztp.py` and
`backend/app/api/v1/endpoints/agent.py`, and the device side is
`plugin/os-fleet-agent/src/opnsense/mvc/app/library/OPNsense/FleetAgent/Enrollment.php`.

## Flow

```text
operator                    OFME                          OPNsense + os-fleet-agent
   │                          │                                      │
   │ POST /ztp/enrollments    │                                      │
   │─────────────────────────►│ token = token_urlsafe(32)            │
   │  {token, bootstrap_url}  │ store SHA-256(token), hint=token[:8] │
   │◄─────────────────────────│ status=pending, expires_at           │
   │                          │                                      │
   │ paste token into the     │                                      │
   │ plugin UI ─────────────────────────────────────────────────────►│
   │                          │◄── GET /agent/bootstrap?token= ──────│
   │                          │─── package (template, platform) ────►│
   │                          │◄── POST /agent/enroll ───────────────│
   │                          │    serial, MAC, hostname, CSR        │
   │                          │  validate token/serial/MAC/TTL/limit │
   │                          │  create device, sign CSR with CA     │
   │                          │─── cert, CA, bootstrap, URLs ───────►│ install key+cert,
   │                          │                                      │ verify CA fingerprint,
   │                          │                                      │ clear token, heartbeat
```

Discovery (`GET /ztp/discovery`) is the same contract for images that fetch
their configuration from a well-known URL instead of a pasted token.

## Two public entry points

The public surface exists twice:

| Path | Consumer | Implementation |
|---|---|---|
| `GET /api/v1/ztp/discovery` | provisioning images / installers | `EnrollmentAgentService.discovery` |
| `GET /api/v1/ztp/bootstrap?token=` | provisioning images | `EnrollmentAgentService.bootstrap_package` |
| `POST /api/v1/ztp/enroll` | provisioning images | `EnrollmentService.enroll` |
| `GET /api/v1/agent/bootstrap?token=` | the OPNsense plugin | same service |
| `POST /api/v1/agent/enroll` | the OPNsense plugin | same service |

Both `bootstrap` endpoints return the same `BootstrapPackage`, and both
`enroll` endpoints call the same enrollment service (the `/agent` variant checks
token expiry before loading the service; the `/ztp` variant lets the service do
it). They are **unauthenticated apart from the token** and must be reachable
through the ingress from devices that have no certificate yet.

`/ztp/discovery` has no token and therefore reveals only the platform URL, the
two endpoint paths and the CA SHA-256 fingerprint. `tenant_hint` exists in the
schema but is not populated.

## Enrollment tokens

### Minting

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
        "site_id": "'$SITE_ID'",
        "group_id": "'$GROUP_ID'",
        "template_id": null,
        "device_serial": null,
        "device_mac": null,
        "hostname": null,
        "ttl_minutes": 60,
        "discovery_method": "token"
      }' \
  https://ofme.example.com/api/v1/ztp/enrollments | jq
```

```json
{
  "enrollment_id": "b5f1…",
  "token": "9nQ3…43-char-urlsafe…",
  "expires_at": "2026-01-14T10:12:44Z",
  "bootstrap_url": "https://ofme.example.com/api/v1/ztp/bootstrap?token=9nQ3…",
  "site_id": "…",
  "template_id": null
}
```

* The token is `secrets.token_urlsafe(32)` (43 characters, 256 bits of entropy).
* Only `SHA-256(token)` is stored (`ztp_enrollments.token_hash`, unique). The
  plaintext is returned **once**; there is no endpoint to read it again.
* `token_hint` stores the first 8 characters for identification in the UI. That
  leaves 35 characters of the token secret.
* `ttl_minutes` defaults to `ENROLLMENT_TOKEN_TTL_MINUTES` (60) and is constrained
  to 5–10080 (7 days). The expiry is absolute (`expires_at`), not sliding.
* `discovery_method` is `token`, `dhcp`, `dns`, `https` or `certificate`; it is
  recorded on the enrollment and copied into the device metadata. Only `token`
  has an implemented flow.
* Optional constraints bind the token to one box: `device_serial` (exact match),
  `device_mac` (stored uppercased, `AA:BB:CC:DD:EE:FF` pattern enforced) and
  `hostname` (used as the device hostname and as a site-matching hint).
* `site_id`, `group_id` and `template_id` pre-assign the device. Passing nulls
  lets the resolver choose (below).
* Minting writes `ztp.token_created` to the audit trail.

### Lifecycle

`ZtpStatus` values:

| Status | Set by | Meaning |
|---|---|---|
| `pending` | creation | token usable, device not enrolled |
| `enrolled` | manual `PATCH` (requires `ztp:approve`) | accepted, provisioning still in progress |
| `provisioning` | manual `PATCH` | operator-defined intermediate state |
| `completed` | enrollment (automatic) or manual `PATCH` | device created, certificate issued |
| `failed` | manual `PATCH` | operator marked the attempt failed |
| `expired` | automatic on an enrolment attempt after `expires_at` | token no longer usable |
| `revoked` | `POST /enrollments/{id}/revoke` | token no longer usable |

Only `pending` can enroll. The automatic transitions are
`pending → completed` (successful enrollment) and `pending → expired` (a late
attempt; the row is committed before the 401 is returned). Everything else is a
manual `PATCH /api/v1/ztp/enrollments/{id}` with `{"status": "…"}`; setting
`completed` or `enrolled` additionally requires `ztp:approve`
(`ADMIN`/`TENANT_ADMIN`/`SUPER_ADMIN`). `PATCH` does not validate transitions, so
an operator can move a revoked token back to pending.

`revoke` only changes the enrollment row: it does **not** delete the device or
revoke the certificate if enrollment already happened. Use
`DELETE /api/v1/devices/{id}` or the certificate endpoints for that.

`DELETE /api/v1/ztp/enrollments/{id}` removes the record (hard delete, no audit
entry). The device keeps `metadata.enrollment_id` as a dangling reference.

### Administration endpoints

| Method | Path | Permission |
|---|---|---|
| `POST` | `/ztp/enrollments` | `ztp:write` |
| `GET` | `/ztp/enrollments?status=` | `ztp:read` |
| `GET` | `/ztp/enrollments/{id}` | `ztp:read` |
| `PATCH` | `/ztp/enrollments/{id}` | `ztp:write` (+ `ztp:approve` for `completed`/`enrolled`) |
| `POST` | `/ztp/enrollments/{id}/revoke` | `ztp:write` |
| `DELETE` | `/ztp/enrollments/{id}` | `ztp:write` |

`OPERATOR` has `ztp:read` only. `AUDITOR`/`READ_ONLY` have `ztp:read`.

## Enrollment

### Request

```bash
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{
        "token": "'$ENROLLMENT_TOKEN'",
        "serial_number": "OPNsense-4A1B2C3D",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "hostname": "vie-branch-01",
        "model": "DEC750",
        "firmware_version": "25.1.2",
        "csr_pem": "-----BEGIN CERTIFICATE REQUEST-----\n…\n-----END CERTIFICATE REQUEST-----\n",
        "hardware_profile": {"cpu": "N100", "memory_mb": 8192, "management_ip": "10.20.0.5"}
      }' \
  https://ofme.example.com/api/v1/ztp/enroll | jq
```

| Field | Required | Rules |
|---|---|---|
| `token` | yes | ≥ 16 characters; looked up by SHA-256 |
| `serial_number` | yes | 3–128 characters; unique within the tenant |
| `mac_address` | no | compared uppercase, only when both sides provide it |
| `hostname` | no | ≤ 255; used for the device hostname and SAN |
| `model`, `firmware_version` | no | stored on the device |
| `csr_pem` | no | PKCS#10; signature must validate |
| `hardware_profile` | no | arbitrary JSON, stored; `management_ip` drives site matching |

### Validation order

`EnrollmentService.enroll` evaluates in this order and stops at the first
failure:

1. token hash exists and belongs to the tenant resolved from the token (the
   endpoint resolves the tenant, so this is a cross-check) → `401`;
2. status is `pending` → `409` with the current status;
3. `expires_at` is in the future → marks `expired`, commits, `401`;
4. `device_serial` matches, when the token is pre-bound → `401`;
5. `device_mac` matches uppercased, when both sides provide it → `401`;
6. tenant row exists → `404`;
7. `devices.count() < tenant.device_limit` → `402` (`LicenseLimitError`);
8. no device with this serial exists in the tenant → `409`;
9. assignment resolution (below);
10. device row, certificate row and enrollment update, bootstrap package, audit
    entry, `DeviceRegistered` event, commit.

The device is created as `status=registered`, `enrolled_at=now`, tagged `ztp`,
with `metadata = {hardware, enrollment_id, discovery}` and
`ip_address = <source IP>`. The source IP is `request.client.host`, overridden by
the first value of `X-Forwarded-For` when present. Configure
`TRUSTED_PROXY_IPS` and let the ingress set that header; otherwise a client can
choose the IP recorded on the device and put into its certificate SAN.

### Assignment resolution

`site`:

1. the token's `site_id`, if the site still exists;
2. otherwise, when `payload.hostname` is set, the first site (of up to 200) whose
   `metadata.subnets` contains `hardware_profile.management_ip`;
3. otherwise the first site in the tenant;
4. otherwise no site.

`group`: the token's `group_id`, else the first non-deleted group in the tenant.

`template`: the token's `template_id`, else the group's `template_id`, else the
first active template.

Device name:

```text
<slug(site.code)>-<slug(last 8 chars of serial)>     e.g. vie-4a1b2c3d
site-<slug(last 8 chars of serial)>                   when no site resolved
site-<random hex>                                     when no serial
```

truncated to 80 characters. `hostname` is `payload.hostname` or the device name.

None of this is validated against the tenant's naming policy; collisions are
possible because device names are not unique.

### Certificate issuance

`CertificateAuthority.issue` is called with
`common_name = "device-<serial>"`, the tenant id, the CSR (when supplied), SAN DNS
= hostname and SAN IP = source IP.

* With a CSR: the CSR signature is verified, its public key is used, and the
  platform **does not** store a private key (`private_key_encrypted = ""`). This
  is the plugin's path; the key never leaves the device.
* Without a CSR: the platform generates an EC P-384 key and stores it encrypted,
  but the private key is not part of `EnrollmentResponse`. A client cannot use
  the resulting certificate, so always send a CSR.
* Subject: `O=OFME Managed Device`, `CN=device-<serial>` (any CN in the CSR is
  replaced). Extensions: `basicConstraints CA=false` (critical), key usage
  digitalSignature+keyEncipherment (critical), EKU `clientAuth`, SKI/AKI, the
  device OID `1.3.6.1.4.1.57264.1.1` (serial) and tenant OID
  `1.3.6.1.4.1.57264.1.2`.
* Validity: `PKI_DEVICE_VALIDITY_DAYS` (365), backdated 5 minutes.
* The `device_certificates` row is `active`, holds the PEM, serial, SHA-256
  fingerprint and validity, and is what `get_agent_device` checks on every agent
  request. `devices.certificate_serial` is set.

### Response

```json
{
  "status": "accepted",
  "device_id": "1d6c…",
  "device_name": "vie-4a1b2c3d",
  "certificate_pem": "-----BEGIN CERTIFICATE-----\n…",
  "ca_pem": "-----BEGIN CERTIFICATE-----\n…",
  "certificate_serial": "5f3a…",
  "valid_to": "2027-01-14T09:12:44Z",
  "bootstrap": {
    "enrollment_id": "b5f1…",
    "device_name": "vie-4a1b2c3d",
    "site_id": "…",
    "template": {"id": "…", "name": "branch-base", "body": "…", "variables": {}},
    "policies": [
      {"id": "…", "name": "branch-edge", "kind": "firewall",
       "environment": "production", "content": "…"}
    ],
    "vpn": [
      {"name": "wg-vie-to-fra", "protocol": "wireguard", "interface": "wg-1",
       "allowed_ips": ["10.10.0.0/24"], "keepalive": 25, "mtu": 1420}
    ],
    "monitoring": {"heartbeat_interval_seconds": 60, "metric_retention_days": 90},
    "platform": {
      "api_version": "v1",
      "tenant_id": "…",
      "site": "Vienna",
      "group": "Branches",
      "ca_fingerprint": "ab12…"
    }
  },
  "heartbeat_url": "/api/v1/agent/heartbeat",
  "heartbeat_interval_seconds": 60
}
```

`heartbeat_url` is a path, not an absolute URL; the plugin prefixes
`platform_url` when it does not start with `http(s)://`. `status` is always the
literal `accepted`.

### Bootstrap package contents

Two variants share the `BootstrapPackage` schema:

| Field | Pre-enrollment (`/bootstrap`) | Post-enrollment (response) |
|---|---|---|
| `enrollment_id` | token row id | device's `metadata.enrollment_id` |
| `device_name` | token hostname or `ztp-<hint>` | resolved device name |
| `site_id` | token site | device site |
| `template` | token template (`id`, `name`, `body`) | resolved template (`id`, `name`, `body`, `variables`) |
| `policies` | empty | **every deployed policy in the tenant** |
| `vpn` | empty | tunnels whose `local_device_id` is this device |
| `monitoring` | heartbeat interval | heartbeat interval + metric retention |
| `platform` | API version, tenant id/slug, site name, CA fingerprint | API version, tenant id, site/group names, CA fingerprint |

The pre-enrollment package is available while the status is `pending` or
`enrolled`, and expires with the token. It does **not** include policies or VPN
tunnels (the device has no identity yet).

The post-enrollment package's `policies` list is tenant-wide: it is not filtered
by site, group, selector or environment. Treat the enrollment token as a
credential that can read every deployed policy document (and the template body)
in the tenant.

## The device side (os-fleet-agent)

The plugin performs enrollment from **Services → Fleet Agent**:

1. `platform_url` must match `https://…` (enforced by the model mask); the agent
   appends `/api/v1` unless it is already present.
2. The operator pastes the token. It is stored in `config.xml` until enrollment
   succeeds.
3. `Enrollment::bootstrap` calls `GET /agent/bootstrap?token=…` over TLS with
   `verify_tls` (default on) and the pinned CA file if one exists, merges the
   package into `state.json` and logs it.
4. `Identity::generateKeyPair` creates an RSA-2048 key and a SHA-256 CSR
   locally in `/usr/local/etc/ofme-agent` (`0700` directory, `0600` key).
5. `Enrollment::enroll` posts serial, MAC, hostname, model, firmware, CSR and
   hardware profile to `/agent/enroll`.
6. Every required field in the response is checked (`device_id`,
   `certificate_pem`, `ca_pem`, `certificate_serial`, `heartbeat_url`).
7. The private key is written, the certificate and CA are installed, and if the
   local CA fingerprint differs from `platform.ca_fingerprint`, everything is
   reset and enrollment fails. A key written before a failed install is deleted.
8. `applyEnrollment` stores device id/name/serial, CA fingerprint, heartbeat URL
   and a clamped interval (15–3600 s), then **clears the enrollment token** and
   saves `config.xml`.
9. State records `enrolled_at`, `device_id`, `device_name`,
   `certificate_serial`, `heartbeat_url`, clears `last_error` and resets
   `consecutive_failures`.

After that the agent authenticates with `X-Device-Id` plus the client
certificate fingerprint asserted by the ingress. See SECURITY.md for the trust
boundary and `plugin/os-fleet-agent/README.md` for the UI and CLI.

CLI equivalent (the token is read from `config.xml`, so set it in the UI first):

```bash
# on OPNsense
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php enroll
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php status
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php test
```

The plugin refuses non-HTTPS platform URLs and never writes the token or private
key to logs or diagnostics.

## Local smoke test (no appliance)

`tests/agent/` is a Python stand-in that speaks the same contract, so the
enrollment path can be exercised against a local stack. It lives in the
`testing` Compose profile, because it needs a one-time token and must not make
`docker compose up -d --wait` fail.

```bash
# 1. mint a token bound to the serial the agent will report
TEST_AGENT_SERIAL=OFME-TEST-004 make ztp-token

# 2. start the helper with that token
ENROLLMENT_TOKEN=<printed token> TEST_AGENT_SERIAL=OFME-TEST-004 \
  docker compose --profile testing up -d ofme-test-agent
make agent-logs

# 3. clean up when finished
make agent-down
```

Expected log sequence:

```text
[agent] bootstrap ok: device_name=ztp-…
[agent] enrolled: device_id=… serial=…
[agent] config fetched: hash=… rules=0 aliases=0
[agent] heartbeat ok: accepted=True commands=0 results=0
```

The device appears in `/devices` as `online` / `connected` and an `ztp.enrolled`
audit entry is written. Two failure modes are worth knowing:

* `ENROLLMENT_TOKEN is missing or shorter than 16 characters` — the token was not
  exported into the Compose environment; the agent checks this before calling the
  API.
* `HTTP Error 409: Conflict` — a device with that serial is already registered
  (`enroll` is not a re-enrolment endpoint). Use a fresh `TEST_AGENT_SERIAL`, or
  delete the old device first.

## End-to-end example

```bash
API=https://ofme.example.com/api/v1
AUTH="Authorization: Bearer $TOKEN"

# 1. mint a token bound to a site
ENROLL=$(curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"site_id":"'$SITE_ID'","ttl_minutes":120,"discovery_method":"token"}' \
  "$API/ztp/enrollments")
TOKEN=$(echo "$ENROLL" | jq -r .token)
ID=$(echo "$ENROLL" | jq -r .enrollment_id)
echo "$ENROLL" | jq '{enrollment_id,expires_at,bootstrap_url}'

# 2. hand the token to the device, then watch it complete
curl -fsS -H "$AUTH" "$API/ztp/enrollments/$ID" | jq '{status,device_id,token_hint,enrolled_at}'
curl -fsS -H "$AUTH" "$API/devices?search=vie-" | jq '.items[0] | {id,name,status,site_id,enrolled_at}'

# 3. the issued certificate
curl -fsS -H "$AUTH" "$API/devices/$(curl -fsS -H "$AUTH" "$API/ztp/enrollments/$ID" | jq -r .device_id)/certificates" \
  | jq '.[0] | {serial_number,fingerprint_sha256,valid_to,status}'
```

If the token leaks, revoke it before it is used:

```bash
curl -fsS -X POST -H "$AUTH" "$API/ztp/enrollments/$ID/revoke" | jq
```

## Operational notes

* Enrollment is the only unauthenticated write path besides login. Put it behind
  the ingress, keep TLS termination correct, and consider a WAF rule limiting
  `POST /api/v1/(ztp|agent)/enroll` per source. The application has no rate
  limiter.
* A failed enrollment leaves the token `pending` (and the device unregistered);
  retrying with the same token is allowed until it expires, unless the failure
  was a serial/MAC mismatch or a duplicate serial.
* The license check counts tenant devices, so a token minted when the tenant was
  below its limit can still fail at enrollment.
* `metric_retention_days` in the post-enrollment package is informational; the
  device does not purge platform data.
* The CA fingerprint in discovery and bootstrap must match `pki/ca.crt`. If the
  CA is recreated, devices fail their fingerprint check and must be reset and
  re-enrolled.

### Audit and events

| Action | When |
|---|---|
| `ztp.token_created` | token minted (site id and serial recorded) |
| `ztp.enrolled` | device created and certificate issued (actor `ztp:<serial>`) |
| `ztp.revoked` | token revoked |

`DELETE /enrollments/{id}`, `PATCH` status changes, discovery and bootstrap reads
are not audited. A successful enrollment publishes `DeviceRegistered`
(`Device` aggregate), which reaches WebSocket subscribers on topic `devices` and
is persisted in the aggregate's domain-event stream.

## Known limitations

* **The post-enrollment bootstrap package is tenant-wide.** `policies` contains
  every deployed policy in the tenant, not the device's applicable subset. A
  token is therefore a read credential for policy content and template bodies.
* **`/bootstrap` can be called repeatedly** while the token is pending or marked
  `enrolled`, and by anyone who holds the token.
* **No approval gate on enrollment.** The device is active (`registered`) as soon
  as the request succeeds; `ztp:approve` only guards manual status changes.
* **No CSR policy enforcement.** The CSR's subject and SANs are replaced; only
  the signature is checked. Key size/algorithm of the supplied public key is not
  constrained.
* **Server-generated keys are unusable by clients.** Without a CSR the platform
  stores a private key it never returns. Always enroll with a CSR.
* **MAC binding is optional and loosely typed.** The enrollment request does not
  validate the MAC format; it is compared only when present on both sides.
* **`X-Forwarded-For` is trusted** when present (subject to `TRUSTED_PROXY_IPS`
  for logging, but not for this field). A direct client can influence the recorded
  management IP and certificate SAN.
* **Discovery URL is derived from the request.** Behind a proxy that does not
  forward the external scheme/host, `platform_url` can be an internal address.
* **Only the token method is implemented.** `dhcp`, `dns`, `https` and
  `certificate` are recorded but have no discovery/provisioning flow.
* **No automatic expiry sweep.** Expiry is noticed when an enrollment is
  attempted (or by comparing `expires_at` in the UI); there is no beat task that
  marks stale tokens `expired`.
* **Revoke is not a certificate revocation.** It stops future enrollment with the
  token; an already issued certificate stays active until revoked separately.
* **No ZTP for switches/APs or firmware images.** The module provisions OPNsense
  identities and configuration only.
