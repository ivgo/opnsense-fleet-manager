# Client Inventory Implementation

**Date:** 2026-10-29  
**Status:** ✅ Complete  
**Feature:** Инвентарь клиентов из ARP/DHCP/LLDP с блокировкой/паузой

---

## Overview

The Client Inventory system provides automatic discovery of all endpoint devices on the network via ARP tables, DHCP leases, and LLDP neighbors. It enables one-click blocking or temporary pausing of clients through OPNsense firewall alias integration.

### Key Capabilities

| Feature | Description |
|---------|-------------|
| **Discovery** | Automatic collection via ARP, DHCP, LLDP on every heartbeat |
| **Deduplication** | Unified view by MAC address with source priority |
| **Blocking** | Immediate firewall alias-based blocking |
| **Pausing** | Temporary block with automatic unblock after N minutes |
| **Vendor Lookup** | OUI-based vendor identification |
| **RBAC** | `inventory:read` / `inventory:write` permissions |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         OPNsense Device                                  │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ Telemetry.php                                                     │   │
│  │ - arpTable()      → /usr/sbin/arp -an                            │   │
│  │ - dhcpLeases()    → /var/dhcpd/var/db/dhcpd.leases               │   │
│  │ - lldpNeighbors() → lldpctl -f keyvalue                          │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                              │                                           │
│                              ▼                                           │
│                    POST /agent/heartbeat                                 │
│                    { arp, dhcp_leases, lldp }                            │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         OFME Backend                                     │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ HeartbeatService.ingest()                                         │   │
│  │    └─ InventoryIngestService.ingest()                             │   │
│  │         - Normalize ARP/DHCP/LLDP → ClientDevice                  │   │
│  │         - Deduplicate by MAC (priority: LLDP > DHCP > ARP)        │   │
│  │         - Upsert to client_devices table                          │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                              │                                           │
│                              ▼                                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ InventoryService                                                  │   │
│  │ - block_client()  → OpnsenseClient.add_to_alias()                │   │
│  │ - pause_client()  → OpnsenseClient.add_to_alias() + TTL          │   │
│  │ - unblock_client() → OpnsenseClient.remove_from_alias()          │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                              │                                           │
│                              ▼                                           │
│                    OPNsense Firewall API                                 │
│                    POST /api/firewall/alias/set                          │
│                    Alias: BLOCKED_CLIENTS (type: mac)                    │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         OFME Frontend                                    │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ /inventory                                                        │   │
│  │ - DataTable with MAC/IP/Hostname/Vendor/Source/Status             │   │
│  │ - Filters: Status (Active/Blocked/Paused), Source, Search         │   │
│  │ - Actions: Block | Pause (5min) | Unblock                         │   │
│  │ - Polling: 30s refetch interval                                   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### `client_devices` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `tenant_id` | UUID | Foreign key to tenants |
| `device_id` | UUID | Foreign key to devices (OPNsense that reported it) |
| `mac_address` | VARCHAR(17) | Normalized MAC (AA:BB:CC:DD:EE:FF), unique index |
| `ip_address` | VARCHAR | Current IP from ARP/DHCP |
| `hostname` | VARCHAR | From DHCP lease or reverse DNS |
| `vendor` | VARCHAR | OUI lookup result |
| `source` | ENUM | 'arp' \| 'dhcp' \| 'lldp' |
| `status` | ENUM | 'active' \| 'blocked' \| 'paused' |
| `paused_until` | TIMESTAMP | When pause expires (NULL if not paused) |
| `first_seen` | TIMESTAMP | When first discovered |
| `last_seen` | TIMESTAMP | Last heartbeat update |

**Indexes:**
- `ix_client_devices_mac` (unique)
- `ix_client_devices_tenant_source`

---

## Files Modified/Created

### Backend

| File | Type | Changes |
|------|------|---------|
| `backend/app/models/inventory.py` | NEW | `ClientDevice` model, `ClientSource`, `ClientStatus` enums |
| `backend/app/services/inventory.py` | NEW | `InventoryIngestService`, `InventoryService` |
| `backend/app/api/v1/endpoints/inventory.py` | NEW | 6 REST endpoints |
| `backend/app/api/v1/router.py` | MOD | Registered `inventory.router` |
| `backend/app/schemas/operations.py` | MOD | `ClientDeviceOut`, `ClientDeviceBlock`, `ClientDevicePause`, `VendorInfo` |
| `backend/app/schemas/topology.py` | MOD | `HeartbeatPayload.arp`, `dhcp_leases`, `lldp` |
| `backend/app/integrations/opnsense/client.py` | MOD | `add_to_alias()`, `remove_from_alias()`, `apply_firewall_rules()` |
| `backend/app/services/devices.py` | MOD | Call `InventoryIngestService` in `ingest()` |
| `backend/app/rbac/permissions.py` | MOD | `INVENTORY_READ`, `INVENTORY_WRITE` permissions |

### Frontend

| File | Type | Changes |
|------|------|---------|
| `frontend/src/pages/InventoryPage.tsx` | NEW | Full page component with DataTable, filters, actions |
| `frontend/src/api/types.ts` | MOD | `ClientDevice`, `VendorInfo` interfaces |
| `frontend/src/api/endpoints.ts` | MOD | `inventoryApi` client |
| `frontend/src/api/queryKeys.ts` | MOD | `qk.inventory` keys |
| `frontend/src/router.tsx` | MOD | `/inventory` route |

### Agent (OPNsense Plugin)

| File | Type | Changes |
|------|------|---------|
| `plugin/os-fleet-agent/Telemetry.php` | MOD | `arpTable()`, `dhcpLeases()`, `lldpNeighbors()` methods |

---

## API Reference

### List Clients

```http
GET /api/v1/inventory/clients?status=active&source=arp&search=aa:bb:cc
Authorization: Bearer {token}
```

**Query Parameters:**
- `status` (optional): `active` | `blocked` | `paused`
- `source` (optional): `arp` | `dhcp` | `lldp`
- `search` (optional): MAC, IP, or hostname substring
- `limit` (optional): Max results (default 200, max 1000)

**Response:**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "ip_address": "192.168.1.105",
    "hostname": "iphone-john",
    "vendor": "Apple",
    "first_seen": "2026-10-29T10:15:00Z",
    "last_seen": "2026-10-29T14:30:00Z",
    "source": "dhcp",
    "status": "active",
    "paused_until": null
  }
]
```

### Block Client

```http
POST /api/v1/inventory/clients/AA:BB:CC:DD:EE:FF/block
Authorization: Bearer {token}
Content-Type: application/json

{
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "reason": "Unauthorized device"
}
```

**Response:**
```json
{
  "message": "Client AA:BB:CC:DD:EE:FF blocked successfully"
}
```

### Pause Client

```http
POST /api/v1/inventory/clients/AA:BB:CC:DD:EE:FF/pause
Authorization: Bearer {token}
Content-Type: application/json

{
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "minutes": 5,
  "reason": "Temporary isolation for troubleshooting"
}
```

### Unblock Client

```http
POST /api/v1/inventory/clients/AA:BB:CC:DD:EE:FF/unblock
Authorization: Bearer {token}
```

### Vendor Lookup

```http
POST /api/v1/inventory/vendors
Authorization: Bearer {token}
Content-Type: application/json

{
  "macs": ["AA:BB:CC", "00:0C:29", "52:54:00"]
}
```

**Response:**
```json
[
  {
    "mac_prefix": "AA:BB:CC",
    "vendor_name": "Apple",
    "vendor_address": "1 Infinite Loop, Cupertino CA"
  },
  {
    "mac_prefix": "00:0C:29",
    "vendor_name": "VMware"
  }
]
```

---

## OPNsense Agent Integration

### Data Collection Methods

#### ARP Table (`arpTable()`)

```php
private function arpTable(): ?array
{
    $result = Configd::capture('/usr/sbin/arp', ['-an'], 10);
    // Parse: ? (192.168.1.5) at aa:bb:cc:dd:ee:ff on em0 expires ...
    // Returns: [{ip, mac, interface}, ...]
}
```

**Source:** `/usr/sbin/arp -an`  
**Frequency:** Every heartbeat (default 30s)  
**Coverage:** All IP-to-MAC bindings in ARP cache

#### DHCP Leases (`dhcpLeases()`)

```php
private function dhcpLeases(): ?array
{
    $content = @file_get_contents('/var/dhcpd/var/db/dhcpd.leases');
    // Parse: lease 192.168.1.5 { starts ...; hardware ethernet ...; }
    // Returns: [{ip, mac, hostname, starts, expires}, ...]
}
```

**Source:** `/var/dhcpd/var/db/dhcpd.leases`  
**Frequency:** Every heartbeat  
**Coverage:** Active DHCP leases only

#### LLDP Neighbors (`lldpNeighbors()`)

```php
private function lldpNeighbors(): ?array
{
    $result = Configd::shell('/usr/local/sbin/lldpctl -f keyvalue', 10);
    // Parse: lldp.chassis.mac=..., lldp.chassis.name=...
    // Returns: [{mac, chassis_name, port_description, management_ip, vendor}, ...]
}
```

**Source:** `lldpctl -f keyvalue`  
**Frequency:** Every heartbeat  
**Coverage:** LLDP-advertised network devices (switches, APs, phones)

### Heartbeat Payload

```json
{
  "serial_number": "OFME-001",
  "hostname": "fw-hq-01",
  "firmware_version": "23.7.2",
  "agent_version": "1.0.0",
  "uptime_seconds": 86400,
  "cpu_pct": 12.5,
  "memory_pct": 45.2,
  "arp": [
    {"ip": "192.168.1.105", "mac": "AA:BB:CC:DD:EE:FF", "interface": "em0"}
  ],
  "dhcp_leases": [
    {"ip": "192.168.1.105", "mac": "AA:BB:CC:DD:EE:FF", "hostname": "iphone-john"}
  ],
  "lldp": [
    {"mac": "00:1A:2B:3C:4D:5E", "chassis_name": "switch-core-01", "management_ip": "192.168.1.2"}
  ]
}
```

---

## Firewall Integration

### BLOCKED_CLIENTS Alias

**Type:** MAC addresses  
**Auto-created:** Yes (on first block)  
**Managed by:** OFME InventoryService  

**OPNsense API Flow:**

1. **Add to alias:**
   ```http
   POST /api/firewall/alias/set
   {
     "alias": {
       "BLOCKED_CLIENTS": {
         "name": "BLOCKED_CLIENTS",
         "type": "mac",
         "content": "AA:BB:CC:DD:EE:FF\n00:11:22:33:44:55",
         "description": "Client blocked by OFME inventory"
       }
     }
   }
   ```

2. **Apply changes:**
   ```http
   POST /api/firewall/alias/reconfigure
   POST /api/firewall/filter/apply
   ```

3. **Firewall rule (manual setup required):**
   - Create rule: `block src MAC in BLOCKED_CLIENTS`
   - Position: Top of ruleset (before allow rules)

---

## RBAC Permissions

### Permission Strings

| Permission | Description | Roles |
|------------|-------------|-------|
| `inventory:read` | View client inventory | All roles |
| `inventory:write` | Block/pause/unblock clients | TenantAdmin, Admin, Operator |

### Role Matrix Integration

```python
READ_ONLY: frozenset[P] = frozenset({
    # ... existing permissions ...
    P.INVENTORY_READ,
})

OPERATOR: frozenset[P] = READ_ONLY | {
    # ... existing permissions ...
    P.INVENTORY_WRITE,
}
```

---

## Frontend Implementation

### Page Structure (`/inventory`)

```tsx
InventoryPage
├── PageHeader
│   ├── Title: "Client Inventory"
│   └── Action: "Block Selected" (bulk)
├── Filters Bar
│   ├── Search (MAC/IP/hostname)
│   ├── Status Select (All/Active/Blocked/Paused)
│   └── Source Select (All/ARP/DHCP/LLDP)
└── DataTable
    ├── MAC Address (monospace)
    ├── IP Address
    ├── Hostname
    ├── Source (chip)
    ├── Status (chip)
    ├── Vendor (hide < md)
    ├── Last Seen (fromNow)
    └── Actions (Block/Pause/Unblock)
```

### Query Configuration

```typescript
const { data: clients = [], isLoading } = useQuery({
  queryKey: qk.inventory.list({ status, source, search }),
  queryFn: () => inventoryApi.list({ status, source, search }),
  refetchInterval: 30_000, // 30s polling
});
```

### Mutations

```typescript
const blockMutation = useMutation({
  mutationFn: (mac: string) => inventoryApi.block(mac),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: qk.inventory.list() });
    showToast({ message: `Client ${mac} blocked`, severity: "success" });
  },
});
```

---

## Testing

### Backend Tests (Pending)

```bash
cd backend
pytest tests/test_inventory.py -v
```

**Test Coverage:**
- [ ] `InventoryIngestService.ingest()` - deduplication logic
- [ ] `InventoryService.block_client()` - firewall integration
- [ ] `InventoryService.pause_client()` - TTL handling
- [ ] `InventoryService.unblock_client()` - alias removal
- [ ] API endpoint permission checks
- [ ] RBAC role matrix inclusion

### Frontend Tests (Pending)

```bash
cd frontend
npm test -- InventoryPage.test.tsx
```

**Test Coverage:**
- [ ] Component renders with empty state
- [ ] Filter changes update query params
- [ ] Block action calls API and invalidates cache
- [ ] Pause action shows dialog
- [ ] Unblock action succeeds

### E2E Validation

1. **Start stack:**
   ```bash
   docker compose up -d
   ```

2. **Enroll test device with clients:**
   - Ensure OPNsense agent has ARP/DHCP/LLDP data
   - Wait for heartbeat (30s interval)

3. **Verify inventory page:**
   - Open http://localhost:8080/inventory
   - Confirm clients appear in table

4. **Test blocking:**
   - Click Block on a client
   - Verify OPNsense alias updated
   - Verify toast notification

5. **Test pausing:**
   - Click Pause (5 min) on a client
   - Verify status changes to "Paused"
   - Wait 5 min, verify auto-unblock (requires Celery task)

---

## Known Limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| No Celery task for auto-unblock after pause | Paused clients stay blocked until manual unblock | Add `ofme.inventory.unblock_expired` task |
| OUI lookup uses static map | Limited vendor coverage | Integrate `mac-vendor-lookup` API |
| No bulk operations UI | Must block clients one-by-one | Implement checkbox select + bulk action |
| Firewall rule not auto-created | Requires manual OPNsense setup | Document rule creation in setup guide |
| No client history/timeline | Can't see when client appeared/disappeared | Add `first_seen`/`last_seen` visualization |

---

## Future Enhancements

### Phase 2 (High Priority)

1. **Auto-unblock Celery task**
   - `backend/app/workers/inventory.py`
   - Runs every minute, checks `paused_until < NOW`
   - Calls `unblock_client()` for expired pauses

2. **Enhanced OUI lookup**
   - Full vendor database (IEEE OUI dump)
   - Fallback to online API if local miss

3. **Bulk operations**
   - Checkbox selection in DataTable
   - "Block Selected" / "Pause Selected" actions

4. **Client history timeline**
   - Graph of client count over time
   - First-seen/last-seen analytics

### Phase 3 (Medium Priority)

5. **Client classification**
   - Known devices (manual whitelist)
   - Device type inference (IoT, phone, laptop)
   - Risk scoring

6. **Alerting integration**
   - Alert on new unknown device
   - Alert on blocked device reconnection
   - Alert on high-risk vendor (e.g., unknown manufacturer)

7. **Network segmentation**
   - VLAN assignment by client type
   - Quarantine VLAN for blocked clients

---

## Operational Runbooks

### Setup: Create Firewall Rule

1. Log into OPNsense web UI
2. Navigate to **Firewall > Rules > LAN**
3. Click **Add** (top of ruleset)
4. Configure:
   - **Action:** Block
   - **Source:** `BLOCKED_CLIENTS` alias
   - **Destination:** Any
   - **Description:** "Block OFME-managed clients"
5. Click **Save**, then **Apply Changes**

### Troubleshooting: Client Not Appearing

1. **Check agent telemetry:**
   ```bash
   # On OPNsense
   /usr/local/etc/rc.d/os-fleet-agent.sh status
   tail -f /var/log/os-fleet-agent.log
   ```

2. **Verify ARP data:**
   ```bash
   /usr/sbin/arp -an
   ```

3. **Check backend logs:**
   ```bash
   docker compose logs ofme-api | grep inventory
   ```

4. **Query database directly:**
   ```sql
   SELECT mac_address, ip_address, source, status, last_seen
   FROM client_devices
   WHERE tenant_id = '<tenant-uuid>'
   ORDER BY last_seen DESC;
   ```

### Emergency: Unblock All Clients

```bash
# Database reset (use with caution)
docker compose exec postgres psql -U ofme -d ofme -c \
  "UPDATE client_devices SET status = 'active', paused_until = NULL WHERE tenant_id = '<uuid>';"
```

---

## Changelog

### 2026-10-29 — Initial Implementation

- ✅ Backend models, services, API endpoints
- ✅ OPNsense agent ARP/DHCP/LLDP collection
- ✅ Frontend inventory page with filters/actions
- ✅ RBAC permissions integration
- ✅ Firewall alias integration
- ⏳ Auto-unblock Celery task (Phase 2)
- ⏳ Full test coverage (Phase 2)

---

## Related Documentation

- [Architecture Overview](ARCHITECTURE.md)
- [OPNsense Agent Guide](AGENT_SETUP.md)
- [RBAC Configuration](RBAC.md)
- [Firewall Rules Guide](FIREWALL_RULES.md)