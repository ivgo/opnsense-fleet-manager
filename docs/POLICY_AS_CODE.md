# Policy as code

A policy is a YAML document stored in OFME, optionally mirrored from a Git
repository, that is validated, reviewed, deployed to devices and continuously
compared with their live configuration.

The implementation lives in `backend/app/services/gitops.py` (validation,
compilation, diff, deployment, drift, change requests, promotion) and
`backend/app/services/git_sync.py` (Git providers, sync, webhooks). The API
surface is `/api/v1/policies`, `/api/v1/deployments`, `/api/v1/drift`,
`/api/v1/changes` and `/api/v1/git`.

## The policy record

| Field | Meaning |
|---|---|
| `name` | unique per `(tenant, environment)` |
| `kind` | `firewall`, `nat`, `vlan`, `vpn`, `interface`, `routing`, `compliance` |
| `environment` | `development`, `testing`, `staging`, `production` |
| `path` | file path inside the linked Git repository |
| `content` | the YAML document(s) |
| `content_hash` | SHA-256 of `content`; drives "unchanged" detection during sync |
| `version` | incremented on every content change |
| `status` | lifecycle state (below) |
| `target_selector` | which devices a deployment applies to |
| `validation_errors` | errors from the last validation (persisted for the UI) |
| `validated_at` | timestamp of the last validation |

Changing `content` resets the policy to `draft`, clears `validation_errors` and
increments `version`. Editing metadata (description, selector) does not.

## Document format

```yaml
apiVersion: fleet.opnsense.io/v1
kind: FirewallPolicy
metadata:
  name: branch-edge
  environment: production
  description: Standard branch firewall
  labels:
    owner: network-team
spec: {}
```

Rules:

* `apiVersion` must be exactly `fleet.opnsense.io/v1`.
* `kind` must be one of `FirewallPolicy`, `NatPolicy`, `VlanPolicy`,
  `VpnPolicy`, `CompliancePolicy`.
* `metadata.name` is required (it is validated, not used as the record key).
* `spec` must be a mapping.
* A file may contain multiple documents separated by `---`; every document is
  validated independently.

### FirewallPolicy

```yaml
apiVersion: fleet.opnsense.io/v1
kind: FirewallPolicy
metadata:
  name: branch-edge
spec:
  default_action: block
  rules:
    - name: allow-web-in
      action: pass
      direction: in
      interface: wan
      protocol: tcp
      source: any
      destination: 10.10.20.10
      destination_port: "443"
      log: true
      description: Public web front end
      tags: [web, tier-1]

    - name: allow-dns-out
      action: pass
      direction: out
      interface: lan
      protocol: udp
      source: 10.10.20.0/24
      destination: 10.10.20.1
      destination_port: "53"

    - name: block-rfc1918-in
      action: block
      direction: in
      interface: wan
      source: 10.0.0.0/8
```

Per-rule fields: `name`, `action` (`pass|block|reject`), `direction`
(`in|out`), `interface`, `protocol`, `source`, `destination`,
`destination_port`, `source_port`, `log`, `description`, `tags`.

Compilation produces OPNsense rule attributes in a deterministic order:

```json
{
  "enabled": "1",
  "action": "pass",
  "direction": "in",
  "interface": "wan",
  "protocol": "tcp",
  "source_net": "",
  "destination_net": "10.10.20.10",
  "destination_port": "443",
  "source_port": "",
  "descr": "Public web front end",
  "log": "1",
  "sequence": "10"
}
```

`sequence` is `(index + 1) * 10`, so ordering is explicit and stable. `any`
becomes an empty source/destination (OPNsense semantics). `default_action` is
validated but is not encoded as a rule: unmatched traffic follows the device's
own default (block), which is the OPNsense default.

### NatPolicy

```yaml
apiVersion: fleet.opnsense.io/v1
kind: NatPolicy
metadata:
  name: branch-nat
spec:
  rules:
    - name: web-forward
      type: port_forward
      interface: wan
      protocol: tcp
      destination: 203.0.113.10
      destination_port: 443
      target: 10.10.20.10
      target_port: 443

    - name: lan-outbound
      type: outbound
      interface: wan
      protocol: any
      source: 10.10.20.0/24
      target: wan-address
```

`type` is `port_forward`, `outbound` or `one_to_one`.

### VlanPolicy

```yaml
apiVersion: fleet.opnsense.io/v1
kind: VlanPolicy
metadata:
  name: branch-vlans
spec:
  vlans:
    - vlan_id: 20
      parent_interface: igb1
      description: Users
    - vlan_id: 30
      parent_interface: igb1
      description: Voice
```

`vlan_id` is constrained to 1–4094.

### VpnPolicy

```yaml
apiVersion: fleet.opnsense.io/v1
kind: VpnPolicy
metadata:
  name: branch-wireguard
spec:
  protocol: wireguard
  interface: wg0
  listen_port: 51820
  address: 10.99.0.2/24
  peers:
    - name: hub
      public_key: 3G0f8k...=
      allowed_ips: [10.99.0.0/24, 10.10.0.0/16]
      endpoint: vpn.example.com:51820
      keepalive: 25
```

`protocol` is `wireguard`, `ipsec` or `openvpn`. Duplicate peer public keys are
rejected.

### CompliancePolicy

`kind: CompliancePolicy` maps to the `compliance` policy kind. It is stored,
validated for structure and versioned like the others; controls are evaluated by
the compliance engine (`/api/v1/compliance`), not compiled into device
configuration.

## Validation

`POST /api/v1/policies/{id}/validate` (permission `policy:validate`) runs the
validator, persists the result and moves the policy to `validated` or back to
`draft`.

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/policies/$POLICY_ID/validate | jq
```

Response:

```json
{
  "valid": false,
  "errors": [
    {
      "severity": "error",
      "code": "permit_any_without_justification",
      "message": "Rule 'allow-all' permits any/any without a description",
      "path": "spec.rules[2]",
      "line": null,
      "remediation": "Restrict source/destination or document the exception"
    }
  ],
  "warnings": [],
  "rule_count": 3,
  "conflict_count": 0,
  "compiled": { "firewall": [ ... ] }
}
```

### Codes

| Code | Severity | Cause |
|---|---|---|
| `yaml_syntax` | error | YAML cannot be parsed; `line` points at the problem mark |
| `empty_document` | error | no documents in the file |
| `invalid_document` | error | a document is not a mapping |
| `unsupported_api_version` | error | `apiVersion` is not `fleet.opnsense.io/v1` |
| `unsupported_kind` | error | `kind` is not one of the five |
| `missing_name` | error | `metadata.name` absent |
| `missing_spec` | error | `spec` absent or not a mapping |
| `schema_error` | error | field-level validation (wrong type, bad enum, port range) |
| `duplicate_rule` | error | two rules share a name |
| `permit_any_without_justification` | error | `pass` with `source: any` **and** `destination: any` and no description |
| `duplicate_peer_key` | error | repeated WireGuard public key |
| `permit_any` | warning | any/any pass that is documented |
| `tcp_without_port` | warning | `protocol: tcp` with no `destination_port` |
| `duplicate_effective_rule` | warning | two pass rules with the same interface, protocol, source and destination |
| `kind_mismatch` | warning | the record's `kind` differs from the document's `kind` |

Errors block deployment; warnings do not. `conflict_count` counts
`duplicate_effective_rule` findings.

## Lifecycle

```
draft ──► validated ──► review ──► approved ──► deployed ──► draft
  │            │            │           │           │
  └────────────┴────────────┴───────────┴───────────┴──► archived
```

Allowed transitions (enforced by `PolicyService._assert_transition`):

| From | To |
|---|---|
| `draft` | `validated`, `archived` |
| `validated` | `review`, `approved`, `archived` |
| `review` | `approved`, `draft`, `archived` |
| `approved` | `deployed`, `archived` |
| `deployed` | `draft`, `archived` |
| `archived` | – (terminal) |

Set a status through `PATCH /api/v1/policies/{id}` with `{"status": "review"}`.
Illegal transitions return 400. A deployed policy cannot be deleted — archive it
first (`PATCH` to `archived`, then `DELETE`).

Validation is authoritative: a successful validation sets `validated`; a failed
one returns the policy to `draft` and stores the errors.

## Diff

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/policies/$POLICY_ID/diff" \
  --get --data-urlencode "against@previous.yaml" | jq
```

`against` is a YAML string (omit it to diff against an empty document). The
engine walks both trees and emits one entry per added, removed or modified leaf:

```json
{
  "policy_id": "…",
  "base_version": 0,
  "target_version": 7,
  "entries": [
    { "path": "rules[1].destination_port", "change": "modified", "before": "80", "after": "443" },
    { "path": "rules[2]", "change": "added", "before": null, "after": { "name": "allow-dns" } }
  ],
  "summary": "2 change(s): 1 added, 0 removed, 1 modified"
}
```

Array indices are positional, so an inserted rule shows up as a series of
modifications followed by an addition. Read the diff with the order in mind.

## Simulation

`POST /api/v1/policies/{id}/simulate` evaluates a synthetic packet against the
policy's firewall rules in document order and returns the first match:

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"source_ip":"198.51.100.7","destination_ip":"10.10.20.10","protocol":"tcp","destination_port":443,"interface":"wan"}' \
  http://localhost:8000/api/v1/policies/$POLICY_ID/simulate | jq
```

```json
{
  "matched": true,
  "action": "pass",
  "rule_name": "allow-web-in",
  "rule_index": 0,
  "evaluated": 1,
  "shadowed_rules": ["allow-dns-out", "block-rfc1918-in"]
}
```

* `matched: false` means no rule matched; the effective action is `block`
  (OPNsense default).
* `shadowed_rules` lists the rules after the matching pass that can no longer be
  reached for this packet — useful for finding dead policy.
* Interface, protocol, source, destination and port are honoured; address
  matching accepts CIDR (`10.0.0.0/8`), `any`, and ports accept `443`,
  `8000-8100` and comma lists.

## Deployment

`POST /api/v1/policies/{id}/deploy` (permission `policy:deploy`):

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"device_ids":[],"dry_run":false,"change_request_id":null}' \
  http://localhost:8000/api/v1/policies/$POLICY_ID/deploy | jq
```

Body fields: `device_ids` (empty = resolve through `target_selector`), `dry_run`,
`change_request_id`.

### Target resolution

When `device_ids` is empty, `target_selector` is applied:

```json
{ "site_id": "…", "group_id": "…", "tags": ["branch", "emea"], "all": true }
```

* `site_id` and `group_id` filter the tenant's devices;
* `tags` requires **all** listed tags (`required.issubset(tags)`);
* `all: true` returns everything that passed the other filters;
* without `all`, the filtered set is still returned — the flag documents intent
  rather than changing the query. Always use `dry_run: true` first to see the
  target list in `plan.targets`.

### Preconditions

1. The policy must pass validation (errors abort with 422 and the issue list).
2. In `production`, a non-dry-run deployment **requires** an approved change
   request whose approvals meet `required_approvals`; without it the call fails
   with 400.
3. Every targeted device must belong to the tenant (`get_or_404` per id).

### What happens

1. A `PolicyDeployment` row is created in `validating` with a plan containing the
   compiled rules, target ids, warnings and `dry_run`.
2. For `firewall` policies, `ConfigurationDeployer.deploy_rules` pushes the rules
   to each device (unless `dry_run`), and per-device results are recorded.
   `dry_run` records `{"success": true, "dry_run": true}` without touching the
   device.
3. On success, the documented `firewall_rules` rows for each target are replaced
   (old rows soft-deleted, new rows linked through `source_policy_id`) so the
   database reflects the desired state.
4. The deployment becomes `completed` (no failures) or `failed` (any device
   error), `completed_at` and `logs` (first 20 000 chars of the results) are set.
5. On a non-dry-run success the policy moves to `deployed` and a linked change
   request moves to `applied`.
6. An audit entry (`policy.deployed`) and a `PolicyDeployed` domain event are
   emitted.

`nat`, `vlan`, `vpn`, `interface`, `routing` and `compliance` policies produce a
validated, versioned plan and a deployment record, but this release only pushes
`firewall` policies to devices. The other kinds are the desired state consumed by
the corresponding CRUD module (`/api/v1/nat`, `/api/v1/interfaces`, …) and the
compliance engine; applying them device-side is a separate configuration
operation.

### Deployment statuses

`pending` → `validating` → `deploying` → `completed` | `failed` | `rolled_back`.

`POST /api/v1/deployments/{id}/rollback` (permission `policy:rollback`) marks a
deployment `rolled_back`, requires an earlier successful deployment to exist, and
records the decision in the audit trail. It does **not** re-push the earlier
configuration: to restore device state, re-deploy the previous policy content
(from Git or a backup) or restore the device configuration backup. Treat the
endpoint as "this change is withdrawn" plus bookkeeping, not as an automatic
revert.

### Reading a deployment

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/deployments?policy_id=$POLICY_ID&size=20" | jq '.items[0]'
```

`results` is a list of `{device_id, success, …}`; a failure carries `error`
verbatim from the device client, which is what you paste into an incident.

## Drift

`DriftService.scan` compares, for every device (or an explicit list):

* the device's live firewall rules (`search_rules()` through the OPNsense API);
* the documented rules in OFME (`firewall_rules` for that device);
* the newest deployed firewall policy as the desired state.

Differences are summarised per object; one open report per device is maintained
(`open_for_device`) rather than a report per scan. An unreachable device is
logged (`drift.device_unreachable`) and its rules compare as empty — that is
recorded as drift, not silently ignored.

```bash
# scan everything (scheduled every 30 minutes as ofme.policies.drift_scan)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"device_ids":[]}' http://localhost:8000/api/v1/drift/scan | jq

# triage
curl -fsS -H "Authorization: Bearer $TOKEN" \
  'http://localhost:8000/api/v1/drift?status=open&size=50' | jq '.items[] | {device_id, detected_at, differences}'

# resolve after remediation
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"notes":"manually aligned, ticket OPS-4711"}' \
  http://localhost:8000/api/v1/drift/$DRIFT_ID/resolve | jq
```

Drift statuses: `open`, `acknowledged`, `remediated`, `ignored`. The open count
feeds `ofme_policy_drift_findings` and the `OFMEPolicyDriftHigh` alert (> 25 for
one hour).

## Change control

Production deployments require an approved change request. The object is generic
enough for other operations (config, VPN, template):

```bash
# open
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
        "title": "Publish branch-edge v8",
        "type": "policy",
        "resource_type": "Policy",
        "resource_id": "'$POLICY_ID'",
        "payload": {"policy_id": "'$POLICY_ID'"},
        "priority": "high",
        "environment": "production",
        "required_approvals": 2,
        "expires_in_hours": 72
      }' \
  http://localhost:8000/api/v1/changes | jq

# approve (a different user, permission change:approve)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"comment":"reviewed the diff"}' \
  http://localhost:8000/api/v1/changes/$CHANGE_ID/approve | jq
```

Statuses: `pending`, `approved`, `rejected`, `applied`, `expired`, `cancelled`.
`required_approvals` is 1–5 (promotion to production creates a request with 2).
`approvals` is a list of `{user_id, comment, at}`; the deployment checks the
count, not the identities, so enforce "different person" through process/RBAC
(the approver needs `change:approve`, which is not implied by `policy:write`).

`expires_at` is advisory: the deployment path does not reject expired requests.
Cancel stale requests explicitly.

## Git integration

### Connecting a repository

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
        "name": "fleet-policies",
        "provider": "github",
        "url": "https://github.com/acme/fleet-policies.git",
        "default_branch": "main",
        "auth_type": "token",
        "token": "ghp_…",
        "auto_sync": true,
        "sync_interval_minutes": 60
      }' \
  http://localhost:8000/api/v1/git/repositories | jq
```

Providers: `github`, `gitlab`, `azure_devops`, `generic`. Auth: `token`, `ssh`,
`oauth`. The token/PAT is encrypted at rest and never returned.

### Importing and syncing

1. `POST /api/v1/git/repositories/{id}/import` with `{path, name, kind,
   environment, …}` creates a policy bound to that file (`repo_id` + `path`).
2. `POST /api/v1/git/repositories/{id}/sync` (or the `auto_sync` schedule, or a
   webhook) reads the head commit, fetches each linked file and compares its
   SHA-256 with `content_hash`.
3. Changed files are validated and stored with `version += 1`; invalid files are
   stored **and** flagged (`validation_errors`, status back to `draft`) so the
   failure is visible, not silently skipped. Missing files and provider errors
   are reported per path in the sync result.
4. Unchanged files are counted, not rewritten.

Sync result:

```json
{
  "repository_id": "…",
  "commit": "2f1c…",
  "updated": 3,
  "unchanged": 12,
  "invalid": 1,
  "errors": ["policies/branch-edge.yaml: 404 on main"]
}
```

### Publishing

`POST /api/v1/git/policies/{id}/publish` writes the current content back to the
policy's `path` on the default branch and commits with
`GIT_COMMIT_AUTHOR`. Use it for "edit in UI, commit for review" workflows; the
Git commit is the review artefact, not the platform record.

### Webhooks

`POST /api/v1/git/webhooks/{repository_id}` (no bearer auth; validated by
signature):

| Provider | Header | Validation |
|---|---|---|
| GitHub | `X-Hub-Signature-256` | HMAC-SHA256 of the raw body with the repository webhook secret |
| GitLab | `X-Gitlab-Token` | constant-time equality with the secret |
| Generic/Azure | `X-OFME-Signature` | equality with the secret |

If no secret is configured, the endpoint accepts unsigned calls — configure one
(`POST /api/v1/git/repositories/{id}/webhook-secret` rotates and returns it).
The branch is taken from `payload.ref` (`refs/heads/x` → `x`), falling back to
the default branch. Every webhook writes a `git.webhook_received` audit entry.

## Promotion between environments

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"source_environment":"staging","target_environment":"production","create_change_request":true}' \
  http://localhost:8000/api/v1/policies/$POLICY_ID/promote | jq
```

* The source policy must be in `approved`, `deployed` or `validated` and its
  `environment` must match `source_environment`.
* The target is created (status `validated`) or overwritten with the source
  content (`version += 1`, status `validated`).
* Moving to `production` with `create_change_request=true` opens a change request
  requiring **2** approvals.
* Promotion copies content, hash and selector; it does not deploy. Deployment is
  a separate, audited action.

Recommended flow:

```
feature branch ─► PR review ─► merge to main
      │                           │
      │                     webhook / sync
      ▼                           ▼
  environment: development ──► testing ──► staging ──► production
                                   validate   simulate   change request
                                                          │
                                                     deploy (dry-run, then apply)
```

## End-to-end example

```bash
API=http://localhost:8000/api/v1
AUTH="Authorization: Bearer $TOKEN"

# 1. create
POLICY=$(curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"branch-edge","kind":"firewall","environment":"staging","content":"'"$(cat branch-edge.yaml | sed 's/"/\\"/g' | tr '\n' ' ')"'"}' \
  $API/policies | jq -r .id)

# 2. validate
curl -fsS -X POST -H "$AUTH" $API/policies/$POLICY/validate | jq '.valid, .errors'

# 3. diff against what is deployed conceptually
curl -fsS -H "$AUTH" "$API/policies/$POLICY/diff" | jq '.summary'

# 4. simulate a packet
curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"source_ip":"198.51.100.7","destination_ip":"10.10.20.10","destination_port":443}' \
  $API/policies/$POLICY/simulate | jq

# 5. dry run on the selector
curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"dry_run":true}' $API/policies/$POLICY/deploy | jq '.status, .target_device_ids'

# 6. review → approve
curl -fsS -X PATCH -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"status":"review"}' $API/policies/$POLICY | jq .status
curl -fsS -X PATCH -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"status":"approved"}' $API/policies/$POLICY | jq .status

# 7. production: change request, approval, deploy
CHANGE=$(curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"title":"deploy branch-edge","type":"policy","resource_type":"Policy","resource_id":"'$POLICY'","environment":"production","required_approvals":2}' \
  $API/changes | jq -r .id)
# (second user approves twice / two approvers)
curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' -d '{}' $API/changes/$CHANGE/approve >/dev/null
curl -fsS -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"change_request_id":"'$CHANGE'"}' $API/policies/$POLICY/deploy | jq '.status, .results'
```

## Authoring conventions

* One file per policy, named after `metadata.name` (`branch-edge.yaml`).
* Keep environments in separate branches or directories and promote through the
  API, not by copying YAML between records.
* Every `pass` rule needs a description; any/any without one is an error by
  design.
* Order matters: put specific permits before broad blocks, and use `simulate` to
  prove reachability.
* Name rules uniquely across a policy; `duplicate_rule` is a hard error.
* Prefer `tags` on rules and selectors — they survive renames better than ids.
* Validate locally in CI by calling `/validate` against staging; the same
  validator runs in the API.
* Do not hand-edit `firewall_rules` rows that carry `source_policy_id`: the next
  deployment replaces them.

## Known limitations

* Only `FirewallPolicy` is pushed to devices; the other kinds are validated,
  versioned and tracked but applied through their own modules.
* Deployment is synchronous per request; a large fleet makes the HTTP call long.
  Use `dry_run` to size the change and deploy per site for very large targets.
* `rollback` marks state and audits; it does not re-apply the previous rules.
* Policy content history is not stored in the database (only the current content
  and version). Git — or the deployment `plan`/`logs` — is the history.
* The diff endpoint compares against a YAML string supplied by the caller; it
  does not read the previous version from a version store.
