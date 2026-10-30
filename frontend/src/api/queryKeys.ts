/**
 * Central TanStack Query keys. Every list key starts with the resource name so
 * that the realtime bridge can invalidate broad prefixes (`["devices"]`).
 */
export const qk = {
  dashboard: ["dashboard"] as const,
  health: ["health"] as const,
  fleetTraffic: (interfaceName: string, hours: number) =>
    ["metrics", "traffic", interfaceName, hours] as const,

  devices: {
    all: ["devices"] as const,
    list: (params: unknown) => ["devices", "list", params] as const,
    detail: (id: string) => ["devices", "detail", id] as const,
    summary: ["devices", "summary"] as const,
    search: (term: string) => ["devices", "search", term] as const,
    certificates: (id: string) => ["devices", id, "certificates"] as const,
    commands: (id: string) => ["devices", id, "commands"] as const,
    firmware: (id: string) => ["devices", id, "firmware"] as const,
    ipsec: (id: string) => ["devices", id, "ipsec"] as const,
    wireguard: (id: string) => ["devices", id, "wireguard"] as const,
    openvpn: (id: string) => ["devices", id, "openvpn"] as const,
    vlan: (id: string) => ["devices", id, "vlan"] as const,
    dhcp: (id: string) => ["devices", id, "dhcp"] as const,
    dns: (id: string) => ["devices", id, "dns"] as const,
    series: (id: string, metric: string, hours: number) =>
      ["devices", id, "series", metric, hours] as const,
    traffic: (id: string, interfaceName: string, hours: number) =>
      ["devices", id, "traffic", interfaceName, hours] as const,
  },
  sites: {
    all: ["sites"] as const,
    list: (params: unknown) => ["sites", "list", params] as const,
    detail: (id: string) => ["sites", "detail", id] as const,
    map: ["sites", "map"] as const,
  },
  groups: {
    all: ["groups"] as const,
    list: (params: unknown) => ["groups", "list", params] as const,
    tree: ["groups", "tree"] as const,
    detail: (id: string) => ["groups", "detail", id] as const,
  },
  templates: {
    all: ["templates"] as const,
    list: (params: unknown) => ["templates", "list", params] as const,
    detail: (id: string) => ["templates", "detail", id] as const,
  },
  dhcp: {
    all: ["dhcp"] as const,
    scopes: (params: unknown) => ["dhcp", "scopes", params] as const,
    scope: (id: string) => ["dhcp", "scope", id] as const,
    reservations: (params: unknown) => ["dhcp", "reservations", params] as const,
    reservation: (id: string) => ["dhcp", "reservation", id] as const,
  },
  dns: {
    all: ["dns"] as const,
    records: (params: unknown) => ["dns", "records", params] as const,
    record: (id: string) => ["dns", "record", id] as const,
  },
  rules: {
    all: ["rules"] as const,
    list: (params: unknown) => ["rules", "list", params] as const,
    detail: (id: string) => ["rules", "detail", id] as const,
    conflicts: (id: string) => ["rules", id, "conflicts"] as const,
  },
  aliases: {
    all: ["aliases"] as const,
    list: (params: unknown) => ["aliases", "list", params] as const,
    detail: (id: string) => ["aliases", "detail", id] as const,
  },
  nat: {
    all: ["nat"] as const,
    list: (params: unknown) => ["nat", "list", params] as const,
    detail: (id: string) => ["nat", "detail", id] as const,
  },
  policies: {
    all: ["policies"] as const,
    list: (params: unknown) => ["policies", "list", params] as const,
    detail: (id: string) => ["policies", "detail", id] as const,
    diff: (id: string) => ["policies", id, "diff"] as const,
  },
  deployments: {
    all: ["deployments"] as const,
    list: (params: unknown) => ["deployments", "list", params] as const,
    detail: (id: string) => ["deployments", "detail", id] as const,
  },
  drift: {
    all: ["drift"] as const,
    list: (params: unknown) => ["drift", "list", params] as const,
  },
  changes: {
    all: ["changes"] as const,
    list: (params: unknown) => ["changes", "list", params] as const,
    detail: (id: string) => ["changes", "detail", id] as const,
  },
  git: {
    all: ["git"] as const,
    repositories: (params: unknown) => ["git", "repositories", params] as const,
    repository: (id: string) => ["git", "repository", id] as const,
  },
  sdwan: {
    all: ["sdwan"] as const,
    topologies: (params: unknown) => ["sdwan", "topologies", params] as const,
    topology: (id: string) => ["sdwan", "topology", id] as const,
    graph: (id: string) => ["sdwan", "topology", id, "graph"] as const,
    tunnels: (id: string) => ["sdwan", "topology", id, "tunnels"] as const,
    routes: (id: string) => ["sdwan", "topology", id, "routes"] as const,
    links: (params: unknown) => ["sdwan", "links", params] as const,
    trafficPolicies: (params: unknown) => ["sdwan", "traffic-policies", params] as const,
  },
  ztp: {
    all: ["ztp"] as const,
    enrollments: (params: unknown) => ["ztp", "enrollments", params] as const,
    enrollment: (id: string) => ["ztp", "enrollment", id] as const,
  },
  backups: {
    all: ["backups"] as const,
    list: (params: unknown) => ["backups", "list", params] as const,
    detail: (id: string) => ["backups", "detail", id] as const,
    usage: ["backups", "usage"] as const,
  },
  jobs: {
    all: ["jobs"] as const,
    list: (params: unknown) => ["jobs", "list", params] as const,
    detail: (id: string) => ["jobs", "detail", id] as const,
  },
  tasks: {
    all: ["tasks"] as const,
    list: (params: unknown) => ["tasks", "list", params] as const,
  },
  alerts: {
    all: ["alerts"] as const,
    list: (params: unknown) => ["alerts", "list", params] as const,
    counts: ["alerts", "counts"] as const,
    rules: (params: unknown) => ["alert-rules", params] as const,
  },
  notifications: {
    all: ["notifications"] as const,
    list: (params: unknown) => ["notifications", "list", params] as const,
  },
  inventory: {
    all: ["inventory"] as const,
    list: (params: unknown) => ["inventory", "list", params] as const,
    detail: (mac: string) => ["inventory", "detail", mac] as const,
  },
  ha: {
    all: ["ha"] as const,
    list: (params: unknown) => ["ha", "list", params] as const,
    detail: (id: string) => ["ha", "detail", id] as const,
  },
  users: {
    all: ["users"] as const,
    list: (params: unknown) => ["users", "list", params] as const,
    detail: (id: string) => ["users", "detail", id] as const,
  },
  roles: {
    all: ["roles"] as const,
    list: ["roles", "list"] as const,
    matrix: ["roles", "matrix"] as const,
    permissions: ["permissions"] as const,
  },
  apiKeys: {
    all: ["api-keys"] as const,
    list: ["api-keys", "list"] as const,
  },
  audit: {
    all: ["audit"] as const,
    list: (params: unknown) => ["audit", "list", params] as const,
    integrity: ["audit", "integrity"] as const,
    actions: ["audit", "actions"] as const,
  },
  compliance: {
    all: ["compliance"] as const,
    summary: ["compliance", "summary"] as const,
    reports: (params: unknown) => ["compliance", "reports", params] as const,
    report: (id: string) => ["compliance", "report", id] as const,
    frameworks: ["compliance", "frameworks"] as const,
  },
  tenants: {
    all: ["tenants"] as const,
    list: (params: unknown) => ["tenants", "list", params] as const,
    current: ["tenants", "current"] as const,
    stats: (id: string) => ["tenants", id, "stats"] as const,
  },
  maintenance: {
    all: ["maintenance-windows"] as const,
    list: ["maintenance-windows", "list"] as const,
    active: ["maintenance-windows", "active"] as const,
  },
  reports: {
    all: ["reports"] as const,
    list: ["reports", "list"] as const,
    detail: (id: string) => ["reports", "detail", id] as const,
  },
  version: ["version"] as const,
};
