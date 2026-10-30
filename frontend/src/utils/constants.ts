import type {
  ComplianceFramework,
  Environment,
  PolicyKind,
  ReportKind,
  TaskKind,
  TopologyType,
} from "@/api/types";

export const NAV_WIDTH = 272;
export const NAV_WIDTH_COLLAPSED = 76;
export const TOPBAR_HEIGHT = 64;

export const ROLE_OPTIONS = [
  "SuperAdmin",
  "TenantAdmin",
  "Admin",
  "Operator",
  "Auditor",
  "ReadOnly",
] as const;

export const ENVIRONMENTS: Array<{ value: Environment; label: string }> = [
  { value: "development", label: "Development" },
  { value: "testing", label: "Testing" },
  { value: "staging", label: "Staging" },
  { value: "production", label: "Production" },
];

export const POLICY_KINDS: Array<{ value: PolicyKind; label: string }> = [
  { value: "firewall", label: "Firewall" },
  { value: "nat", label: "NAT" },
  { value: "vpn", label: "VPN" },
  { value: "vlan", label: "VLAN" },
  { value: "interface", label: "Interface" },
  { value: "routing", label: "Routing" },
  { value: "compliance", label: "Compliance" },
];

export const FRAMEWORKS: Array<{ value: ComplianceFramework; label: string; description: string }> = [
  { value: "cis", label: "CIS Benchmark", description: "Center for Internet Security OPNsense benchmark" },
  { value: "iso27001", label: "ISO/IEC 27001", description: "Information security management controls" },
  { value: "nis2", label: "NIS2", description: "EU network and information security directive" },
  { value: "pci_dss", label: "PCI DSS", description: "Payment card industry data security standard" },
  { value: "soc2", label: "SOC 2", description: "Service organisation controls" },
];

export const FRAMEWORK_LABELS: Record<string, string> = Object.fromEntries(
  FRAMEWORKS.map((item) => [item.value, item.label]),
);

export const DEVICE_STATUS_LABELS: Record<string, string> = {
  unregistered: "Unregistered",
  registered: "Registered",
  online: "Online",
  offline: "Offline",
  error: "Error",
  maintenance: "Maintenance",
};

export const CONNECTION_STATUS_LABELS: Record<string, string> = {
  unknown: "Unknown",
  connected: "Connected",
  disconnected: "Disconnected",
  error: "Error",
};

export const ALERT_SEVERITY_LABELS: Record<string, string> = {
  info: "Info",
  warning: "Warning",
  critical: "Critical",
};

export const ALERT_STATUS_LABELS: Record<string, string> = {
  firing: "Firing",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
};

export const POLICY_STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  validated: "Validated",
  review: "In review",
  approved: "Approved",
  deployed: "Deployed",
  archived: "Archived",
};

export const JOB_STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const BACKUP_TYPE_LABELS: Record<string, string> = {
  manual: "Manual",
  scheduled: "Scheduled",
  pre_upgrade: "Pre-upgrade",
  pre_change: "Pre-change",
  auto: "Automatic",
};

export const TUNNEL_STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  provisioning: "Provisioning",
  active: "Active",
  down: "Down",
  error: "Error",
};

export const TASK_KINDS: Array<{ value: TaskKind; label: string }> = [
  { value: "backup", label: "Configuration backup" },
  { value: "compliance_scan", label: "Compliance scan" },
  { value: "firmware_upgrade", label: "Firmware upgrade" },
  { value: "policy_deploy", label: "Policy deployment" },
  { value: "drift_scan", label: "Drift scan" },
  { value: "metric_collect", label: "Metric collection" },
  { value: "report", label: "PDF report" },
  { value: "custom", label: "Custom (safe actions)" },
];

export const MAINTENANCE_TARGET_LABELS: Record<string, string> = {
  fleet: "Whole fleet",
  device: "Devices",
  site: "Sites",
  group: "Groups",
};

export const REPORT_KINDS: Array<{ value: ReportKind; label: string; description: string }> = [
  { value: "fleet", label: "Fleet summary", description: "Inventory, health, open alerts and compliance" },
  { value: "compliance", label: "Compliance", description: "Framework scores and failing controls" },
  { value: "traffic", label: "Traffic", description: "Interface throughput for the selected period" },
  { value: "alerts", label: "Alerts", description: "Alert history and acknowledgement state" },
];

export const REPORT_KIND_LABELS: Record<string, string> = Object.fromEntries(
  REPORT_KINDS.map((item) => [item.value, item.label]),
);

export const REPORT_STATUS_LABELS: Record<string, string> = {
  pending: "Queued",
  generating: "Generating",
  ready: "Ready",
  failed: "Failed",
};

export const BULK_ACTION_LABELS: Record<string, string> = {
  maintenance_on: "Enter maintenance",
  maintenance_off: "Leave maintenance",
  command: "Run command",
  backup: "Create backups",
  firmware_upgrade: "Upgrade firmware",
  reboot: "Reboot devices",
};

export const BULK_COMMAND_ACTIONS = [
  { value: "collect_diagnostics", label: "Collect diagnostics" },
  { value: "sync_config", label: "Synchronise configuration" },
  { value: "reload_firewall", label: "Reload firewall rules" },
  { value: "update_telemetry", label: "Refresh telemetry" },
  { value: "ping", label: "Ping the agent" },
] as const;

export const TOPOLOGY_TYPES: Array<{ value: TopologyType; label: string }> = [
  { value: "hub_spoke", label: "Hub & spoke" },
  { value: "full_mesh", label: "Full mesh" },
  { value: "regional_hub", label: "Regional hub" },
];

export const STEERING_STRATEGIES = [
  { value: "lowest_latency", label: "Lowest latency" },
  { value: "lowest_loss", label: "Lowest packet loss" },
  { value: "lowest_cost", label: "Lowest cost" },
  { value: "application", label: "Application-aware" },
  { value: "weighted", label: "Weighted bandwidth" },
  { value: "failover", label: "Failover" },
] as const;

export const TUNNEL_PROTOCOLS = [
  { value: "wireguard", label: "WireGuard" },
  { value: "ipsec", label: "IPsec" },
  { value: "openvpn", label: "OpenVPN" },
] as const;

export const ALERT_CHANNELS = ["email", "slack", "webhook", "teams", "pagerduty"] as const;

export const ALERT_OPERATORS = [">", ">=", "<", "<=", "==", "!="] as const;

export const ALERT_METRICS = [
  "cpu",
  "memory",
  "disk",
  "load",
  "gateway_down",
  "vpn_down",
  "carp",
  "offline_seconds",
  "sessions",
] as const;

export const CRON_PRESETS = [
  { label: "Every 5 minutes", value: "*/5 * * * *" },
  { label: "Hourly", value: "0 * * * *" },
  { label: "Daily at 02:00", value: "0 2 * * *" },
  { label: "Weekly (Monday 03:00)", value: "0 3 * * 1" },
  { label: "Monthly (1st, 04:00)", value: "0 4 1 * *" },
] as const;

export const DEFAULT_PAGE_SIZE = 25;

export const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];
