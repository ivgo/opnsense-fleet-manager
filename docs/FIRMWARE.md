# Firmware lifecycle

OFME can read the OPNsense release inventory of a managed appliance and trigger an
in-place upgrade or a reboot. The control plane never executes shell commands on
either side: every operation is an OPNsense REST call made with the device's
stored API key/secret.

## Endpoints

| Method | Path | Permission | Status |
|---|---|---|---|
| `GET` | `/api/v1/devices/{device_id}/firmware/status` | `firmware:read` | 200 |
| `POST` | `/api/v1/devices/{device_id}/firmware/upgrade` | `firmware:upgrade` | 202 |
| `POST` | `/api/v1/devices/{device_id}/firmware/reboot` | `firmware:reboot` | 202 |

`firmware:read` is part of `ReadOnly`; upgrade and reboot are granted to
`Operator` and above (`TenantAdmin`/`Admin` inherit both). A `ReadOnly` or
`Auditor` principal receives `403`.

## Status probe

`GET .../firmware/status` reads two OPNsense endpoints and merges them:

* `GET /api/core/firmware/status` — running `product_version`, product name and
  series;
* `GET /api/core/firmware/info` — the `latest` release and the host's own
  `upgrade_available` flag.

The response also carries the version OFME recorded (`current_version`, updated by
the agent heartbeat and by `probe`), a computed `needs_upgrade` (running version
differs from `latest`), and the raw payloads for diagnostics.

```json
{
  "device_id": "0f0c…",
  "device_name": "fra-hub-01",
  "reachable": true,
  "product_version": "25.1.2",
  "product_name": "OPNsense",
  "product_series": "25.1",
  "current_version": "25.1.2",
  "latest_release": "25.7",
  "needs_upgrade": true,
  "upgrade_available": true,
  "raw_firmware": { "…": "…" },
  "raw_info": { "latest": "25.7" }
}
```

Failures are explicit: a device without API credentials returns `400`
(`Device '…' has no OPNsense API credentials configured`); a host that exposes
neither endpoint returns `502` from `UpstreamError`. TLS verification follows
`OPNsense_VERIFY_TLS`.

## Upgrade

```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"package": "OPNsense-25.7"}' \
  https://ofme.example.com/api/v1/devices/$DEVICE_ID/firmware/upgrade
```

* `package` is optional. When omitted, OPNsense installs the latest available
  release — but only if OFME knows the current version (`device.firmware_version`).
  A device with no recorded version and no package returns `400`, because the
  upgrade could otherwise reinstall an unknown target.
* The call returns `202` with `status: "initiated"` as soon as OPNsense accepts the
  job. It does **not** wait for the appliance to reboot.
* `device.firmware_version` is cleared so stale data is not displayed; the next
  heartbeat repopulates it.
* The action is written to the audit trail (`firmware.upgrade`) with the package
  name and the device's response.

## Reboot

`POST .../firmware/reboot` calls `POST /api/core/firmware/reboot`, returns `202`
and writes `firmware.reboot` to the audit trail. Use it after a restore or when a
maintenance window requires a clean restart. Traffic through the appliance is
interrupted until it finishes booting.

## Batch operations

The Celery tasks `ofme.firmware.upgrade` and `ofme.firmware.reboot` (queue
`ofme-firmware`) accept `{"device_ids": ["…"], "package": "OPNsense-25.7"}` and are
driven by the `firmware_upgrade`/`firmware_reboot` scheduled-task types. One
failing device is logged and counted; the batch continues and the job result
reports `{"tenants": n, "ok": n, "failed": n}`.

## Console

`Devices → <device> → Firmware` shows the live status, warns when a newer release
exists, and exposes **Upgrade** (optional package) and **Reboot** actions behind
their permissions. The raw device payload is rendered below the summary for
support cases.

## Limits

* **Fire-and-forget.** OFME cannot follow the upgrade progress; it neither polls
  the reboot nor verifies that the new version booted. Confirm with the next
  heartbeat or the firmware tab.
* **No image hosting.** Only packages the appliance can reach through its own
  configured mirrors can be installed; OFME does not upload images.
* **No HA orchestration.** On a CARP pair, upgrade the secondary first and fail
  over manually — OFME does not sequence the pair.
* **No rollback.** OPNsense keeps no automatic snapshot; take a backup
  (`POST /api/v1/backups`) before upgrading.
