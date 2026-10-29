import { cleanParams, del, get, getBlob, patch, post, put } from "./client";
import type {
  Alert,
  AlertRule,
  Alias,
  AliasPayload,
  AliasUpdatePayload,
  ApiKey,
  ApiKeyCreated,
  ApiKeyPayload,
  AuditEntry,
  AuditIntegrity,
  AuthProviders,
  AuthUser,
  Backup,
  BackupPayload,
  BackupRestorePayload,
  BackupVerification,
  BootstrapPackage,
  Certificate,
  ChangeRequest,
  ComplianceFramework,
  ComplianceReport,
  ComplianceRunPayload,
  ComplianceSummary,
  DashboardOverview,
  Deployment,
  Device,
  DeviceCommand,
  DeviceCommandAction,
  DeviceCommandStatus,
  DeviceCreate,
  DeviceGroup,
  DeviceGroupPayload,
  DeviceHealth,
  DeviceSearchResult,
  DeviceSummary,
  DeviceUpdate,
  DhcpReservation,
  DhcpReservationPayload,
  DhcpReservationUpdate,
  DhcpScope,
  DhcpScopePayload,
  DhcpScopeUpdate,
  DiscoveryResult,
  DnsRecord,
  DnsRecordPayload,
  DnsRecordUpdate,
  DriftReport,
  Enrollment,
  EnrollmentTokenResponse,
  Environment,
  FleetSummary,
  FleetTraffic,
  FirmwareAction,
  FirmwareStatus,
  GitRepository,
  GitRepositoryPayload,
  GroupTreeNode,
  HaCluster,
  HaClusterPayload,
  HaFailoverResult,
  InterfaceInfo,
  Job,
  JobPayload,
  LoginPayload,
  LoginResponse,
  Message,
  MfaSetup,
  MfaVerifyPayload,
  MetricSeries,
  NatRule,
  NatRulePayload,
  NatRuleUpdatePayload,
  Notification,
  NotificationCreatePayload,
  Page,
  Permission,
  Policy,
  PolicyDiff,
  PolicyPayload,
  PolicyValidation,
  ReadinessReport,
  Role,
  RoleMatrixEntry,
  Rule,
  RuleDeployResult,
  RulePayload,
  RuleUpdatePayload,
  ScheduledTask,
  ScheduledTaskPayload,
  SdwanLink,
  SessionInfo,
  Site,
  SiteMapPoint,
  SitePayload,
  Template,
  TemplatePayload,
  TemplateRenderResponse,
  Tenant,
  TenantStats,
  Topology,
  TopologyDeployResult,
  TopologyGraph,
  TopologyPayload,
  TrafficPolicy,
  TrafficPolicyPayload,
  TrafficSeries,
  Tunnel,
  TunnelPayload,
  User,
  UserPayload,
  UserUpdatePayload,
  VersionInfo,
  VpnStatus,
  WireGuardKey,
  ClientDevice,
  VendorInfo,
} from "./types";

const P = "/api/v1";

type Query = Record<string, unknown>;

interface ListQuery {
  page?: number;
  size?: number;
  sort?: string;
  order?: "asc" | "desc";
  search?: string;
  [filter: string]: unknown;
}

function listParams(query?: ListQuery & Query): Query {
  return cleanParams(query);
}

/* ------------------------------------------------------------------ health */

export const healthApi = {
  live: () => get<{ status: string }>(`${P}/health/live`),
  ready: () => get<ReadinessReport>(`${P}/health/ready`),
  version: () => get<VersionInfo>(`${P}/health/version`),
};

/* -------------------------------------------------------------------- auth */

export const authApi = {
  login: (payload: LoginPayload) =>
    post<LoginResponse>(`${P}/auth/login`, payload, { skipRefresh: true }),
  ldapLogin: (payload: LoginPayload) =>
    post<LoginResponse>(`${P}/auth/ldap/login`, payload, { skipRefresh: true }),
  verifyMfa: (payload: MfaVerifyPayload) =>
    post<LoginResponse>(`${P}/auth/mfa/verify`, payload, { skipRefresh: true }),
  refresh: (refreshToken: string) =>
    post<LoginResponse>(`${P}/auth/refresh`, { refresh_token: refreshToken }, { skipRefresh: true }),
  logout: (refreshToken?: string | null, allSessions = false) =>
    post<Message>(`${P}/auth/logout`, { refresh_token: refreshToken ?? null, all_sessions: allSessions }),
  me: () => get<AuthUser>(`${P}/auth/me`),
  providers: () => get<AuthProviders>(`${P}/auth/providers`),
  changePassword: (currentPassword: string, newPassword: string) =>
    post<Message>(`${P}/auth/password`, {
      current_password: currentPassword,
      new_password: newPassword,
    }),
  sessions: () => get<SessionInfo[]>(`${P}/auth/sessions`),
  revokeSessions: () => del<Message>(`${P}/auth/sessions`),
  setupMfa: () => post<MfaSetup>(`${P}/auth/mfa/setup`),
  verifyMfaSetup: (code: string) => post<Message>(`${P}/auth/mfa/verify-setup`, { code }),
  disableMfa: (password: string, code: string) =>
    post<Message>(`${P}/auth/mfa/disable`, { password, code }),
  oidcAuthorize: (tenant?: string, entra = false) =>
    get<{ authorization_url: string; state: string }>(`${P}/auth/oidc/authorize`, {
      tenant: tenant ?? undefined,
      entra,
    }),
  oidcCallback: (code: string, state: string) =>
    post<LoginResponse>(`${P}/auth/oidc/callback`, { code, state }, { skipRefresh: true }),
};

/* ----------------------------------------------------------------- tenancy */

export const tenantsApi = {
  list: (query?: ListQuery) => get<Page<Tenant>>(`${P}/tenants`, listParams(query)),
  current: () => get<Tenant>(`${P}/tenants/current`),
  get: (id: string) => get<Tenant>(`${P}/tenants/${id}`),
  create: (payload: Partial<Tenant> & { name: string; slug: string }) =>
    post<Tenant>(`${P}/tenants`, payload),
  update: (id: string, payload: Partial<Tenant>) => patch<Tenant>(`${P}/tenants/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/tenants/${id}`),
  stats: (id: string) => get<TenantStats>(`${P}/tenants/${id}/stats`),
  devices: (id: string, query?: ListQuery) =>
    get<Page<Device>>(`${P}/tenants/${id}/devices`, listParams(query)),
};

/* ------------------------------------------------------------------- users */

export const usersApi = {
  list: (query?: ListQuery) => get<Page<User>>(`${P}/users`, listParams(query)),
  get: (id: string) => get<User>(`${P}/users/${id}`),
  create: (payload: UserPayload) => post<User>(`${P}/users`, payload),
  update: (id: string, payload: UserUpdatePayload) => patch<User>(`${P}/users/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/users/${id}`),
  resetPassword: (id: string, newPassword: string, revokeSessions = true) =>
    post<Message>(`${P}/users/${id}/reset-password`, {
      new_password: newPassword,
      revoke_sessions: revokeSessions,
    }),
  unlock: (id: string) =>
    post<{ id: string; locked_until: string | null }>(`${P}/users/${id}/unlock`),
};

export const rolesApi = {
  list: () => get<Role[]>(`${P}/roles`),
  create: (payload: { name: string; description?: string | null; permissions: string[] }) =>
    post<Role>(`${P}/roles`, payload),
  update: (id: string, payload: { description?: string | null; permissions?: string[] }) =>
    patch<Role>(`${P}/roles/${id}`, payload),
  matrix: () => get<RoleMatrixEntry[]>(`${P}/roles/matrix`),
  permissions: () => get<Permission[]>(`${P}/permissions`),
};

export const apiKeysApi = {
  list: () => get<ApiKey[]>(`${P}/api-keys`),
  create: (payload: ApiKeyPayload) => post<ApiKeyCreated>(`${P}/api-keys`, payload),
  revoke: (id: string) => del<Message>(`${P}/api-keys/${id}`),
};

/* ------------------------------------------------------------------- sites */

export const sitesApi = {
  list: (query?: ListQuery & { country?: string }) =>
    get<Page<Site>>(`${P}/sites`, listParams(query)),
  get: (id: string) => get<Site>(`${P}/sites/${id}`),
  create: (payload: SitePayload) => post<Site>(`${P}/sites`, payload),
  update: (id: string, payload: Partial<SitePayload>) => patch<Site>(`${P}/sites/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/sites/${id}`),
  devices: (id: string, query?: ListQuery) =>
    get<Page<Device>>(`${P}/sites/${id}/devices`, listParams(query)),
  map: () => get<SiteMapPoint[]>(`${P}/sites/map`),
};

/* ------------------------------------------------------------------ groups */

export const groupsApi = {
  list: (query?: ListQuery & { parent_id?: string }) =>
    get<Page<DeviceGroup>>(`${P}/groups`, listParams(query)),
  tree: () => get<GroupTreeNode[]>(`${P}/groups/tree`),
  get: (id: string) => get<DeviceGroup>(`${P}/groups/${id}`),
  create: (payload: DeviceGroupPayload) => post<DeviceGroup>(`${P}/groups`, payload),
  update: (id: string, payload: Partial<DeviceGroupPayload>) =>
    patch<DeviceGroup>(`${P}/groups/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/groups/${id}`),
  devices: (id: string, query?: ListQuery) =>
    get<Page<Device>>(`${P}/groups/${id}/devices`, listParams(query)),
};

/* ----------------------------------------------------------------- devices */

export const devicesApi = {
  list: (
    query?: ListQuery & {
      status?: string;
      site_id?: string;
      group_id?: string;
    },
  ) => get<Page<Device>>(`${P}/devices`, listParams(query)),
  summary: () => get<DeviceSummary>(`${P}/devices/summary`),
  search: (term: string, limit = 20) =>
    get<DeviceSearchResult[]>(`${P}/devices/search`, { q: term, limit }),
  get: (id: string) => get<Device>(`${P}/devices/${id}`),
  create: (payload: DeviceCreate) => post<Device>(`${P}/devices`, payload),
  update: (id: string, payload: DeviceUpdate) => patch<Device>(`${P}/devices/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/devices/${id}`),
  maintenance: (id: string, enabled: boolean) =>
    post<Device>(`${P}/devices/${id}/maintenance`, { enabled }),
  probe: (id: string) => post<Record<string, unknown>>(`${P}/devices/${id}/probe`),
  heartbeat: (id: string, payload?: Record<string, unknown>) =>
    post<Record<string, unknown>>(`${P}/devices/${id}/heartbeat`, payload ?? {}),
  discover: (payload: { cidr: string; port?: number; timeout?: number }) =>
    post<DiscoveryResult[]>(`${P}/devices/discover`, payload),
  certificates: (id: string) => get<Certificate[]>(`${P}/devices/${id}/certificates`),
  issueCertificate: (id: string, commonName?: string, validityDays?: number) =>
    post<Certificate>(`${P}/devices/${id}/certificates`, {
      common_name: commonName ?? null,
      validity_days: validityDays ?? null,
    }),
  commands: (id: string) => get<DeviceCommandStatus>(`${P}/devices/${id}/commands`),
  sendCommand: (id: string, action: DeviceCommandAction, payload: Record<string, unknown> = {}) =>
    post<DeviceCommand>(`${P}/devices/${id}/commands`, { action, payload }),
  firmwareStatus: (id: string) => get<FirmwareStatus>(`${P}/devices/${id}/firmware/status`),
  upgradeFirmware: (id: string, packageName?: string) =>
    post<FirmwareAction>(`${P}/devices/${id}/firmware/upgrade`, { package: packageName ?? null }),
  rebootDevice: (id: string) => post<FirmwareAction>(`${P}/devices/${id}/firmware/reboot`),
};

/* ------------------------------------------------- device-scoped SD-WAN (IPsec/WG/OVPN/VLAN/DHCP/DNS) */

export const deviceSdwanApi = {
  ipsecTunnels: (id: string) => get<unknown[]>(`${P}/sdwan/devices/${id}/ipsec/tunnels`),
  createIpsecTunnel: (id: string, phase1: Record<string, unknown>, phase2: Record<string, unknown>) =>
    post<unknown>(`${P}/sdwan/devices/${id}/ipsec/tunnels`, { phase1, phase2 }),
  applyIpsec: (id: string) => post<Message>(`${P}/sdwan/devices/${id}/ipsec/apply`),
  wireguardServers: (id: string) => get<unknown[]>(`${P}/sdwan/devices/${id}/wireguard/servers`),
  createWireguardServer: (id: string, payload: Record<string, unknown>) =>
    post<unknown>(`${P}/sdwan/devices/${id}/wireguard/servers`, payload),
  deleteWireguardServer: (id: string, uuid: string) =>
    del<Message>(`${P}/sdwan/devices/${id}/wireguard/servers/${uuid}`),
  applyWireguard: (id: string) => post<Message>(`${P}/sdwan/devices/${id}/wireguard/apply`),
  openvpnInstances: (id: string) => get<unknown[]>(`${P}/sdwan/devices/${id}/openvpn/instances`),
  createOpenvpnInstance: (id: string, payload: Record<string, unknown>) =>
    post<unknown>(`${P}/sdwan/devices/${id}/openvpn/instances`, payload),
  deleteOpenvpnInstance: (id: string, uuid: string) =>
    del<Message>(`${P}/sdwan/devices/${id}/openvpn/instances/${uuid}`),
  applyOpenvpn: (id: string) => post<Message>(`${P}/sdwan/devices/${id}/openvpn/apply`),
  vlans: (id: string) => get<unknown[]>(`${P}/sdwan/devices/${id}/vlans`),
  createVlan: (id: string, payload: Record<string, unknown>) =>
    post<unknown>(`${P}/sdwan/devices/${id}/vlans`, payload),
  deleteVlan: (id: string, uuid: string) =>
    del<Message>(`${P}/sdwan/devices/${id}/vlans/${uuid}`),
  dhcpLeases: (id: string) => get<unknown[]>(`${P}/sdwan/devices/${id}/dhcp/leases`),
  dhcpRelays: (id: string) => get<unknown[]>(`${P}/sdwan/devices/${id}/dhcp/relays`),
  dnsRecords: (id: string) => get<unknown[]>(`${P}/sdwan/devices/${id}/dns/records`),
  dnsOverrides: (id: string) => get<unknown[]>(`${P}/sdwan/devices/${id}/dns/overrides`),
};

export const certificatesApi = {
  list: (query?: ListQuery & { status?: string; device_id?: string }) =>
    get<Page<Certificate>>(`${P}/certificates`, listParams(query)),
  revoke: (id: string) => del<Message>(`${P}/certificates/${id}`),
  crl: () => get<string>(`${P}/certificates/crl`),
};

/* ------------------------------------------------------------------- DHCP */

export const dhcpApi = {
  scopes: (query?: ListQuery & { device_id?: string; enabled?: boolean }) =>
    get<Page<DhcpScope>>(`${P}/dhcp/scopes`, listParams(query)),
  scope: (id: string) => get<DhcpScope>(`${P}/dhcp/scopes/${id}`),
  createScope: (payload: DhcpScopePayload) => post<DhcpScope>(`${P}/dhcp/scopes`, payload),
  updateScope: (id: string, payload: DhcpScopeUpdate) =>
    patch<DhcpScope>(`${P}/dhcp/scopes/${id}`, payload),
  removeScope: (id: string) => del<Message>(`${P}/dhcp/scopes/${id}`),
  reservations: (query?: ListQuery & { scope_id?: string; device_id?: string; enabled?: boolean }) =>
    get<Page<DhcpReservation>>(`${P}/dhcp/reservations`, listParams(query)),
  reservation: (id: string) => get<DhcpReservation>(`${P}/dhcp/reservations/${id}`),
  createReservation: (payload: DhcpReservationPayload) =>
    post<DhcpReservation>(`${P}/dhcp/reservations`, payload),
  updateReservation: (id: string, payload: DhcpReservationUpdate) =>
    patch<DhcpReservation>(`${P}/dhcp/reservations/${id}`, payload),
  removeReservation: (id: string) => del<Message>(`${P}/dhcp/reservations/${id}`),
  apply: (payload: { device_id: string; dry_run?: boolean; apply?: boolean }) =>
    post<Record<string, unknown>>(`${P}/dhcp/apply`, payload),
};

/* -------------------------------------------------------------------- DNS */

export const dnsApi = {
  records: (query?: ListQuery & { device_id?: string; record_type?: string; enabled?: boolean }) =>
    get<Page<DnsRecord>>(`${P}/dns/records`, listParams(query)),
  record: (id: string) => get<DnsRecord>(`${P}/dns/records/${id}`),
  createRecord: (payload: DnsRecordPayload) => post<DnsRecord>(`${P}/dns/records`, payload),
  updateRecord: (id: string, payload: DnsRecordUpdate) =>
    patch<DnsRecord>(`${P}/dns/records/${id}`, payload),
  removeRecord: (id: string) => del<Message>(`${P}/dns/records/${id}`),
  apply: (payload: { device_id: string; dry_run?: boolean; apply?: boolean }) =>
    post<Record<string, unknown>>(`${P}/dns/apply`, payload),
};

/* ------------------------------------------------------------ firewall rules */

export const rulesApi = {
  list: (
    query?: ListQuery & {
      device_id?: string;
      group_id?: string;
      action?: string;
      enabled?: boolean;
    },
  ) => get<Page<Rule>>(`${P}/rules`, listParams(query)),
  get: (id: string) => get<Rule>(`${P}/rules/${id}`),
  create: (payload: RulePayload) => post<Rule>(`${P}/rules`, payload),
  update: (id: string, payload: RuleUpdatePayload) => patch<Rule>(`${P}/rules/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/rules/${id}`),
  conflicts: (id: string) => get<Array<Record<string, unknown>>>(`${P}/rules/${id}/conflicts`),
  reorder: (deviceId: string, ruleIds: string[]) =>
    post<Message>(`${P}/rules/reorder`, { device_id: deviceId, rule_ids: ruleIds }),
  deploy: (deviceId: string, dryRun = false) =>
    post<RuleDeployResult>(`${P}/rules/deploy/${deviceId}?dry_run=${dryRun ? "true" : "false"}`),
};

/* ----------------------------------------------------------------- aliases */

export const aliasesApi = {
  list: (query?: ListQuery & { device_id?: string; type?: string }) =>
    get<Page<Alias>>(`${P}/aliases`, listParams(query)),
  get: (id: string) => get<Alias>(`${P}/aliases/${id}`),
  create: (payload: AliasPayload) => post<Alias>(`${P}/aliases`, payload),
  update: (id: string, payload: AliasUpdatePayload) => patch<Alias>(`${P}/aliases/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/aliases/${id}`),
};

/* -------------------------------------------------------------------- NAT */

export const natApi = {
  list: (query?: ListQuery & { device_id?: string; type?: string }) =>
    get<Page<NatRule>>(`${P}/nat`, listParams(query)),
  get: (id: string) => get<NatRule>(`${P}/nat/${id}`),
  create: (payload: NatRulePayload) => post<NatRule>(`${P}/nat`, payload),
  update: (id: string, payload: NatRuleUpdatePayload) =>
    patch<NatRule>(`${P}/nat/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/nat/${id}`),
  apply: (payload: { device_id: string; dry_run?: boolean; apply?: boolean }) =>
    post<Record<string, unknown>>(`${P}/nat/apply`, payload),
};

/* --------------------------------------------------------------- templates */

export const templatesApi = {
  list: (query?: ListQuery & { kind?: string; is_active?: boolean }) =>
    get<Page<Template>>(`${P}/templates`, listParams(query)),
  get: (id: string) => get<Template>(`${P}/templates/${id}`),
  create: (payload: TemplatePayload) => post<Template>(`${P}/templates`, payload),
  update: (id: string, payload: Partial<TemplatePayload>) =>
    patch<Template>(`${P}/templates/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/templates/${id}`),
  render: (id: string, variables: Record<string, unknown>) =>
    post<TemplateRenderResponse>(`${P}/templates/${id}/render`, { variables }),
  effective: (id: string) => get<Record<string, unknown>>(`${P}/templates/${id}/effective`),
};

/* ---------------------------------------------------------------- policies */

export const policiesApi = {
  list: (
    query?: ListQuery & { kind?: string; environment?: Environment; status?: string },
  ) => get<Page<Policy>>(`${P}/policies`, listParams(query)),
  get: (id: string) => get<Policy>(`${P}/policies/${id}`),
  create: (payload: PolicyPayload) => post<Policy>(`${P}/policies`, payload),
  update: (id: string, payload: Partial<PolicyPayload> & { status?: string }) =>
    patch<Policy>(`${P}/policies/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/policies/${id}`),
  validate: (id: string) => post<PolicyValidation>(`${P}/policies/${id}/validate`),
  diff: (id: string, against?: string) =>
    get<PolicyDiff>(`${P}/policies/${id}/diff`, { against: against ?? undefined }),
  simulate: (
    id: string,
    payload: {
      source_ip: string;
      destination_ip: string;
      protocol?: string;
      destination_port?: number | null;
      interface?: string | null;
    },
  ) => post<Record<string, unknown>>(`${P}/policies/${id}/simulate`, payload),
  deploy: (
    id: string,
    payload: { device_ids?: string[]; dry_run?: boolean; change_request_id?: string | null },
  ) => post<Deployment>(`${P}/policies/${id}/deploy`, payload),
  promote: (
    id: string,
    payload: {
      source_environment: Environment;
      target_environment: Environment;
      create_change_request?: boolean;
    },
  ) => post<Record<string, unknown>>(`${P}/policies/${id}/promote`, payload),
};

export const deploymentsApi = {
  list: (query?: ListQuery & { policy_id?: string; environment?: Environment }) =>
    get<Page<Deployment>>(`${P}/deployments`, listParams(query)),
  get: (id: string) => get<Deployment>(`${P}/deployments/${id}`),
  rollback: (id: string) => post<Deployment>(`${P}/deployments/${id}/rollback`),
};

export const driftApi = {
  list: (query?: ListQuery & { status?: string; device_id?: string }) =>
    get<Page<DriftReport>>(`${P}/drift`, listParams(query)),
  scan: (deviceIds?: string[]) =>
    post<{ reports: DriftReport[]; scanned: number }>(`${P}/drift/scan`, {
      device_ids: deviceIds ?? [],
    }),
  resolve: (id: string, notes?: string) =>
    post<DriftReport>(`${P}/drift/${id}/resolve`, { notes: notes ?? null }),
};

export const changesApi = {
  list: (query?: ListQuery & { status?: string }) =>
    get<Page<ChangeRequest>>(`${P}/changes`, listParams(query)),
  get: (id: string) => get<ChangeRequest>(`${P}/changes/${id}`),
  create: (payload: Partial<ChangeRequest> & { title: string; type: string }) =>
    post<ChangeRequest>(`${P}/changes`, payload),
  approve: (id: string, comment?: string) =>
    post<ChangeRequest>(`${P}/changes/${id}/approve`, { comment: comment ?? null }),
  reject: (id: string, comment?: string) =>
    post<ChangeRequest>(`${P}/changes/${id}/reject`, { comment: comment ?? null }),
  cancel: (id: string) => post<ChangeRequest>(`${P}/changes/${id}/cancel`),
};

/* -------------------------------------------------------------------- git */

export const gitApi = {
  repositories: (query?: ListQuery) =>
    get<Page<GitRepository>>(`${P}/git/repositories`, listParams(query)),
  repository: (id: string) => get<GitRepository>(`${P}/git/repositories/${id}`),
  createRepository: (payload: GitRepositoryPayload) =>
    post<GitRepository>(`${P}/git/repositories`, payload),
  updateRepository: (id: string, payload: Partial<GitRepositoryPayload>) =>
    patch<GitRepository>(`${P}/git/repositories/${id}`, payload),
  removeRepository: (id: string) => del<Message>(`${P}/git/repositories/${id}`),
  sync: (id: string, branch?: string) =>
    post<{ updated: number; created: number; invalid: number; commit_sha: string | null }>(
      `${P}/git/repositories/${id}/sync${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`,
      {},
    ),
  branches: (id: string) => get<string[]>(`${P}/git/repositories/${id}/branches`),
  commits: (id: string, ref?: string) =>
    get<Array<{ sha: string; message: string; author: string; date: string }>>(
      `${P}/git/repositories/${id}/commits`,
      { ref: ref ?? undefined },
    ),
  file: (id: string, path: string, ref?: string) =>
    get<{ path: string; ref: string; content: string }>(`${P}/git/repositories/${id}/file`, {
      path,
      ref: ref ?? undefined,
    }),
  importPolicy: (
    id: string,
    payload: { path: string; name?: string | null; environment?: Environment; ref?: string | null },
  ) => post<Policy>(`${P}/git/repositories/${id}/import`, payload),
  rotateWebhookSecret: (id: string) =>
    post<{ repository_id: string; secret: string; instructions: string }>(
      `${P}/git/repositories/${id}/webhook-secret`,
    ),
  publish: (
    policyId: string,
    payload: {
      branch: string;
      message: string;
      base_branch?: string;
      open_pull_request?: boolean;
      pull_request_title?: string | null;
    },
  ) => post<Record<string, unknown>>(`${P}/git/policies/${policyId}/publish`, payload),
};

/* ------------------------------------------------------------------ sdwan */

export const sdwanApi = {
  topologies: (query?: ListQuery) => get<Page<Topology>>(`${P}/sdwan/topologies`, listParams(query)),
  topology: (id: string) => get<Topology>(`${P}/sdwan/topologies/${id}`),
  createTopology: (payload: TopologyPayload) => post<Topology>(`${P}/sdwan/topologies`, payload),
  updateTopology: (id: string, payload: Partial<TopologyPayload>) =>
    patch<Topology>(`${P}/sdwan/topologies/${id}`, payload),
  removeTopology: (id: string) => del<Message>(`${P}/sdwan/topologies/${id}`),
  graph: (id: string) => get<TopologyGraph>(`${P}/sdwan/topologies/${id}/graph`),
  deploy: (id: string, payload: { regenerate_keys?: boolean; dry_run?: boolean } = {}) =>
    post<TopologyDeployResult>(`${P}/sdwan/topologies/${id}/deploy`, payload),
  routes: (id: string) => get<Array<Record<string, unknown>>>(`${P}/sdwan/topologies/${id}/routes`),
  syncRoutes: (id: string, deviceId: string) =>
    post<{ installed: number }>(`${P}/sdwan/topologies/${id}/routes/sync/${deviceId}`),
  bestLink: (id: string) => get<SdwanLink | null>(`${P}/sdwan/topologies/${id}/best-link`),
  failover: (id: string) =>
    post<Array<Record<string, unknown>>>(`${P}/sdwan/topologies/${id}/failover`),
  tunnels: (id: string) => get<Tunnel[]>(`${P}/sdwan/topologies/${id}/tunnels`),
  createTunnel: (payload: TunnelPayload) => post<Tunnel>(`${P}/sdwan/tunnels`, payload),
  tunnel: (id: string) => get<Tunnel>(`${P}/sdwan/tunnels/${id}`),
  removeTunnel: (id: string) => del<Message>(`${P}/sdwan/tunnels/${id}`),
  links: (query?: ListQuery & { topology_id?: string }) =>
    get<Page<SdwanLink>>(`${P}/sdwan/links`, listParams(query)),
  measureLink: (
    id: string,
    payload: {
      latency_ms?: number | null;
      jitter_ms?: number | null;
      loss_pct?: number | null;
      bandwidth_mbps?: number | null;
      status?: string | null;
    },
  ) => post<SdwanLink>(`${P}/sdwan/links/${id}/measurements`, payload),
  trafficPolicies: (query?: ListQuery & { topology_id?: string }) =>
    get<Page<TrafficPolicy>>(`${P}/sdwan/traffic-policies`, listParams(query)),
  createTrafficPolicy: (payload: TrafficPolicyPayload) =>
    post<TrafficPolicy>(`${P}/sdwan/traffic-policies`, payload),
  removeTrafficPolicy: (id: string) => del<Message>(`${P}/sdwan/traffic-policies/${id}`),
  vpnStatus: (topologyId: string) =>
    get<VpnStatus>(`${P}/sdwan/topologies/${topologyId}/vpn-status`),
  wireguardKeys: (topologyId: string) =>
    get<WireGuardKey[]>(`${P}/sdwan/topologies/${topologyId}/wireguard-keys`),
};

/* --------------------------------------------------- high availability */

export const haApi = {
  clusters: (query?: ListQuery & { site_id?: string }) =>
    get<Page<HaCluster>>(`${P}/ha/clusters`, listParams(query)),
  cluster: (id: string) => get<HaCluster>(`${P}/ha/clusters/${id}`),
  create: (payload: HaClusterPayload) => post<HaCluster>(`${P}/ha/clusters`, payload),
  update: (id: string, payload: Partial<Omit<HaClusterPayload, "nodes">>) =>
    patch<HaCluster>(`${P}/ha/clusters/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/ha/clusters/${id}`),
  refresh: (id: string) => post<HaCluster>(`${P}/ha/clusters/${id}/refresh`),
  failover: (id: string) => post<HaFailoverResult>(`${P}/ha/clusters/${id}/failover`),
};

/* -------------------------------------------------------------------- ztp */

export const ztpApi = {
  discovery: () => get<Record<string, unknown>>(`${P}/ztp/discovery`),
  bootstrap: (token: string) =>
    get<BootstrapPackage>(`${P}/ztp/bootstrap`, { token }),
  enroll: (payload: Record<string, unknown>) => post<Record<string, unknown>>(`${P}/ztp/enroll`, payload),
  enrollments: (query?: ListQuery & { status?: string; site_id?: string }) =>
    get<Page<Enrollment>>(`${P}/ztp/enrollments`, listParams(query)),
  enrollment: (id: string) => get<Enrollment>(`${P}/ztp/enrollments/${id}`),
  createEnrollment: (payload: {
    site_id?: string | null;
    template_id?: string | null;
    group_id?: string | null;
    device_serial?: string | null;
    device_mac?: string | null;
    hostname?: string | null;
    ttl_minutes?: number;
    discovery_method?: string;
  }) => post<EnrollmentTokenResponse>(`${P}/ztp/enrollments`, payload),
  updateEnrollment: (id: string, status: string) =>
    patch<Enrollment>(`${P}/ztp/enrollments/${id}`, { status }),
  removeEnrollment: (id: string) => del<Message>(`${P}/ztp/enrollments/${id}`),
  revokeEnrollment: (id: string) => post<Enrollment>(`${P}/ztp/enrollments/${id}/revoke`),
};

/* ---------------------------------------------------------------- backups */

export const backupsApi = {
  list: (query?: ListQuery & { device_id?: string; type?: string }) =>
    get<Page<Backup>>(`${P}/backups`, listParams(query)),
  get: (id: string) => get<Backup>(`${P}/backups/${id}`),
  create: (payload: BackupPayload) => post<Backup>(`${P}/backups`, payload),
  remove: (id: string) => del<Message>(`${P}/backups/${id}`),
  verify: (id: string) => get<BackupVerification>(`${P}/backups/${id}/verify`),
  download: (id: string) => getBlob(`${P}/backups/${id}/download`),
  restore: (id: string, payload: Omit<BackupRestorePayload, "backup_id"> = {}) =>
    post<Record<string, unknown>>(`${P}/backups/${id}/restore`, { backup_id: id, ...payload }),
  storageUsage: () => get<{ storage_bytes: number }>(`${P}/backups/storage-usage`),
  sweep: (type = "scheduled") => post<Record<string, unknown>>(`${P}/backups/sweep`, { type }),
  retention: (payload: { retention_days?: number; keep_per_device?: number } = {}) =>
    post<Record<string, unknown>>(`${P}/backups/retention`, payload),
};

/* ------------------------------------------------------------------- jobs */

export const jobsApi = {
  list: (query?: ListQuery & { status?: string; task_name?: string }) =>
    get<Page<Job>>(`${P}/jobs`, listParams(query)),
  get: (id: string) => get<Job>(`${P}/jobs/${id}`),
  create: (payload: JobPayload) => post<Job>(`${P}/jobs`, payload),
  cancel: (id: string) => post<Job>(`${P}/jobs/${id}/cancel`),
};

export const tasksApi = {
  list: (query?: ListQuery & { enabled?: boolean }) =>
    get<Page<ScheduledTask>>(`${P}/tasks`, listParams(query)),
  get: (id: string) => get<ScheduledTask>(`${P}/tasks/${id}`),
  create: (payload: ScheduledTaskPayload) => post<ScheduledTask>(`${P}/tasks`, payload),
  update: (id: string, payload: Partial<Omit<ScheduledTaskPayload, "kind">>) =>
    patch<ScheduledTask>(`${P}/tasks/${id}`, payload),
  remove: (id: string) => del<Message>(`${P}/tasks/${id}`),
  run: (id: string) => post<Job>(`${P}/tasks/${id}/run`),
};

/* ----------------------------------------------------------------- alerts */

export const alertsApi = {
  list: (query?: ListQuery & { status?: string; severity?: string; device_id?: string }) =>
    get<Page<Alert>>(`${P}/alerts`, listParams(query)),
  counts: () => get<Record<string, number>>(`${P}/alerts/counts`),
  get: (id: string) => get<Alert>(`${P}/alerts/${id}`),
  acknowledge: (id: string, comment?: string) =>
    post<Alert>(`${P}/alerts/${id}/acknowledge`, { comment: comment ?? null }),
  resolve: (id: string) => post<Alert>(`${P}/alerts/${id}/resolve`),
  rules: (query?: ListQuery) => get<Page<AlertRule>>(`${P}/alert-rules`, listParams(query)),
  createRule: (payload: Partial<AlertRule>) => post<AlertRule>(`${P}/alert-rules`, payload),
  updateRule: (id: string, payload: Partial<AlertRule>) =>
    patch<AlertRule>(`${P}/alert-rules/${id}`, payload),
  removeRule: (id: string) => del<Message>(`${P}/alert-rules/${id}`),
  testRule: (id: string) => post<Record<string, unknown>>(`${P}/alert-rules/${id}/test`),
};

export const notificationsApi = {
  list: (query?: ListQuery & { unread_only?: boolean }) =>
    get<Page<Notification>>(`${P}/notifications`, listParams(query)),
  create: (payload: NotificationCreatePayload) => post<Notification>(`${P}/notifications`, payload),
  read: (id: string) => post<Message>(`${P}/notifications/${id}/read`),
  readAll: () => post<Message>(`${P}/notifications/read-all`),
  remove: (id: string) => del<Message>(`${P}/notifications/${id}`),
};

/* ---------------------------------------------------------------- metrics */

export const metricsApi = {
  summary: () => get<FleetSummary>(`${P}/metrics/summary`),
  health: () => get<DeviceHealth[]>(`${P}/metrics/health`),
  trends: (hours = 24) => get<DashboardOverview["trends"]>(`${P}/metrics/trends`, { hours }),
  dashboard: () => get<DashboardOverview>(`${P}/metrics/dashboard`),
  deviceSeries: (deviceId: string, metricType = "cpu", hours = 24, limit = 500) =>
    get<MetricSeries>(`${P}/metrics/devices/${deviceId}/series`, {
      metric_type: metricType,
      hours,
      limit,
    }),
  deviceTraffic: (deviceId: string, interfaceName = "wan", hours = 24) =>
    get<TrafficSeries>(`${P}/metrics/devices/${deviceId}/traffic`, {
      interface: interfaceName,
      hours,
    }),
  fleetTraffic: (interfaceName = "wan", hours = 24) =>
    get<FleetTraffic>(`${P}/metrics/traffic`, { interface: interfaceName, hours }),
  aggregate: (hours = 24) => get<Record<string, unknown>>(`${P}/metrics/aggregate`, { hours }),
};

/* ------------------------------------------------------------- inventory */

export const inventoryApi = {
  list: (query?: ListQuery & { status?: string; source?: string; search?: string }) =>
    get<ClientDevice[]>(`${P}/inventory/clients`, cleanParams(query)),
  get: (mac: string) => get<ClientDevice>(`${P}/inventory/clients/${mac}`),
  block: (mac: string, reason?: string) =>
    post<Message>(`${P}/inventory/clients/${mac}/block`, { mac_address: mac, reason }),
  pause: (mac: string, minutes: number, reason?: string) =>
    post<Message>(`${P}/inventory/clients/${mac}/pause`, { mac_address: mac, minutes, reason }),
  unblock: (mac: string) => post<Message>(`${P}/inventory/clients/${mac}/unblock`),
  vendors: (macs: string[]) => post<VendorInfo[]>(`${P}/inventory/vendors`, { macs }),
};

/* ------------------------------------------------------------------ audit */

export const auditApi = {
  list: (
    query?: ListQuery & {
      action?: string;
      resource_type?: string;
      resource_id?: string;
      user_id?: string;
      result?: string;
      from_date?: string;
      to_date?: string;
    },
  ) => get<Page<AuditEntry>>(`${P}/audit`, listParams(query)),
  get: (id: number) => get<AuditEntry>(`${P}/audit/${id}`),
  integrity: () => get<AuditIntegrity>(`${P}/audit/integrity`),
  actions: () =>
    get<Array<{ action: string; resource_type: string; count: number }>>(`${P}/audit/actions`),
  export: (query?: Query) =>
    get<Blob>(`${P}/audit/export`, cleanParams(query), { responseType: "blob", timeout: 120_000 }),
  events: (aggregateType: string, aggregateId: string) =>
    get<Array<Record<string, unknown>>>(`${P}/audit/events/${aggregateType}/${aggregateId}`),
};

/* ------------------------------------------------------------- compliance */

export const complianceApi = {
  frameworks: () =>
    get<Array<{ framework: ComplianceFramework; title: string; controls: number }>>(
      `${P}/compliance/frameworks`,
    ),
  run: (payload: ComplianceRunPayload) => post<ComplianceReport>(`${P}/compliance/run`, payload),
  summary: () => get<ComplianceSummary[]>(`${P}/compliance/summary`),
  reports: (query?: ListQuery & { framework?: ComplianceFramework }) =>
    get<Page<ComplianceReport>>(`${P}/compliance/reports`, listParams(query)),
  report: (id: string) => get<ComplianceReport>(`${P}/compliance/reports/${id}`),
  removeReport: (id: string) => del<Message>(`${P}/compliance/reports/${id}`),
  evidence: (id: string) => get<Record<string, unknown>>(`${P}/compliance/reports/${id}/evidence`),
  remediate: (payload: { finding_ids?: string[]; device_ids?: string[]; dry_run?: boolean }) =>
    post<Record<string, unknown>>(`${P}/compliance/remediate`, payload),
};

/* ------------------------------------------------------------------ misc */

export const uiApi = {
  searchDevices: (term: string) => devicesApi.search(term, 8),
};

export type { Rule, Alias, NatRule, InterfaceInfo, Certificate };
export { put };
