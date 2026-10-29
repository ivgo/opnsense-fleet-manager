# SD-WAN

The SD-WAN controller builds overlays between OPNsense devices, keeps a route
table for each participant, ingests per-link quality telemetry and selects a
path per traffic policy. It is implemented in `backend/app/services/sdwan.py`,
exposed under `/api/v1/sdwan`, scheduled by `ofme.sdwan.health_sweep`, and
rendered by `frontend/src/pages/SdWanPage.tsx`.

Read this as the operator's description of what the code does, including the
parts that are planning/bookkeeping only. The last section lists the gaps
explicitly; do not assume a feature that is not described here.

## Concepts

| Object | Table | Meaning |
|---|---|---|
| Topology | `sdwan_topologies` | A named overlay: type, hub ids, spoke ids, configuration |
| Tunnel | `vpn_tunnels` | One WireGuard interface on **one** device, with a keypair and allowed IPs |
| Link | `sdwan_links` | The measured path associated with a tunnel; carries SLA thresholds and telemetry |
| Route | `sdwan_routes` | A destination reachable through a tunnel on a device |
| Traffic policy | `traffic_policies` | A steering rule: strategy, match, preferred links, priority |

A tunnel is directional. `local_device_id` is the device the controller
configures; `remote_device_id` is the peer. The planner emits one tunnel per
spoke (or per pair direction in a mesh) — it does not create the reverse side.

## Topology types

`topology_type` is one of:

| Type | Planning result |
|---|---|
| `hub_spoke` (default) | one tunnel per spoke, attached to the **first** hub in `hub_device_ids` |
| `full_mesh` | one tunnel for every unordered pair of `hubs + spokes` |
| `regional_hub` | hubs meshed with each other, plus each spoke attached to the geographically nearest hub |

Device ids that no longer exist (deleted from the registry) are silently dropped
before planning. Ids are stored as strings in JSONB and coerced to UUIDs on use.

### Planning algorithm

`TopologyEngine.plan(topology, devices)` is pure: it performs no database or
network I/O and is safe to call in tests.

**Hub-and-spoke**

```text
require at least one hub
for each spoke:
    tunnel name   = "wg-<spoke>-to-<hub>"[:100]
    local         = spoke
    remote        = hubs[0]
    allowed_ips   = [lan_cidr(hub)]
    wan_interface = configuration.wan_interface or "wan"
    priority      = 100
    cost          = 10
```

One hub only: extra hub ids are ignored by the planner, so there is no automatic
hub redundancy. To get a second path, model it as a `full_mesh` / `regional_hub`
topology or create explicit tunnels.

**Full mesh**

```text
require at least two participants (hubs + spokes)
for each unordered pair (a, b):
    tunnel name   = "wg-<a>-<b>"[:100]
    local         = a
    remote        = b
    allowed_ips   = [lan_cidr(b)]
    wan_interface = "wan"
    priority      = 100
    cost          = 10
```

`configuration.wan_interface` is **not** honoured for full mesh; the interface
is always `wan`.

**Regional hub** (the `else` branch)

```text
require at least one hub
for each unordered hub pair (h1, h2):
    name = "wg-hub-<h1>-<h2>"[:100]; allowed_ips = [lan_cidr(h2)]
    priority = 50; cost = 5; wan_interface = "wan"
for each spoke:
    hub = argmin(distance(hub, spoke))
    name = "wg-<spoke>-to-<hub>"[:100]; allowed_ips = [lan_cidr(hub)]
    priority = 100; cost = 10; wan_interface = "wan"
```

Distance is the haversine great-circle distance in kilometres between the sites'
`latitude`/`longitude`. A device with no site, or a site without coordinates,
contributes distance `0.0`, so `min()` picks the first hub in `hub_device_ids`.
Populate site coordinates if you rely on regional placement.

### Allowed IPs

`_lan_cidr(device)` resolves the network that the peer advertises, in order:

1. `device.metadata_["lan_cidr"]`;
2. `device.metadata_["lan_network"]`;
3. `device.ip_address` widened to a `/24` (e.g. `10.10.20.0/24`);
4. the fallback `10.255.255.0/24`.

The result becomes the tunnel's `allowed_ips` and therefore the remote network in
the route table. It is **not** a tunnel address, and nothing allocates a
point-to-point subnet.

### Interface names

When `TunnelCreate.interface_name` is omitted, `TunnelProvisioner.create_tunnel`
counts the topology's existing tunnels and assigns `wg-<n+1>` (`wg-1`, `wg-2`, …).
The count is taken from the database, so provisioning a topology of N spokes
yields N distinct names. A name supplied by the caller is used verbatim and must
be unique on the device.

## Keys and secrets

`generate_wireguard_keypair()` creates an X25519 keypair and returns
base64-encoded raw 32-byte values `(private, public)`.

* `public_key` is stored in clear text; it is not secret.
* the **private** key is encrypted with `encrypt_secret` (AES-256-GCM, key
  derived from `SECRET_KEY`) and stored in `vpn_tunnels.preshared_key_encrypted`.
  The column name is historical: it holds the private key, not a WireGuard
  preshared key.
* `tunnel.config` records `{"private_key_ref": "encrypted", "wan_interface": …}`;
  after a successful push it also carries `key_material: "stored-encrypted"`.
* `POST /sdwan/topologies/{id}/deploy` with `{"regenerate_keys": true}` rotates
  the keypair of **existing** planned tunnels. It does not push the new private
  key to the device and it does not inform the peer — see the limitations.

The private key never leaves the API in an HTTP response (`TunnelOut` omits it).
Rotating `SECRET_KEY` makes every stored key undecryptable; re-provision rather
than rotate the platform secret casually (see SECURITY.md).

## Data model

### `sdwan_topologies`

| Column | Notes |
|---|---|
| `name` | unique per tenant (`uq_sdwan_topologies_tenant_name`) |
| `description` | free text |
| `topology_type` | `hub_spoke`, `full_mesh`, `regional_hub` |
| `status` | string, starts `draft`; set to `active` or `error` by a deploy |
| `configuration` | JSONB, read for `wan_interface` (hub-and-spoke only) |
| `routing_config` | JSONB, stored for consumers; the planner does not read it |
| `hub_device_ids`, `spoke_device_ids` | JSONB arrays of UUID strings |
| `created_by` | user id, nullable |

`status` is a free-form string: `PATCH` accepts any value, and the worker skips
topologies whose status is exactly `draft`.

### `vpn_tunnels`

Unique per `(topology_id, name)`; indexed on `(tenant_id, status)`. Carries
`protocol` (`wireguard`/`ipsec`/`openvpn`), `interface_name`, `public_key`,
encrypted private key, endpoints, `allowed_ips`, `keepalive` (25 s default),
`mtu` (1420 default), `status`, `health_status`, `last_handshake_at`, `metrics`,
`config`. Deleting a topology cascades its tunnels; deleting a device cascades
the tunnels it is local to and nulls `remote_device_id`.

### `sdwan_links`

One row per tunnel created by the provisioner, with `wan_interface`, `cost`
(default 10), `priority` (100), `status`, `latency_ms`, `jitter_ms`, `loss_pct`,
`bandwidth_mbps`, `sla_latency_ms` (150.0 default), `sla_loss_pct` (1.0 default),
`measured_at`, `metadata`. The link is the unit of steering and SLA evaluation.

### `sdwan_routes`

`(topology_id, device_id, destination)` identifies a route. `next_hop` is copied
from the tunnel's `endpoint_remote` (usually `null`), `tunnel_id` links it to the
tunnel, `metric` is 100, `protocol` is `static`, `installed` reflects whether the
tunnel was active at sync time.

### `traffic_policies`

`strategy`, `match` (JSONB, currently not evaluated), `preferred_link_ids`
(JSONB array of strings), `priority`, `enabled`, unique name per topology is not
enforced.

## API

All endpoints are under `/api/v1/sdwan` and are tenant-scoped (SuperAdmin must
send `X-Tenant-Id`).

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/topologies` | `sdwan:read` | paginated list, `search` |
| `POST` | `/topologies` | `sdwan:write` | create (starts `draft`) |
| `GET` | `/topologies/{id}` | `sdwan:read` | read one |
| `PATCH` | `/topologies/{id}` | `sdwan:write` | description, status, hubs, spokes, config |
| `DELETE` | `/topologies/{id}` | `sdwan:write` | delete; refused while tunnels exist |
| `GET` | `/topologies/{id}/graph` | `sdwan:read` | nodes + edges for the UI |
| `POST` | `/topologies/{id}/deploy` | `sdwan:deploy` | plan, create/update tunnels, push, sync routes |
| `GET` | `/topologies/{id}/routes` | `sdwan:read` | stored route table |
| `POST` | `/topologies/{id}/routes/sync/{device_id}` | `sdwan:write` | recompute one device's routes |
| `GET` | `/topologies/{id}/best-link?strategy=` | `sdwan:read` | current best link (or `null`) |
| `POST` | `/topologies/{id}/failover` | `sdwan:write` | evaluate policies, return events |
| `GET` | `/topologies/{id}/tunnels` | `sdwan:read` | tunnels of the topology |
| `POST` | `/tunnels` | `sdwan:write` | create one tunnel + link manually |
| `GET` | `/tunnels/{id}` | `sdwan:read` | read one |
| `DELETE` | `/tunnels/{id}` | `sdwan:write` | withdraw routes, delete tunnel |
| `GET` | `/links?topology_id=` | `sdwan:read` | paginated link inventory |
| `POST` | `/links/{id}/measurements` | `sdwan:write` | ingest telemetry |
| `GET` | `/traffic-policies?topology_id=` | `sdwan:read` | steering policies, ordered by priority |
| `POST` | `/traffic-policies` | `sdwan:write` | create |
| `DELETE` | `/traffic-policies/{id}` | `sdwan:write` | delete |

There is no `PATCH` for tunnels or traffic policies: delete and recreate them.

### Creating a topology

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
        "name": "emea-hub-spoke",
        "description": "EMEA branches to Frankfurt",
        "topology_type": "hub_spoke",
        "hub_device_ids": ["'$HUB_ID'"],
        "spoke_device_ids": ["'$SPOKE_A'", "'$SPOKE_B'"],
        "configuration": {"wan_interface": "wan"},
        "routing_config": {}
      }' \
  https://ofme.example.com/api/v1/sdwan/topologies | jq
```

`name` is 2–255 characters. Hub/spoke ids are validated by the planner, not at
create time, so a topology can be prepared before its devices exist (the ids are
then dropped during planning).

### Deploying

```bash
# plan only: creates/updates tunnel rows, no device calls
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dry_run":true,"regenerate_keys":false}' \
  https://ofme.example.com/api/v1/sdwan/topologies/$TOPOLOGY_ID/deploy | jq

# apply
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"dry_run":false}' \
  https://ofme.example.com/api/v1/sdwan/topologies/$TOPOLOGY_ID/deploy | jq
```

Response:

```json
{
  "topology_id": "4c8f…",
  "tunnels_created": 2,
  "tunnels_updated": 0,
  "routes_installed": 2,
  "devices_configured": 2,
  "errors": []
}
```

`errors` contains one line per failed tunnel (`"<name>: <exception>"`); the
topology becomes `error` if any exist, `active` otherwise. A partial deployment
is therefore visible in the response and in the topology status, and the audit
entry `sdwan.topology_deployed` records created/updated/route counts and errors.

Behaviour worth knowing:

* Planned tunnels are matched to existing rows by `(topology_id, name)`. Renaming
  a device changes the generated tunnel name and therefore creates a new tunnel;
  the old one is left behind.
* `dry_run` still writes: tunnels and links are created/updated, keys may be
  rotated, and the transaction commits. It only skips the device call and route
  sync (`devices_configured = 0`). Use it to inspect the plan, not as a
  read-only preview.
* Route sync runs per successfully configured local device, so a failed tunnel
  leaves its routes uninstalled.
* There is no per-device concurrency: a large topology is applied sequentially in
  one request. An HTTP timeout does not cancel the work already committed per
  tunnel; the topology status reflects the last completed run.

### Device payload

For each planned tunnel the provisioner calls the device's OPNsense API:

```http
POST /api/wireguard/server/add
{"server": {
  "enabled": "1",
  "name": "<interface_name>",
  "pubkey": "<tunnel.public_key>",
  "port": "51820",
  "tunneladdress": "<comma-joined allowed_ips>",
  "peers": [{
    "enabled": "1",
    "name": "<tunnel.name[:30]>",
    "pubkey": "<tunnel.public_key>",
    "endpoint": "<endpoint_remote or ''>",
    "keepalive": "<keepalive>",
    "allowedips": "<comma-joined allowed_ips>"
  }]
}}
POST /api/wireguard/service/reconfigure
```

Credentials come from `DeviceService.credentials(device)` (the stored API key and
secret, TLS verified when `OPNsense_VERIFY_TLS=true`). Any non-2xx response
raises and is recorded as a tunnel error.

The same public key is used for the server and the peer because the peer's key
is not known to the controller; `tunneladdress` receives the peer's LAN CIDR
because no tunnel subnet is allocated. A working handshake therefore requires an
operator (or an external automation) to install the matching peer configuration
on the remote device. Treat the push as bootstrapping, not as a complete
two-sided provisioning (see limitations).

### IPsec and OpenVPN push

`_apply_to_device` dispatches on `protocol`, so an `ipsec` tunnel is written as a
phase-1 + phase-2 pair and `openvpn` as a peer-to-peer server instance:

| Protocol | OPNsense endpoints (in order) |
|---|---|
| `ipsec` | `POST /api/ipsec/phase1/add`, `POST /api/ipsec/phase2/add`, `POST /api/ipsec/service/reconfigure` |
| `openvpn` | `POST /api/openvpn/server/add`, `POST /api/openvpn/service/reconfigure` |

Phase 1 carries `remote`, `local`, `encryption`, `hash` and `lifetime`; phase 2
carries the tunnel network (`allowed_ips`, comma-joined), `pfs` and the same
algorithms. Absent values default to `aes256gcm16`/`sha256`/86400 s.

Operators can also drive IPsec directly, without planning a topology:

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/sdwan/devices/{device_id}/ipsec/tunnels` | `sdwan:read` | read the host's tunnel table |
| `POST` | `/api/v1/sdwan/devices/{device_id}/ipsec/tunnels` | `sdwan:write` | create phase 1 + phase 2 and reconfigure |
| `POST` | `/api/v1/sdwan/devices/{device_id}/ipsec/apply` | `sdwan:write` | re-run `reconfigure` (audited as `ipsec.reconfigure`) |

These calls are direct and synchronous, require stored device API credentials and
annotate the audit trail (`ipsec.tunnel_created`, `ipsec.reconfigure`). They do
not read or write `vpn_tunnels`, so a tunnel created through the endpoint is not
tracked by the planner.

### Graph

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  https://ofme.example.com/api/v1/sdwan/topologies/$TOPOLOGY_ID/graph | jq
```

```json
{
  "topology_id": "4c8f…",
  "name": "emea-hub-spoke",
  "type": "hub_spoke",
  "nodes": [
    {"id": "…", "name": "fra-hub", "role": "hub", "status": "online",
     "site": "Frankfurt", "latitude": 50.11, "longitude": 8.68},
    {"id": "…", "name": "vie-branch", "role": "spoke", "status": "online",
     "site": "Vienna", "latitude": 48.21, "longitude": 16.37}
  ],
  "edges": [
    {"id": "…", "source": "…", "target": "…", "status": "active",
     "health": "healthy", "latency_ms": 18.4, "loss_pct": 0.0,
     "label": "wg-vie-branch-to-fra-hub"}
  ],
  "generated_at": "2026-01-14T09:12:44Z"
}
```

Nodes are derived from the tunnels' endpoints (not from `hub_device_ids` alone),
so a topology with no tunnels renders an empty graph. `role` is `hub` when the id
appears in `hub_device_ids`, otherwise `spoke`. Edge telemetry is attached from
the link whose `tunnel_id` matches.

## Routing

`RouteManager.sync_routes(topology_id, device_id)` reads every tunnel where the
device is local **or** remote, keeps those of this topology, and for each entry in
`allowed_ips` upserts a route on that device:

| Field | Value |
|---|---|
| `destination` | the allowed IP/CIDR |
| `next_hop` | `tunnel.endpoint_remote` (often `null`) |
| `tunnel_id` | the tunnel |
| `metric` | 100 |
| `protocol` | `static` |
| `installed` | `tunnel.status == active` |
| `updated_at_dynamic` | now |

Because only the local side of a tunnel is planned, the "remote" branch of
`for_device` mainly matters for manually created tunnels; it can install a route
to the device's own LAN if a tunnel names it as remote.

Trigger a recompute without redeploying:

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  https://ofme.example.com/api/v1/sdwan/topologies/$TOPOLOGY_ID/routes/sync/$DEVICE_ID | jq
```

Withdrawing (`DELETE /sdwan/tunnels/{id}`) sets `installed=false` on the tunnel's
routes, clears their `tunnel_id` (so the tunnel row can be deleted), deletes the
tunnel and cascades its link, and commits. Routes remain in the table as
historical, uninstalled entries; nothing is pushed to the device by this call.

## Steering

`SteeringService.select_best_link(topology_id, strategy)` considers links that
are `status=active` **and** have at least one latency sample
(`latency_ms IS NOT NULL`). It then drops links that violate their SLA:

```text
latency_ms <= sla_latency_ms  AND  loss_pct <= sla_loss_pct
```

(unknown values are treated as passing). Among the survivors:

| Strategy | Selection |
|---|---|
| `lowest_latency` (default) | smallest `latency_ms` |
| `lowest_loss` | smallest `loss_pct` (missing loss counts as 100) |
| `lowest_cost` | smallest `(cost, latency_ms)` |
| `weighted` | largest `bandwidth_mbps / max(cost, 1)` |
| `application`, `failover`, anything else | smallest `(priority, latency_ms)` |

If no link passes, the result is `null` (HTTP 200 with `null`, not 404).

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  "https://ofme.example.com/api/v1/sdwan/topologies/$TOPOLOGY_ID/best-link?strategy=lowest_latency" | jq
```

### Failover evaluation

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  https://ofme.example.com/api/v1/sdwan/topologies/$TOPOLOGY_ID/failover | jq
```

For every enabled traffic policy, the service computes the best link for the
policy's strategy. If that link is **not** in the policy's
`preferred_link_ids`, it returns:

```json
[{
  "policy_id": "…",
  "previous_link_id": "…",
  "selected_link_id": "…",
  "reason": "sla_violation"
}]
```

`previous_link_id` is the first preferred link. The event is advisory: nothing
is reprogrammed, no route is switched, and no failover event is persisted.
`preferred_link_ids` does not constrain `select_best_link` — it only drives this
comparison. Enforcement is an operator decision (change the device routing, or
ingest measurements that make the preferred link win again).

## Link health

### Ingest

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"latency_ms":18.4,"jitter_ms":1.1,"loss_pct":0.0,"bandwidth_mbps":300,"status":"active"}' \
  https://ofme.example.com/api/v1/sdwan/links/$LINK_ID/measurements | jq
```

Body fields are all optional; supplied values overwrite, missing ones keep their
previous value. `loss_pct` is 0–100, the rest ≥ 0. `measured_at` is set to now.
When `status` changes, the linked tunnel's `status` is updated and
`TunnelStateChanged` is emitted; the tunnel's `health_status` is recomputed on
every ingest:

| Condition | `health_status` |
|---|---|
| link not `active` | `unhealthy` |
| latency and loss within SLA | `healthy` |
| within neither/both violated | `degraded` |

The event reaches WebSocket subscribers on topic `tunnels` as
`sdwan.tunnel_state_changed` with `{status, topology_id, aggregate_id, …}`.

### Scheduled sweep

`ofme.sdwan.health_sweep` runs every 5 minutes (`sdwan-health-sweep`):

* iterates tenants (or one, when a tenant id is passed), up to 200 topologies
  and 500 links per tenant;
* skips topologies whose status is exactly `draft`;
* calls `evaluate_failover` for the others and logs `sdwan.failover` per event;
* marks any `active` link whose `measured_at` is missing or older than
  `3 × HEARTBEAT_INTERVAL_SECONDS` (default 180 s) as `down`, which flips the
  tunnel and emits `sdwan.tunnel_state_changed`. `pending` links are skipped.

There is no built-in active prober: telemetry arrives only through the API (or
your own collector posting to it). An agent heartbeat does not populate link
metrics in this release. If nothing posts measurements, links go stale and the
sweep marks them down — that is visible in the UI and in tunnel events.

## Traffic policies

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
        "topology_id": "'$TOPOLOGY_ID'",
        "name": "voice-preferred",
        "description": "Voice over the lowest-latency path",
        "strategy": "lowest_latency",
        "match": {"destination_port": 5060, "protocol": "udp"},
        "preferred_link_ids": ["'$PRIMARY_LINK_ID'"],
        "priority": 10,
        "enabled": true
      }' \
  https://ofme.example.com/api/v1/sdwan/traffic-policies | jq
```

`match` is stored verbatim and is not interpreted by `SteeringService`; the
strategy applies to the whole topology. `priority` orders the list endpoint
(ascending). `enabled=false` removes the policy from failover evaluation.

## Permissions

| Permission | Roles (see SECURITY.md) |
|---|---|
| `sdwan:read` | all roles (included in `READ_ONLY`) |
| `sdwan:write` | Admin, TenantAdmin, SuperAdmin |
| `sdwan:deploy` | Admin, TenantAdmin, SuperAdmin |

Operator and Auditor are read-only for SD-WAN. Deployment is separated from
editing so that the write permission alone does not push configuration to
devices.

## UI

`/sdwan` has four tabs, scoped to the selected topology:

1. **Topologies** — table (name, type, status, hubs/spokes), create/edit dialogs,
   graph viewer, deploy action, delete.
2. **Tunnels** — per-topology tunnel list with local/remote device, status,
   health, allowed IPs; delete (withdraw).
3. **WAN links** — link inventory with latency/loss/bandwidth, SLA thresholds and
   a measurement dialog.
4. **Steering** — traffic policies with strategy, priority, preferred links;
   create/delete.

The header shows topology, tunnel, link and policy counts. Data comes from the
REST API through TanStack Query; live tunnel state arrives on the `tunnels`
WebSocket topic if the page subscribes to it.

## End-to-end example

```bash
API=https://ofme.example.com/api/v1
AUTH="Authorization: Bearer $TOKEN"
HUB=$(curl -fsS -H "$AUTH" "$API/devices?search=fra-hub" | jq -r '.items[0].id')
SPOKE=$(curl -fsS -H "$AUTH" "$API/devices?search=vie-branch" | jq -r '.items[0].id')

TOPOLOGY=$(curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"emea","topology_type":"hub_spoke",
       "hub_device_ids":["'$HUB'"],"spoke_device_ids":["'$SPOKE'"],
       "configuration":{"wan_interface":"wan"}}' \
  "$API/sdwan/topologies" | jq -r .id)

# plan, inspect, then apply
curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"dry_run":true}' "$API/sdwan/topologies/$TOPOLOGY/deploy" | jq
curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"dry_run":false}' "$API/sdwan/topologies/$TOPOLOGY/deploy" | jq

# confirm the graph and routes
curl -fsS -H "$AUTH" "$API/sdwan/topologies/$TOPOLOGY/graph" | jq '.edges'
curl -fsS -H "$AUTH" "$API/sdwan/topologies/$TOPOLOGY/routes" | jq '.[] | {device_id,destination,installed}'

# feed telemetry and pick a path
LINK=$(curl -fsS -H "$AUTH" "$API/sdwan/links?topology_id=$TOPOLOGY" | jq -r '.items[0].id')
curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"latency_ms":17.2,"jitter_ms":0.8,"loss_pct":0.0,"bandwidth_mbps":500,"status":"active"}' \
  "$API/sdwan/links/$LINK/measurements" | jq '{latency_ms,status}'
curl -fsS -H "$AUTH" "$API/sdwan/topologies/$TOPOLOGY/best-link?strategy=lowest_latency" | jq
```

## Known limitations

Verified against the implementation; they define the supported scope:

* **One direction per pair.** The planner emits only the local side. There is no
  reverse tunnel, no per-device key registry, and the peer entry reuses the local
  public key. A complete WireGuard handshake requires the remote side to be
  configured separately. `regenerate_keys` rotates the stored key without
  distributing it.
* **No tunnel addressing.** `tunneladdress` receives the peer's LAN CIDR; no
  point-to-point `/31`/`/32` allocation exists. Interface addresses must be
  chosen and applied out of band.
* **No idempotency on the device side.** Re-deploying a topology appends new
  WireGuard servers, IPsec phase-1/2 entries and OpenVPN instances instead of
  updating the ones created by the previous run; OPNsense generates the object
  ids, so the controller cannot address them afterwards. Clean up duplicates on
  the appliance before a re-deploy, or use the direct IPsec endpoints with
  operator-chosen names.
* **Hub-and-spoke uses one hub**; additional hubs are ignored by the planner.
* **Regional hub distance is approximate**: missing coordinates collapse to 0 and
  make the first hub win.
* **`dry_run` is not read-only**: it persists tunnels/links and may rotate keys.
* **Steering is advisory.** `select_best_link` and `evaluate_failover` return
  decisions; they do not reprogram routes or devices. `preferred_link_ids` does
  not constrain selection. `application` and `failover` strategies fall back to
  priority order.
* **No active probing.** Link metrics must be posted to
  `/links/{id}/measurements`; the agent heartbeat does not provide them. Active
  links without a fresh sample are marked `down` by the sweep after 3× the
  heartbeat interval.
* **No bandwidth/QoS enforcement.** `bandwidth_mbps` participates only in the
  `weighted` score.
* **`match` is documentation.** Traffic policies are not compiled into firewall
  or shaping rules; `/api/v1` has no QoS module.
* **Deployment is synchronous** and per-tunnel sequential. Very large topologies
  should be split by region/site.
* **Existing tunnels are only partially reconciled**: a redeploy updates
  `allowed_ips` (and keys with `regenerate_keys`); `wan_interface`, endpoints,
  keepalive, MTU and the associated link's cost/priority are not updated, and a
  link row is never refreshed after creation.
* **No topology versioning or rollback.** A deploy mutates the tunnel rows in
  place; to revert, redeploy the previous hub/spoke sets or restore the database.
* Audit coverage is partial: topology create and deploy are audited; tunnel
  create/delete, route sync, measurements and traffic-policy CRUD are not.
