export type ISODate = string;

export interface PageMeta {
  page: number;
  size: number;
  total: number;
  pages: number;
}

export interface Page<T> {
  items: T[];
  meta: PageMeta;
}

export interface Message {
  message: string;
  code?: string | null;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: unknown;
    request_id?: string | null;
  };
}

export type DeviceStatus =
  | "unregistered"
  | "registered"
  | "online"
  | "offline"
  | "error"
  | "maintenance";

export type ConnectionStatus = "unknown" | "connected" | "disconnected" | "error";
export type AlertSeverity = "info" | "warning" | "critical";
export type AlertStatus = "firing" | "acknowledged" | "resolved";
export type JobStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type PolicyStatus =
  | "draft"
  | "validated"
  | "review"
  | "approved"
  | "deployed"
  | "archived";
export type PolicyKind =
  | "firewall"
  | "nat"
  | "vpn"
  | "vlan"
  | "interface"
  | "routing"
  | "compliance";
export type Environment = "development" | "testing" | "staging" | "production";
export type BackupType = "manual" | "scheduled" | "pre_upgrade" | "pre_change" | "auto";
export type ComplianceFramework = "cis" | "iso27001" | "nis2" | "pci_dss" | "soc2";
export type VpnProtocol = "wireguard" | "ipsec" | "openvpn";
export type TunnelStatus = "pending" | "provisioning" | "active" | "down" | "error";
export type TopologyType = "hub_spoke" | "full_mesh" | "regional_hub";
export type SteeringStrategy =
  | "lowest_latency"
  | "lowest_loss"
  | "lowest_cost"
  | "application"
  | "weighted"
  | "failover";
export type DriftStatus = "open" | "acknowledged" | "remediated" | "ignored";
export type DeploymentStatus =
  | "pending"
  | "validating"
  | "deploying"
  | "completed"
  | "failed"
  | "rolled_back";
export type ZtpStatus =
  | "pending"
  | "token_issued"
  | "discovered"
  | "enrolled"
  | "provisioned"
  | "failed"
  | "revoked"
  | "completed";
export type TaskKind =
  | "backup"
  | "compliance_scan"
  | "firmware_upgrade"
  | "policy_deploy"
  | "drift_scan"
  | "metric_collect"
  | "report"
  | "custom";

export type TemplateKind = "config" | "policy" | "ztp";

export interface AuthUser {
  id: string;
  tenant_id: string | null;
  username: string;
  email: string;
  full_name: string | null;
  roles: string[];
  permissions: string[];
  is_superadmin: boolean;
  mfa_enabled: boolean;
  auth_provider: string;
  last_login_at: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  mfa_required: boolean;
}

export interface LoginResponse extends TokenPair {
  challenge_token: string | null;
  methods: string[];
  user: AuthUser | null;
}

export interface LoginPayload {
  username: string;
  password: string;
  tenant?: string | null;
  mfa_code?: string | null;
}

export interface MfaVerifyPayload {
  code: string;
  challenge_token?: string | null;
}

export interface SessionInfo {
  id: string;
  user_id: string;
  jti: string;
  ip_address: string | null;
  user_agent: string | null;
  created_at: ISODate;
  expires_at: ISODate;
}

export interface MfaSetup {
  secret: string;
  provisioning_uri: string;
  backup_codes: string[];
}

export interface AuthProviders {
  ldap: boolean;
  oidc: boolean;
  entra_id: boolean;
  saml: boolean;
  mfa_enabled: boolean;
}

export interface OidcAuthorizeResponse {
  authorization_url: string;
  state: string;
}

export interface Device {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  tenant_id: string;
  site_id: string | null;
  group_id: string | null;
  name: string;
  hostname: string | null;
  description: string | null;
  serial_number: string | null;
  model: string | null;
  firmware_version: string | null;
  agent_version: string | null;
  ip_address: string | null;
  api_port: number;
  status: DeviceStatus;
  connection_status: ConnectionStatus;
  is_ha: boolean;
  ha_role: string | null;
  tags: string[];
  certificate_serial: string | null;
  last_seen_at: string | null;
  last_heartbeat_at: string | null;
  uptime_seconds: number | null;
  enrolled_at: string | null;
  provisioned_at: string | null;
}

export interface DeviceCreate {
  name: string;
  site_id?: string | null;
  group_id?: string | null;
  hostname?: string | null;
  description?: string | null;
  ip_address?: string | null;
  api_port?: number;
  serial_number?: string | null;
  model?: string | null;
  is_ha?: boolean;
  ha_role?: string | null;
  tags?: string[];
  api_key?: string | null;
  api_secret?: string | null;
}

export type DeviceUpdate = Partial<
  Pick<
    DeviceCreate,
    | "name"
    | "site_id"
    | "group_id"
    | "hostname"
    | "description"
    | "ip_address"
    | "api_port"
    | "is_ha"
    | "ha_role"
    | "tags"
    | "api_key"
    | "api_secret"
  >
> & { status?: DeviceStatus };

export interface DeviceSummary {
  total: number;
  online: number;
  offline: number;
  error: number;
  maintenance: number;
  unregistered: number;
}

export interface DeviceSearchResult {
  id: string;
  name: string;
  hostname: string | null;
  ip_address: string | null;
  status: DeviceStatus;
}

export type DeviceCommandAction =
  | "noop"
  | "ping"
  | "sync_config"
  | "renew_certificate"
  | "restart_agent"
  | "collect_diagnostics"
  | "reload_firewall"
  | "update_telemetry";

export interface DeviceCommand {
  id: string;
  action: DeviceCommandAction;
  payload: Record<string, unknown>;
  requested_at: ISODate;
  requested_by: string | null;
  pending_count: number;
}

export interface DeviceCommandResult {
  id: string;
  action: string;
  status: string;
  message?: string | null;
  output?: Record<string, unknown> | null;
  started_at?: ISODate | null;
  finished_at?: ISODate | null;
  duration_ms?: number | null;
  received_at?: ISODate | null;
}

export interface DeviceCommandStatus {
  device_id: string;
  pending: Array<{
    id: string;
    action: string;
    payload: Record<string, unknown>;
    requested_at: ISODate;
    requested_by: string | null;
  }>;
  history: DeviceCommandResult[];
  pending_count: number;
  last_result_at: ISODate | null;
}

export interface FirmwareStatus {
  device_id: string;
  device_name: string;
  reachable: boolean;
  product_version: string | null;
  product_name: string | null;
  product_series: string | null;
  current_version: string | null;
  latest_release: string | null;
  needs_upgrade: boolean;
  upgrade_available: boolean;
  raw_firmware: Record<string, unknown>;
  raw_info: Record<string, unknown>;
}

export interface FirmwareAction {
  device_id: string;
  device_name: string;
  package: string | null;
  status: string;
  response: Record<string, unknown> | null;
  initiated_at: ISODate;
}

export interface Site {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  code: string;
  description: string | null;
  city: string | null;
  country: string | null;
  latitude: number | null;
  longitude: number | null;
  timezone: string | null;
  device_count: number;
}

export interface SitePayload {
  name: string;
  code: string;
  description?: string | null;
  address?: string | null;
  city?: string | null;
  country?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  timezone?: string | null;
  contact_info?: Record<string, unknown> | null;
}

export interface SiteMapPoint {
  id: string;
  name: string;
  city: string | null;
  country: string | null;
  latitude: number | null;
  longitude: number | null;
  devices_total: number;
  devices_online: number;
  worst_severity: string | null;
}

export interface DeviceGroup {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  description: string | null;
  parent_id: string | null;
  template_id: string | null;
  labels: string[];
  device_count: number;
}

export interface DeviceGroupPayload {
  name: string;
  description?: string | null;
  parent_id?: string | null;
  template_id?: string | null;
  labels?: string[];
}

export interface GroupTreeNode {
  id: string;
  name: string;
  description: string | null;
  labels: string[];
  device_count: number;
  children: GroupTreeNode[];
}

export interface Template {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  description: string | null;
  kind: TemplateKind;
  parent_id: string | null;
  body: Record<string, unknown>;
  version: number;
  is_active: boolean;
  variables: Record<string, unknown>;
}

export interface TemplatePayload {
  name: string;
  description?: string | null;
  kind?: TemplateKind;
  parent_id?: string | null;
  body: Record<string, unknown>;
  variables?: Record<string, unknown>;
  is_active?: boolean;
}

export interface TemplateRenderResponse {
  rendered: Record<string, unknown>;
  variables_used: string[];
  warnings: string[];
}

export interface Policy {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  kind: PolicyKind;
  environment: Environment;
  repo_id: string | null;
  path: string | null;
  content: string;
  content_hash: string;
  version: number;
  status: PolicyStatus;
  description: string | null;
  validated_at: string | null;
  validation_errors: Array<Record<string, unknown>>;
  target_selector: Record<string, unknown>;
}

export interface PolicyPayload {
  name: string;
  kind: PolicyKind;
  environment: Environment;
  repo_id?: string | null;
  path?: string | null;
  content: string;
  description?: string | null;
  target_selector?: Record<string, unknown>;
}

export interface PolicyValidationIssue {
  severity: string;
  code: string;
  message: string;
  path?: string | null;
  line?: number | null;
  remediation?: string | null;
}

export interface PolicyValidation {
  valid: boolean;
  errors: PolicyValidationIssue[];
  warnings: PolicyValidationIssue[];
  rule_count: number;
  conflict_count: number;
  compiled: Record<string, unknown> | null;
}

export interface PolicyDiffEntry {
  path: string;
  change: string;
  before: unknown;
  after: unknown;
}

export interface PolicyDiff {
  policy_id: string;
  base_version: number;
  target_version: number;
  entries: PolicyDiffEntry[];
  summary: string;
}

export interface Deployment {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  policy_id: string;
  environment: Environment;
  commit_sha: string | null;
  status: DeploymentStatus;
  plan: Record<string, unknown>;
  target_device_ids: string[];
  results: Array<Record<string, unknown>>;
  logs: string[];
  started_at: string | null;
  completed_at: string | null;
}

export interface DriftReport {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string;
  policy_id: string | null;
  status: DriftStatus;
  differences: Array<Record<string, unknown>>;
  desired_hash: string | null;
  actual_hash: string | null;
  detected_at: string;
  resolved_at: string | null;
}

export interface GitRepository {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  provider: "github" | "gitlab" | "azure_devops" | "generic";
  url: string;
  default_branch: string;
  auth_type: "token" | "ssh" | "oauth";
  auto_sync: boolean;
  sync_interval_minutes: number;
  last_sync_at: string | null;
  last_commit_sha: string | null;
  status: string;
}

export interface GitRepositoryPayload {
  name: string;
  provider: GitRepository["provider"];
  url: string;
  default_branch?: string;
  auth_type?: GitRepository["auth_type"];
  auto_sync?: boolean;
  sync_interval_minutes?: number;
  token?: string | null;
}

export interface Topology {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  description: string | null;
  topology_type: TopologyType;
  status: string;
  hub_device_ids: string[];
  spoke_device_ids: string[];
  configuration: Record<string, unknown>;
  routing_config: Record<string, unknown>;
}

export interface TopologyPayload {
  name: string;
  description?: string | null;
  topology_type: TopologyType;
  hub_device_ids?: string[];
  spoke_device_ids?: string[];
  configuration?: Record<string, unknown>;
  routing_config?: Record<string, unknown>;
}

export interface TopologyNode {
  id: string;
  name: string;
  role: string;
  status: string;
  site: string | null;
  latitude: number | null;
  longitude: number | null;
}

export interface TopologyEdge {
  id: string;
  source: string;
  target: string;
  status: string;
  health: string;
  latency_ms: number | null;
  loss_pct: number | null;
  label: string | null;
}

export interface TopologyGraph {
  topology_id: string;
  name: string;
  type: string;
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  generated_at: string;
}

export interface TopologyDeployResult {
  topology_id: string;
  tunnels_created: number;
  tunnels_updated: number;
  routes_installed: number;
  devices_configured: number;
  errors: string[];
}

export interface Tunnel {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  topology_id: string;
  name: string;
  protocol: VpnProtocol;
  local_device_id: string;
  remote_device_id: string | null;
  interface_name: string | null;
  public_key: string | null;
  endpoint_local: string | null;
  endpoint_remote: string | null;
  allowed_ips: string[];
  keepalive: number;
  mtu: number | null;
  status: TunnelStatus;
  health_status: string;
  last_handshake_at: string | null;
  metrics: Record<string, unknown>;
}

export interface TunnelPayload {
  topology_id: string;
  name: string;
  protocol: VpnProtocol;
  local_device_id: string;
  remote_device_id?: string | null;
  interface_name?: string | null;
  endpoint_local?: string | null;
  endpoint_remote?: string | null;
  allowed_ips?: string[];
  keepalive?: number;
  mtu?: number | null;
  wan_interface?: string | null;
  priority?: number;
  cost?: number;
}

export interface SdwanLink {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  topology_id: string;
  tunnel_id: string | null;
  local_device_id: string;
  remote_device_id: string | null;
  wan_interface: string;
  status: TunnelStatus;
  latency_ms: number | null;
  jitter_ms: number | null;
  loss_pct: number | null;
  bandwidth_mbps: number | null;
  cost: number;
  priority: number;
  sla_latency_ms: number;
  sla_loss_pct: number;
  measured_at: string | null;
}

export interface TrafficPolicy {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  topology_id: string;
  name: string;
  description: string | null;
  strategy: SteeringStrategy;
  match: Record<string, unknown>;
  preferred_link_ids: string[];
  priority: number;
  enabled: boolean;
}

export interface TrafficPolicyPayload {
  topology_id: string;
  name: string;
  description?: string | null;
  strategy: SteeringStrategy;
  match?: Record<string, unknown>;
  preferred_link_ids?: string[];
  priority?: number;
  enabled?: boolean;
}

export interface ComplianceReport {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  framework: ComplianceFramework;
  scope: Record<string, unknown>;
  status: string;
  score: number;
  controls_total: number;
  controls_passed: number;
  controls_failed: number;
  findings: Array<Record<string, unknown>>;
  controls: Array<Record<string, unknown>>;
  summary: string | null;
  artifact_key: string | null;
  generated_at: string;
}

export interface ComplianceSummary {
  framework: ComplianceFramework;
  latest_score: number | null;
  controls_total: number;
  controls_failed: number;
  last_run: string | null;
  trend: Array<Record<string, unknown>>;
}

export interface ComplianceRunPayload {
  framework: ComplianceFramework;
  device_ids?: string[];
}

export interface AuditEntry {
  id: number;
  tenant_id: string | null;
  user_id: string | null;
  actor: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  result: string;
  ip_address: string | null;
  request_id: string | null;
  method: string | null;
  path: string | null;
  status_code: number | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
}

export interface AuditIntegrity {
  checked: number;
  valid: boolean;
  first_broken_id: number | null;
  last_hash: string | null;
}

export interface Backup {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string;
  type: BackupType;
  storage_key: string;
  checksum_sha256: string;
  signature: string | null;
  size_bytes: number | null;
  firmware_version: string | null;
  notes: string | null;
  is_encrypted: boolean;
}

export interface BackupPayload {
  device_id: string;
  type: BackupType;
  notes?: string | null;
}

export interface BackupVerification {
  backup_id: string;
  checksum_ok: boolean;
  signature_ok: boolean;
  valid: boolean;
  stored_checksum: string;
  computed_checksum: string;
  size_bytes: number;
}

export interface BackupRestorePayload {
  backup_id: string;
  dry_run?: boolean;
  reboot?: boolean;
}

/* ------------------------------------------------------- maintenance windows */

export type MaintenanceTarget = "fleet" | "device" | "site" | "group";

export interface MaintenanceWindow {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  description: string | null;
  starts_at: ISODate;
  ends_at: ISODate;
  enabled: boolean;
  target_type: MaintenanceTarget;
  target_ids: string[];
  silence_alerts: boolean;
  silence_notifications: boolean;
  created_by: string | null;
  active: boolean;
}

export interface MaintenanceWindowPayload {
  name: string;
  description?: string | null;
  starts_at: ISODate;
  ends_at: ISODate;
  enabled?: boolean;
  target_type?: MaintenanceTarget;
  target_ids?: string[];
  silence_alerts?: boolean;
  silence_notifications?: boolean;
}

export type MaintenanceWindowUpdatePayload = Partial<MaintenanceWindowPayload>;

/* ------------------------------------------------------------------- reports */

export type ReportKind = "fleet" | "compliance" | "traffic" | "alerts";

export type ReportStatus = "pending" | "generating" | "ready" | "failed";

export interface Report {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  kind: ReportKind;
  status: ReportStatus;
  period_start: ISODate;
  period_end: ISODate;
  params: Record<string, unknown>;
  size_bytes: number | null;
  checksum_sha256: string | null;
  error: string | null;
  generated_at: ISODate | null;
  created_by: string | null;
  download_url: string | null;
}

export interface ReportPayload {
  name?: string | null;
  kind: ReportKind;
  period_days: number;
  params?: Record<string, unknown>;
}

/* -------------------------------------------------------------- bulk actions */

export type BulkAction =
  | "maintenance_on"
  | "maintenance_off"
  | "command"
  | "backup"
  | "firmware_upgrade"
  | "reboot";

export interface BulkDeviceAction {
  action: BulkAction;
  device_ids: string[];
  params?: Record<string, unknown>;
}

export interface BulkDeviceResult {
  device_id: string;
  name: string;
  status: "ok" | "failed" | "skipped";
  message: string | null;
}

export interface BulkDeviceResponse {
  action: string;
  total: number;
  succeeded: number;
  failed: number;
  results: BulkDeviceResult[];
}

export interface CsvImportError {
  row: number;
  error: string;
}

export interface CsvImportResult {
  created: number;
  skipped: number;
  errors: CsvImportError[];
  devices: Array<Record<string, unknown>>;
}

export interface User {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  tenant_id: string | null;
  username: string;
  email: string;
  full_name: string | null;
  status: string;
  auth_provider: string;
  is_superadmin: boolean;
  mfa_enabled: boolean;
  roles: string[];
  last_login_at: string | null;
}

export interface UserPayload {
  username: string;
  email: string;
  full_name?: string | null;
  password?: string | null;
  role_ids?: string[];
  role_names?: string[];
  auth_provider?: string;
  external_id?: string | null;
  is_superadmin?: boolean;
}

export type UserUpdatePayload = Partial<
  Pick<UserPayload, "email" | "full_name" | "role_ids">
> & { status?: string; preferences?: Record<string, unknown> | null };

export interface Role {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
  tenant_id: string | null;
}

export interface RoleMatrixEntry {
  role: string;
  description: string;
  permissions: string[];
}

export interface Permission {
  code: string;
  description: string | null;
  category: string | null;
}

export interface Tenant {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  slug: string;
  status: string;
  plan: string;
  device_limit: number;
  contact_email: string | null;
  settings: Record<string, unknown>;
  device_count: number;
}

export interface TenantStats {
  tenant_id: string;
  devices_total: number;
  devices_online: number;
  devices_offline: number;
  active_alerts: number;
  storage_bytes: number;
  users: number;
}

export interface ApiKey {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  key_prefix: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

export type ApiKeyCreated = ApiKey & { key: string };

export interface ApiKeyPayload {
  name: string;
  scopes?: string[];
  expires_in_days?: number | null;
}

export interface FleetSummary {
  devices_total: number;
  devices_online: number;
  devices_offline: number;
  devices_error: number;
  devices_unregistered: number;
  sites_total: number;
  policies_total: number;
  policies_drifted: number;
  tunnels_total: number;
  tunnels_up: number;
  open_alerts: number;
  critical_alerts: number;
  jobs_running: number;
  compliance_score: number;
}

export interface DeviceHealth {
  device_id: string;
  name: string;
  status: DeviceStatus;
  cpu_pct: number | null;
  memory_pct: number | null;
  disk_pct: number | null;
  sessions: number | null;
  uptime_seconds: number | null;
  vpn_up: number;
  vpn_total: number;
  gateways_up: number;
  gateways_total: number;
  carp_status: string | null;
  recorded_at: string | null;
  in_bps: number | null;
  out_bps: number | null;
}

export interface DashboardTrend {
  timestamp: string;
  online: number;
  offline: number;
  alerts: number;
}

export interface Alert {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string | null;
  fingerprint: string;
  title: string;
  message: string | null;
  severity: AlertSeverity;
  status: AlertStatus;
  labels: Record<string, unknown>;
  starts_at: string;
  ends_at: string | null;
  acknowledged_at: string | null;
}

export interface DashboardOverview {
  summary: FleetSummary;
  health: DeviceHealth[];
  alerts: Alert[];
  trends: DashboardTrend[];
  top_alerts_by_severity: Record<string, number>;
  generated_at: string;
}

export interface ClientDevice {
  id: string;
  mac_address: string;
  ip_address: string | null;
  hostname: string | null;
  vendor: string | null;
  first_seen: string;
  last_seen: string;
  source: "arp" | "dhcp" | "lldp";
  status: "active" | "blocked" | "paused";
  paused_until: string | null;
}

export interface VendorInfo {
  mac_prefix: string;
  vendor_name: string;
  vendor_address: string | null;
}

export interface MetricPoint {
  recorded_at: string;
  value: number;
}

export interface MetricSeries {
  device_id: string;
  metric_type: string;
  unit: string | null;
  points: MetricPoint[];
}

export interface TrafficInterface {
  key: string;
  name: string;
}

export interface TrafficPoint {
  recorded_at: string;
  in_bps: number;
  out_bps: number;
}

export interface TrafficSeries {
  device_id: string;
  interface: string;
  unit: string;
  hours: number;
  bucket_seconds: number;
  interfaces: TrafficInterface[];
  points: TrafficPoint[];
  generated_at: string;
}

export interface FleetTrafficDevice {
  device_id: string;
  name: string;
  interface: string;
  interface_name: string;
  in_bps: number;
  out_bps: number;
  recorded_at: string;
}

export interface FleetTraffic {
  interface: string;
  unit: string;
  hours: number;
  bucket_seconds: number;
  points: TrafficPoint[];
  devices: FleetTrafficDevice[];
  generated_at: string;
}

export interface Job {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  task_name: string;
  celery_task_id: string | null;
  status: JobStatus;
  progress: number;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobPayload {
  task_name: string;
  params?: Record<string, unknown>;
}

export interface ScheduledTask {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  kind: TaskKind;
  cron: string;
  payload: Record<string, unknown>;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
}

export interface ScheduledTaskPayload {
  name: string;
  kind: TaskKind;
  cron: string;
  payload?: Record<string, unknown>;
  enabled?: boolean;
}

export interface AlertRule {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  metric: string;
  operator: string;
  threshold: number;
  duration_seconds: number;
  severity: AlertSeverity;
  enabled: boolean;
  device_selector: Record<string, unknown>;
  channels: string[];
}

export interface Notification {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  type: string;
  title: string;
  message: string;
  severity: AlertSeverity;
  read: boolean;
  action_url: string | null;
  delivery: Record<string, NotificationDelivery>;
  delivered_at: string | null;
}

export interface Rule {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string | null;
  name: string;
  description: string | null;
  action: string;
  direction: string;
  interface: string | null;
  protocol: string;
  source: string;
  destination: string;
  destination_port: string | null;
  source_port: string | null;
  gateway: string | null;
  log: boolean;
  enabled: boolean;
  order_index: number;
  tags: string[];
  version: number;
}

export interface Alias {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string | null;
  name: string;
  description: string | null;
  type: string;
  content: string[];
  enabled: boolean;
}

export interface NatRule {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string | null;
  name: string;
  description: string | null;
  type: string;
  interface: string;
  protocol: string;
  source: string;
  destination: string;
  destination_port: string | null;
  target: string | null;
  target_port: string | null;
  enabled: boolean;
  order_index: number;
}

export type RuleAction = "pass" | "block" | "reject";
export type RuleDirection = "in" | "out";

export interface RulePayload {
  device_id?: string | null;
  group_id?: string | null;
  name: string;
  description?: string | null;
  action: RuleAction;
  direction?: RuleDirection;
  interface?: string | null;
  protocol?: string;
  source?: string;
  destination?: string;
  destination_port?: string | null;
  source_port?: string | null;
  gateway?: string | null;
  log?: boolean;
  enabled?: boolean;
  order_index?: number | null;
  tags?: string[];
}

export type RuleUpdatePayload = Partial<Omit<RulePayload, "device_id" | "group_id" | "name">>;

export interface RuleDeployResult {
  device_id: string;
  dry_run: boolean;
  created: number;
  updated: number;
  applied: boolean;
  result: Record<string, unknown>;
}

export type AliasType = "host" | "network" | "port" | "url" | "mac" | "nested";

export interface AliasPayload {
  device_id?: string | null;
  name: string;
  description?: string | null;
  type: AliasType;
  content?: string[];
  enabled?: boolean;
}

export type AliasUpdatePayload = Partial<Pick<AliasPayload, "description" | "content" | "enabled">>;

export type NatType = "port_forward" | "outbound" | "one_to_one";

export interface NatRulePayload {
  device_id?: string | null;
  name: string;
  description?: string | null;
  type: NatType;
  interface?: string;
  protocol?: string;
  source?: string;
  destination?: string;
  destination_port?: string | null;
  target: string;
  target_port?: string | null;
  enabled?: boolean;
  order_index?: number;
}

export type NatRuleUpdatePayload = Partial<Omit<NatRulePayload, "device_id" | "name" | "type">>;

export interface InterfaceInfo {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string;
  name: string;
  description: string | null;
  physical_if: string | null;
  ip_address: string | null;
  subnet_bits: number | null;
  gateway: string | null;
  dhcp: boolean;
  enabled: boolean;
}

export type DnsRecordType = "A" | "AAAA" | "CNAME" | "MX" | "TXT" | "SRV" | "PTR" | "NS";

export interface DhcpScope {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string;
  name: string;
  description: string | null;
  subnet: string;
  pool_start: string;
  pool_end: string;
  gateway: string | null;
  dns_servers: string[];
  domain_name: string | null;
  lease_time_seconds: number;
  enabled: boolean;
  options: Record<string, string>;
}

export interface DhcpScopePayload {
  device_id: string;
  name: string;
  description?: string | null;
  subnet: string;
  pool_start: string;
  pool_end: string;
  gateway?: string | null;
  dns_servers?: string[];
  domain_name?: string | null;
  lease_time_seconds?: number;
  enabled?: boolean;
  options?: Record<string, string>;
}

export type DhcpScopeUpdate = Partial<Omit<DhcpScopePayload, "device_id" | "name" | "subnet">>;

export interface DhcpReservation {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string;
  scope_id: string;
  hostname: string;
  mac_address: string;
  ip_address: string;
  description: string | null;
  enabled: boolean;
}

export interface DhcpReservationPayload {
  scope_id: string;
  hostname: string;
  mac_address: string;
  ip_address: string;
  description?: string | null;
  enabled?: boolean;
}

export type DhcpReservationUpdate = Partial<
  Pick<DhcpReservationPayload, "hostname" | "mac_address" | "ip_address" | "description" | "enabled">
>;

export interface DnsRecord {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string;
  name: string;
  record_type: DnsRecordType;
  value: string;
  ttl: number;
  priority: number | null;
  weight: number | null;
  port: number | null;
  description: string | null;
  enabled: boolean;
}

export interface DnsRecordPayload {
  device_id: string;
  name: string;
  record_type: DnsRecordType;
  value: string;
  ttl?: number;
  priority?: number | null;
  weight?: number | null;
  port?: number | null;
  description?: string | null;
  enabled?: boolean;
}

export type DnsRecordUpdate = Partial<
  Pick<DnsRecordPayload, "value" | "ttl" | "priority" | "weight" | "port" | "description" | "enabled">
>;

/* ------------------------------------------------------------ IPsec */

export type IpsecIkeType = "ikev1" | "ikev2";
export type IpsecAuthMethod = "pre_shared_key" | "rsa" | "ecdsa" | "x509";
export type IpsecNatTraversal = "force" | "disable" | "auto";
export type IpsecMode = "tunnel" | "transport";
export type IpsecProtocol = "esp" | "ah" | "esp-ah";

export interface IpsecPhase1 {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  iketype: IpsecIkeType;
  interface: string;
  remote_gateway: string;
  local_gateway: string | null;
  authentication_method: IpsecAuthMethod;
  my_identifier: string | null;
  peer_identifier: string | null;
  encryption: string[];
  hash: string[];
  dh_group: string;
  lifetime: number;
  dpd_delay: number;
  dpd_maxfail: number;
  nat_traversal: IpsecNatTraversal;
}

export interface IpsecPhase1Payload {
  device_id: string;
  name: string;
  description?: string | null;
  enabled?: boolean;
  iketype?: IpsecIkeType;
  interface?: string;
  remote_gateway: string;
  local_gateway?: string | null;
  authentication_method?: IpsecAuthMethod;
  pre_shared_key?: string | null;
  my_identifier?: string | null;
  peer_identifier?: string | null;
  encryption?: string[];
  hash?: string[];
  dh_group?: string;
  lifetime?: number;
  dpd_delay?: number;
  dpd_maxfail?: number;
  nat_traversal?: IpsecNatTraversal;
}

export type IpsecPhase1Update = Partial<
  Pick<
    IpsecPhase1Payload,
    | "description"
    | "enabled"
    | "iketype"
    | "interface"
    | "remote_gateway"
    | "local_gateway"
    | "authentication_method"
    | "pre_shared_key"
    | "my_identifier"
    | "peer_identifier"
    | "encryption"
    | "hash"
    | "dh_group"
    | "lifetime"
    | "dpd_delay"
    | "dpd_maxfail"
    | "nat_traversal"
  >
>;

export interface IpsecPhase2 {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string;
  phase1_id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  mode: IpsecMode;
  protocol: IpsecProtocol;
  local_net: string;
  remote_net: string;
  encryption: string[];
  hash: string[];
  pfs_group: string;
  lifetime: number;
}

export interface IpsecPhase2Payload {
  device_id: string;
  phase1_id: string;
  name: string;
  description?: string | null;
  enabled?: boolean;
  mode?: IpsecMode;
  protocol?: IpsecProtocol;
  local_net: string;
  remote_net: string;
  encryption?: string[];
  hash?: string[];
  pfs_group?: string;
  lifetime?: number;
}

export type IpsecPhase2Update = Partial<
  Pick<
    IpsecPhase2Payload,
    | "description"
    | "enabled"
    | "mode"
    | "protocol"
    | "local_net"
    | "remote_net"
    | "encryption"
    | "hash"
    | "pfs_group"
    | "lifetime"
  >
>;

export interface Certificate {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string;
  serial_number: string;
  subject_cn: string;
  issuer_cn: string;
  fingerprint_sha256: string;
  valid_from: string;
  valid_to: string;
  status: string;
  revoked_at: string | null;
}

export interface Enrollment {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  site_id: string | null;
  token_hint: string;
  device_serial: string | null;
  device_mac: string | null;
  hostname: string | null;
  status: ZtpStatus;
  discovery_method: string;
  template_id: string | null;
  group_id: string | null;
  device_id: string | null;
  certificate_serial: string | null;
  hardware_profile: Record<string, unknown>;
  enrolled_at: string | null;
  provisioned_at: string | null;
  expires_at: string;
}

export interface BootstrapPackage {
  enrollment_id: string;
  token: string;
  bootstrap_url: string;
  script: string;
  expires_at: string;
}

export interface EnrollmentTokenResponse {
  enrollment_id: string;
  token: string;
  expires_at: string;
  bootstrap_url: string;
  site_id: string | null;
  template_id: string | null;
}

export interface ChangeRequest {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  title: string;
  description: string | null;
  type: string;
  resource_type: string | null;
  resource_id: string | null;
  payload: Record<string, unknown>;
  status: string;
  priority: string;
  environment: Environment | null;
  requested_by: string | null;
  required_approvals: number;
  approvals: Array<Record<string, unknown>>;
  expires_at: string | null;
  applied_at: string | null;
}

export interface DiscoveryResult {
  ip_address: string;
  port: number;
  hostname: string | null;
  firmware_version: string | null;
  serial_number: string | null;
  reachable: boolean;
  already_managed: boolean;
}

export interface VersionInfo {
  name: string;
  version: string;
  environment: string;
  api_version: string;
  python: string;
  server_time: string;
}

export interface ComponentHealth {
  status: string;
  latency_ms: number | null;
  detail: string | null;
}

export interface ReadinessReport {
  status: string;
  components: Record<string, ComponentHealth>;
  checked_at: string;
  version: string;
  environment: string;
}

/* ------------------------------------------------------- notifications */

export interface NotificationDelivery {
  status: "sent" | "failed" | "skipped" | string;
  at?: string;
  reason?: string;
  error?: string;
}

export interface NotificationCreatePayload {
  title: string;
  message: string;
  type?: string;
  severity?: AlertSeverity;
  user_id?: string | null;
  action_url?: string | null;
  channels?: string[];
  metadata?: Record<string, unknown>;
}

/* ---------------------------------------------------- high availability */

export type HaNodeRole = "primary" | "secondary";

export interface HaNode {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  device_id: string;
  role: HaNodeRole;
  advskew: number;
  status: string;
  vip_uuid: string | null;
  last_seen_at: string | null;
  details: Record<string, unknown>;
}

export interface HaNodePayload {
  device_id: string;
  role: HaNodeRole;
  advskew: number;
}

export interface HaCluster {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  name: string;
  description: string | null;
  site_id: string | null;
  virtual_ip: string;
  interface: string;
  vhid: number;
  advbase: number;
  enabled: boolean;
  sync_status: string;
  last_sync_at: string | null;
  nodes: HaNode[];
}

export interface HaClusterPayload {
  name: string;
  description?: string | null;
  site_id?: string | null;
  virtual_ip: string;
  interface: string;
  vhid: number;
  advbase: number;
  password?: string | null;
  enabled: boolean;
  nodes?: HaNodePayload[];
}

export interface HaFailoverResult {
  cluster_id: string;
  promoted_device_id: string;
  demoted_device_id: string;
  applied: boolean;
  nodes: HaNode[];
}

/* ---------------------------------------------------------- VPN status */

export interface WireGuardKey {
  id: string;
  created_at: ISODate;
  updated_at: ISODate;
  topology_id: string;
  device_id: string;
  public_key: string;
  listen_port: number;
  tunnel_address: string;
}

export interface VpnEndpointStatus {
  device_id: string | null;
  device: string | null;
  state: string;
  last_handshake_at: string | null;
  details: Record<string, unknown>;
}

export interface VpnTunnelStatus {
  tunnel_id: string;
  name: string;
  protocol: VpnProtocol;
  status: TunnelStatus;
  endpoints: VpnEndpointStatus[];
}

export interface VpnStatus {
  topology_id: string;
  generated_at: string;
  tunnels: VpnTunnelStatus[];
  errors: string[];
}

