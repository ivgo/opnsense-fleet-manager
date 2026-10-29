# os-fleet-agent

OPNsense plugin for **OPNsense Fleet Manager Enterprise (OFME)**.

The plugin turns an OPNsense firewall into a managed fleet member. It connects
outbound to the OFME control plane, authenticates with a locally generated
X.509 device key, publishes telemetry, polls for a fixed set of operational
commands and can apply centrally managed aliases and firewall rules.

No inbound management port is opened on the firewall.

## Components

| Path | Purpose |
| --- | --- |
| `src/opnsense/scripts/OPNsense/FleetAgent/agent.php` | CLI and daemon entry point |
| `src/opnsense/mvc/app/library/OPNsense/FleetAgent/` | Agent implementation |
| `src/opnsense/mvc/app/controllers/OPNsense/FleetAgent/` | Web UI and API controllers |
| `src/opnsense/mvc/app/models/OPNsense/FleetAgent/` | Settings model, form, menu and ACL |
| `src/opnsense/mvc/app/views/OPNsense/FleetAgent/index.volt` | Status and configuration page |
| `src/etc/rc.d/os-fleet-agent` | rc(8) service wrapper |
| `src/etc/inc/plugins.inc.d/fleetagent.inc` | OPNsense service registration |
| `src/etc/inc/priv/ofme.priv.inc` | Privilege definition |
| `src/opnsense/service/conf/actions.d/actions_ofme.conf` | configd actions |

Runtime locations:

| Path | Mode | Content |
| --- | --- | --- |
| `/usr/local/etc/ofme-agent/` | `0700` | Agent configuration directory |
| `/usr/local/etc/ofme-agent/device.key` | `0600` | RSA-2048 private key (never leaves the firewall) |
| `/usr/local/etc/ofme-agent/device.crt` | `0644` | Device certificate |
| `/usr/local/etc/ofme-agent/ca.crt` | `0644` | Pinned OFME platform CA |
| `/usr/local/etc/ofme-agent/state.json` | `0600` | Timestamps, counters and command-result queue |
| `/usr/local/etc/ofme-agent/managed.json` | `0600` | Last applied configuration hash and managed object UUIDs |
| `/usr/local/etc/ofme-agent/desired.json` | `0600` | Last fetched desired configuration |
| `/usr/local/etc/ofme-agent/apply-report.json` | `0600` | Last apply report |
| `/usr/local/etc/ofme-agent/diagnostics/` | `0700` | Bounded diagnostics bundles |
| `/var/log/ofme-agent.log` | `0640` | Structured JSON log, rotated at 5 MiB |
| `/var/run/os_fleet_agent.pid` | `0644` | PID file |
| `/var/run/ofme-agent.lock` | `0600` | Exclusive daemon lock |

Secrets are never written to `config.xml`, so an OPNsense configuration backup
does not contain the device private key or the enrollment token after
enrollment.

## Installation

The plugin uses the OPNsense ports build system.

```sh
cd /usr/ports/security/os-fleet-agent
make install
```

For a development build:

```sh
cd plugin/os-fleet-agent
make package
pkg install -y work/pkg/os-fleet-agent-1.0.0.pkg
```

After installation:

1. Open **Services → OFME Fleet Agent**.
2. Enter the **Platform URL**, for example `https://ofme.example.com`.
3. Create a one-time enrollment token in OFME under **Zero-touch provisioning**
   and paste it into **Enrollment token**.
4. Save the settings.
5. Click **Enroll**. The agent generates an RSA key and CSR locally, sends the
   CSR to OFME, verifies that the returned certificate matches the key and is
   signed by the returned CA, then installs the certificate.
6. Enable **Apply managed aliases** and/or **Apply managed firewall rules** when
   the firewall should enforce centrally managed policy.
7. Enable the service and start it.

The agent removes the enrollment token from `config.xml` after a successful
enrollment.

## Configuration

| Field | Default | Meaning |
| --- | --- | --- |
| `enabled` | `0` | Run the supervised service |
| `platform_url` | `https://ofme.example.com` | Control-plane base URL |
| `enrollment_token` | empty | One-time token, cleared after enrollment |
| `heartbeat_interval` | `60` | Telemetry interval, clamped to 15–3600 s |
| `config_interval` | `300` | Desired-configuration poll interval, clamped to 60–86400 s |
| `renew_before_days` | `30` | Request renewal when the certificate lifetime drops below this value |
| `request_timeout` | `20` | Connect/read timeout, clamped to 5–120 s |
| `verify_tls` | `1` | Verify the platform TLS certificate |
| `proxy_url` | empty | Optional HTTP(S) proxy |
| `apply_aliases` | `0` | Write managed aliases |
| `apply_firewall_rules` | `0` | Write managed firewall rules |
| `log_level` | `info` | `info`, `warning` or `debug` |

The enrollment token is a bootstrap secret. It is accepted only through an
`https://` URL, is sent to `/api/v1/agent/bootstrap` and
`/api/v1/agent/enroll`, and is deleted from the configuration after success.

## Managed-object marker

Only objects whose OPNsense description starts with the marker **`OFME-`** are
created, modified or deleted by the agent. The trailing hyphen is required:
OPNsense replaces `:` in description fields with a space, which would make the
marker ambiguous.

* Aliases are applied first.
* Firewall rules are applied second.
* Aliases that are no longer desired are pruned last, after managed rules have
  been removed, and only when they are not referenced by any other OPNsense
  object.
* OPNsense validation failures are caught and reported; a failed rule never
  prevents the previous rule set from remaining active.
* `filter reload` and `filter refresh_aliases` run after a change.

NAT, interfaces, routes, VLANs, VPN and SD-WAN data are **never** written by
the agent. They are fetched for comparison and reported as drift.

## Commands

The platform can queue the following fixed commands. There is no generic shell
execution.

| Action | Effect |
| --- | --- |
| `noop` | No side effects, used for round-trip tests |
| `ping` | Return agent version, hostname and uptime |
| `sync_config` | Force a desired-configuration synchronisation |
| `renew_certificate` | Renew and install the device certificate |
| `restart_agent` | Restart the service after the result is reported |
| `collect_diagnostics` | Write a diagnostics bundle |
| `reload_firewall` | Run `filter reload` |
| `update_telemetry` | Force a heartbeat on the next cycle |

Results are stored locally (last 100) and sent in the next heartbeat as
`command_results`. They are removed from the local queue once the platform has
accepted the heartbeat. The agent ignores commands returned in the heartbeat
response and polls `/api/v1/agent/commands` instead, which prevents duplicate
execution.

## CLI

```sh
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php status
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php once --force
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php preview
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php sync --force
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php diagnostics
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php renew
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php test
/usr/local/bin/php /usr/local/opnsense/scripts/OPNsense/FleetAgent/agent.php command ping
```

All commands print one JSON document. `reset` removes the key, certificate, CA
and local state; it requires an explicit confirmation in the UI.

## Service management

```sh
service os_fleet_agent start
service os_fleet_agent status
service os_fleet_agent restart
service os_fleet_agent stop
```

configd actions are exposed as `ofme start`, `ofme stop`, `ofme restart`,
`ofme status` and `ofme agent.*` for the UI.

## Security properties

* The private key is generated on the firewall and is never sent to OFME.
* The issued certificate must match the local key and be signed by the returned
  CA before it is installed.
* If the bootstrap package advertises `platform.ca_fingerprint`, the installed CA
  must match it.
* The agent uses certificate pinning through `/usr/local/etc/ofme-agent/ca.crt`.
* TLS verification is enabled by default and can only be disabled explicitly.
* The daemon holds an exclusive `flock` and validates the PID file, so duplicate
  instances cannot run.
* Commands and configd actions are whitelisted; no user-controlled shell string
  is executed.
* Aliases and rules outside the `OFME-` marker are never modified.
* Logs and diagnostics do not include the private key or the enrollment token.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `not enrolled` | Token saved, platform URL reachable, `test` succeeds |
| `401` or `403` from platform | Device certificate fingerprint is known to OFME; re-enroll if the device was reset |
| TLS errors | Import the platform CA, keep `verify_tls` enabled |
| Service stops immediately | `/var/log/ofme-agent.log` and `service os_fleet_agent status` |
| Configuration not applied | `preview` output, `apply_aliases` / `apply_firewall_rules` switches, `apply-report.json` |
| Alias not pruned | It is still referenced by a non-managed rule; the conflict is listed in the preview |
| Enrollment CA mismatch | The platform changed its CA; reset and re-enroll, or import the new CA before enrolling |

The diagnostics bundle contains status, settings, telemetry, system information,
the apply report and the last 200 log lines. It does not contain the private key.
