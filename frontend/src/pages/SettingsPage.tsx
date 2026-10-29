import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Divider,
  FormControlLabel,
  Grid,
  IconButton,
  MenuItem,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
  alpha,
  useTheme,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import BusinessOutlinedIcon from "@mui/icons-material/BusinessOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import FingerprintOutlinedIcon from "@mui/icons-material/FingerprintOutlined";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import RefreshIcon from "@mui/icons-material/Refresh";
import SecurityOutlinedIcon from "@mui/icons-material/SecurityOutlined";
import VerifiedUserOutlinedIcon from "@mui/icons-material/VerifiedUserOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { alertsApi, authApi, healthApi, tenantsApi, usersApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { AlertRule, MfaSetup, SessionInfo, Tenant } from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import DetailGrid from "@/components/DetailGrid";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import SeverityChip from "@/components/SeverityChip";
import StatusChip from "@/components/StatusChip";
import { usePermissions } from "@/hooks/usePermissions";
import { bootstrapSession, logout } from "@/store/authSlice";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import {
  ALERT_CHANNELS,
  ALERT_METRICS,
  ALERT_OPERATORS,
  DEFAULT_PAGE_SIZE,
} from "@/utils/constants";
import {
  EMPTY,
  formatBytes,
  formatDateTime,
  fromNow,
  initials,
  prettyJson,
} from "@/utils/format";

type SettingsTab = "profile" | "security" | "sessions" | "alerts" | "platform";

const TAB_LABELS: Array<{ key: SettingsTab; label: string }> = [
  { key: "profile", label: "Profile" },
  { key: "security", label: "Security" },
  { key: "sessions", label: "Sessions" },
  { key: "alerts", label: "Alert rules" },
  { key: "platform", label: "Platform" },
];

const TENANT_PLANS = ["community", "professional", "enterprise", "msp"] as const;
const TENANT_STATUSES = ["active", "trial", "suspended", "cancelled"] as const;
const SEVERITIES = ["info", "warning", "critical"] as const;

interface ProfileForm {
  full_name: string;
  email: string;
}

interface PasswordForm {
  current: string;
  next: string;
  confirm: string;
}

interface RuleForm {
  name: string;
  metric: string;
  operator: string;
  threshold: string;
  duration_seconds: string;
  severity: string;
  enabled: boolean;
  channels: string[];
  device_selector: string;
}

const EMPTY_RULE: RuleForm = {
  name: "",
  metric: "cpu",
  operator: ">",
  threshold: "85",
  duration_seconds: "300",
  severity: "warning",
  enabled: true,
  channels: ["email"],
  device_selector: "{}",
};

interface TenantForm {
  name: string;
  slug: string;
  plan: string;
  status: string;
  device_limit: string;
  contact_email: string;
}

const EMPTY_TENANT: TenantForm = {
  name: "",
  slug: "",
  plan: "enterprise",
  status: "trial",
  device_limit: "100",
  contact_email: "",
};

function scoreColor(status?: string): "success" | "warning" | "error" | "default" {
  if (!status) return "default";
  if (status === "ready" || status === "ok" || status === "healthy") return "success";
  if (status === "degraded") return "warning";
  return "error";
}

export function SettingsPage() {
  const theme = useTheme();
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const { user, can, isSuperadmin } = usePermissions();
  const [searchParams] = useSearchParams();

  const canAlerts = can("alert:read");
  const canWriteAlerts = can("alert:write");
  const canEditProfile = can("user:write");

  const visibleTabs = useMemo(
    () => TAB_LABELS.filter((entry) => entry.key !== "alerts" || canAlerts),
    [canAlerts],
  );

  const requestedTab = searchParams.get("tab") as SettingsTab | null;
  const [tab, setTab] = useState<SettingsTab>(
    requestedTab && TAB_LABELS.some((entry) => entry.key === requestedTab) ? requestedTab : "profile",
  );
  const activeTab = visibleTabs.some((entry) => entry.key === tab) ? tab : "profile";

  useEffect(() => {
    if (requestedTab && TAB_LABELS.some((entry) => entry.key === requestedTab)) {
      setTab(requestedTab);
    }
  }, [requestedTab]);

  const [profileForm, setProfileForm] = useState<ProfileForm>({
    full_name: user?.full_name ?? "",
    email: user?.email ?? "",
  });
  const [profileError, setProfileError] = useState<string | null>(null);

  const [passwordForm, setPasswordForm] = useState<PasswordForm>({
    current: "",
    next: "",
    confirm: "",
  });
  const [passwordError, setPasswordError] = useState<string | null>(null);

  const [mfaSetup, setMfaSetup] = useState<MfaSetup | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const [mfaError, setMfaError] = useState<string | null>(null);
  const [disablePassword, setDisablePassword] = useState("");
  const [disableCode, setDisableCode] = useState("");
  const [disableError, setDisableError] = useState<string | null>(null);

  const [sessionsOpen, setSessionsOpen] = useState(false);

  const [rulePage, setRulePage] = useState(1);
  const [ruleSize, setRuleSize] = useState(DEFAULT_PAGE_SIZE);
  const [ruleDialogOpen, setRuleDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<AlertRule | null>(null);
  const [ruleForm, setRuleForm] = useState<RuleForm>(EMPTY_RULE);
  const [ruleError, setRuleError] = useState<string | null>(null);
  const [deleteRuleTarget, setDeleteRuleTarget] = useState<AlertRule | null>(null);

  const [tenantPage, setTenantPage] = useState(1);
  const [tenantDialogOpen, setTenantDialogOpen] = useState(false);
  const [editingTenant, setEditingTenant] = useState<Tenant | null>(null);
  const [tenantForm, setTenantForm] = useState<TenantForm>(EMPTY_TENANT);
  const [tenantError, setTenantError] = useState<string | null>(null);
  const [selectedTenant, setSelectedTenant] = useState<Tenant | null>(null);

  useEffect(() => {
    if (!user) return;
    setProfileForm({ full_name: user.full_name ?? "", email: user.email });
  }, [user]);

  const versionQuery = useQuery({
    queryKey: qk.version,
    queryFn: () => healthApi.version(),
    staleTime: 60_000,
  });

  const readinessQuery = useQuery({
    queryKey: [...qk.health, "ready"],
    queryFn: () => healthApi.ready(),
    enabled: activeTab === "platform",
    refetchInterval: activeTab === "platform" ? 30_000 : false,
  });

  const sessionsQuery = useQuery({
    queryKey: ["auth", "sessions"],
    queryFn: () => authApi.sessions(),
    enabled: activeTab === "sessions",
  });

  const rulesQuery = useQuery({
    queryKey: qk.alerts.rules({ page: rulePage, size: ruleSize }),
    queryFn: () => alertsApi.rules({ page: rulePage, size: ruleSize }),
    enabled: canAlerts && activeTab === "alerts",
    refetchInterval: activeTab === "alerts" ? 60_000 : false,
  });

  const tenantsQuery = useQuery({
    queryKey: qk.tenants.list({ page: tenantPage, size: 25 }),
    queryFn: () => tenantsApi.list({ page: tenantPage, size: 25 }),
    enabled: isSuperadmin && activeTab === "platform",
  });

  const tenantStatsQuery = useQuery({
    queryKey: qk.tenants.stats(selectedTenant?.id ?? "none"),
    queryFn: () => {
      if (!selectedTenant) throw new Error("No tenant selected");
      return tenantsApi.stats(selectedTenant.id);
    },
    enabled: Boolean(selectedTenant?.id),
  });

  const invalidateRules = () => {
    void queryClient.invalidateQueries({ queryKey: ["alert-rules"] });
    void queryClient.invalidateQueries({ queryKey: qk.alerts.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const refreshIdentity = () => {
    void dispatch(bootstrapSession());
  };

  const profileMutation = useMutation({
    mutationFn: () => {
      if (!user) throw new Error("No authenticated user");
      return usersApi.update(user.id, {
        full_name: profileForm.full_name.trim() || null,
        email: profileForm.email.trim(),
      });
    },
    onSuccess: (updated) => {
      setProfileForm({ full_name: updated.full_name ?? "", email: updated.email });
      setProfileError(null);
      refreshIdentity();
      dispatch(showToast({ message: "Profile updated", severity: "success" }));
    },
    onError: (error) => setProfileError(toApiError(error).message),
  });

  const passwordMutation = useMutation({
    mutationFn: () => authApi.changePassword(passwordForm.current, passwordForm.next),
    onSuccess: async (message) => {
      setPasswordForm({ current: "", next: "", confirm: "" });
      setPasswordError(null);
      dispatch(showToast({ message: message.message, severity: "success" }));
      await dispatch(logout());
    },
    onError: (error) => setPasswordError(toApiError(error).message),
  });

  const mfaSetupMutation = useMutation({
    mutationFn: () => authApi.setupMfa(),
    onSuccess: (setup) => {
      setMfaSetup(setup);
      setMfaCode("");
      setMfaError(null);
    },
    onError: (error) => setMfaError(toApiError(error).message),
  });

  const mfaVerifyMutation = useMutation({
    mutationFn: () => authApi.verifyMfaSetup(mfaCode),
    onSuccess: () => {
      setMfaSetup(null);
      setMfaCode("");
      setMfaError(null);
      refreshIdentity();
      dispatch(showToast({ message: "MFA enabled", severity: "success" }));
    },
    onError: (error) => setMfaError(toApiError(error).message),
  });

  const mfaDisableMutation = useMutation({
    mutationFn: () => authApi.disableMfa(disablePassword, disableCode),
    onSuccess: () => {
      setDisablePassword("");
      setDisableCode("");
      setDisableError(null);
      refreshIdentity();
      dispatch(showToast({ message: "MFA disabled", severity: "success" }));
    },
    onError: (error) => setDisableError(toApiError(error).message),
  });

  const revokeSessionsMutation = useMutation({
    mutationFn: () => authApi.revokeSessions(),
    onSuccess: async (message) => {
      setSessionsOpen(false);
      dispatch(showToast({ message: message.message, severity: "success" }));
      await dispatch(logout());
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const saveRuleMutation = useMutation({
    mutationFn: (payload: Partial<AlertRule>) =>
      editingRule ? alertsApi.updateRule(editingRule.id, payload) : alertsApi.createRule(payload),
    onSuccess: (rule) => {
      invalidateRules();
      setRuleDialogOpen(false);
      setEditingRule(null);
      setRuleForm(EMPTY_RULE);
      setRuleError(null);
      dispatch(showToast({ message: `Alert rule ${rule.name} saved`, severity: "success" }));
    },
    onError: (error) => setRuleError(toApiError(error).message),
  });

  const deleteRuleMutation = useMutation({
    mutationFn: (rule: AlertRule) => alertsApi.removeRule(rule.id),
    onSuccess: () => {
      invalidateRules();
      setDeleteRuleTarget(null);
      dispatch(showToast({ message: "Alert rule deleted", severity: "success" }));
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const testRuleMutation = useMutation({
    mutationFn: (rule: AlertRule) => alertsApi.testRule(rule.id),
    onSuccess: (result, rule) => {
      dispatch(
        showToast({
          message: `Test evaluation queued for ${rule.name}: ${String(
            result.status ?? result.result ?? "accepted",
          )}`,
          severity: "success",
        }),
      );
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const saveTenantMutation = useMutation({
    mutationFn: () => {
      const payload = {
        name: tenantForm.name.trim(),
        plan: tenantForm.plan,
        device_limit: Math.max(1, Number(tenantForm.device_limit) || 1),
        contact_email: tenantForm.contact_email.trim() || null,
      };
      return editingTenant
        ? tenantsApi.update(editingTenant.id, { ...payload, status: tenantForm.status })
        : tenantsApi.create({
            ...payload,
            slug: tenantForm.slug.trim().toLowerCase(),
          });
    },
    onSuccess: (tenant) => {
      void queryClient.invalidateQueries({ queryKey: qk.tenants.all });
      setTenantDialogOpen(false);
      setEditingTenant(null);
      setTenantForm(EMPTY_TENANT);
      setTenantError(null);
      dispatch(showToast({ message: `Tenant ${tenant.name} saved`, severity: "success" }));
    },
    onError: (error) => setTenantError(toApiError(error).message),
  });

  const openRuleCreate = () => {
    setEditingRule(null);
    setRuleForm(EMPTY_RULE);
    setRuleError(null);
    setRuleDialogOpen(true);
  };

  const openRuleEdit = (rule: AlertRule) => {
    setEditingRule(rule);
    setRuleForm({
      name: rule.name,
      metric: rule.metric,
      operator: rule.operator,
      threshold: String(rule.threshold),
      duration_seconds: String(rule.duration_seconds),
      severity: rule.severity,
      enabled: rule.enabled,
      channels: [...rule.channels],
      device_selector: prettyJson(rule.device_selector ?? {}),
    });
    setRuleError(null);
    setRuleDialogOpen(true);
  };

  const submitRule = () => {
    if (!ruleForm.name.trim()) {
      setRuleError("A rule name is required.");
      return;
    }
    let selector: Record<string, unknown>;
    try {
      selector = ruleForm.device_selector.trim()
        ? (JSON.parse(ruleForm.device_selector) as Record<string, unknown>)
        : {};
    } catch {
      setRuleError("The device selector must be valid JSON.");
      return;
    }
    saveRuleMutation.mutate({
      name: ruleForm.name.trim(),
      metric: ruleForm.metric,
      operator: ruleForm.operator,
      threshold: Number(ruleForm.threshold),
      duration_seconds: Number(ruleForm.duration_seconds),
      severity: ruleForm.severity as AlertRule["severity"],
      enabled: ruleForm.enabled,
      channels: ruleForm.channels,
      device_selector: selector,
    });
  };

  const openTenantCreate = () => {
    setEditingTenant(null);
    setTenantForm(EMPTY_TENANT);
    setTenantError(null);
    setTenantDialogOpen(true);
  };

  const openTenantEdit = (tenant: Tenant) => {
    setEditingTenant(tenant);
    setTenantForm({
      name: tenant.name,
      slug: tenant.slug,
      plan: tenant.plan,
      status: tenant.status,
      device_limit: String(tenant.device_limit),
      contact_email: tenant.contact_email ?? "",
    });
    setTenantError(null);
    setTenantDialogOpen(true);
  };

  const submitPassword = () => {
    if (passwordForm.next.length < 12) {
      setPasswordError("The new password must be at least 12 characters.");
      return;
    }
    if (passwordForm.next !== passwordForm.confirm) {
      setPasswordError("The new password and confirmation do not match.");
      return;
    }
    if (passwordForm.next === passwordForm.current) {
      setPasswordError("The new password must differ from the current password.");
      return;
    }
    setPasswordError(null);
    passwordMutation.mutate();
  };

  const toggleRuleChannel = (channel: string, checked: boolean) => {
    setRuleForm((value) => ({
      ...value,
      channels: checked
        ? [...value.channels, channel]
        : value.channels.filter((item) => item !== channel),
    }));
  };

  const sessionColumns: Array<DataTableColumn<SessionInfo>> = [
    {
      key: "ip",
      label: "Client IP",
      width: 160,
      render: (row) => (
        <Typography variant="body2" fontFamily="monospace">
          {row.ip_address ?? EMPTY}
        </Typography>
      ),
    },
    {
      key: "agent",
      label: "User agent",
      render: (row) => (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", maxWidth: 420 }}>
          {row.user_agent ?? "unknown client"}
        </Typography>
      ),
    },
    {
      key: "created",
      label: "Signed in",
      width: 170,
      hideBelow: "md",
      render: (row) => (
        <Tooltip title={formatDateTime(row.created_at)}>
          <span>{fromNow(row.created_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: "expires",
      label: "Expires",
      width: 170,
      hideBelow: "lg",
      render: (row) => formatDateTime(row.expires_at),
    },
    {
      key: "jti",
      label: "Token",
      width: 150,
      hideBelow: "lg",
      monospace: true,
      render: (row) => row.jti.slice(0, 13),
    },
  ];

  const ruleColumns: Array<DataTableColumn<AlertRule>> = [
    {
      key: "name",
      label: "Rule",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.name}
          </Typography>
          <Typography variant="caption" color="text.secondary" fontFamily="monospace">
            {row.metric} {row.operator} {row.threshold} for {row.duration_seconds}s
          </Typography>
        </Box>
      ),
    },
    {
      key: "severity",
      label: "Severity",
      width: 120,
      render: (row) => <SeverityChip severity={row.severity} />,
    },
    {
      key: "state",
      label: "State",
      width: 110,
      render: (row) => <StatusChip status={row.enabled ? "enabled" : "disabled"} />,
    },
    {
      key: "channels",
      label: "Channels",
      hideBelow: "md",
      render: (row) => (
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          {row.channels.length > 0 ? (
            row.channels.map((channel) => (
              <Chip key={channel} size="small" variant="outlined" label={channel} />
            ))
          ) : (
            <Typography variant="caption" color="text.disabled">
              none
            </Typography>
          )}
        </Stack>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 150,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <Tooltip title="Send a test evaluation">
            <span>
              <IconButton
                size="small"
                onClick={() => testRuleMutation.mutate(row)}
                disabled={testRuleMutation.isPending}
              >
                <VerifiedUserOutlinedIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          {canWriteAlerts && (
            <>
              <Tooltip title="Edit rule">
                <IconButton size="small" onClick={() => openRuleEdit(row)}>
                  <EditOutlinedIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Tooltip title="Delete rule">
                <IconButton
                  size="small"
                  color="error"
                  onClick={() => setDeleteRuleTarget(row)}
                >
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </>
          )}
        </Stack>
      ),
    },
  ];

  const tenantColumns: Array<DataTableColumn<Tenant>> = [
    {
      key: "name",
      label: "Tenant",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.name}
          </Typography>
          <Typography variant="caption" color="text.secondary" fontFamily="monospace">
            {row.slug} · {row.id.slice(0, 8)}
          </Typography>
        </Box>
      ),
    },
    {
      key: "status",
      label: "Status",
      width: 120,
      render: (row) => <StatusChip status={row.status} />,
    },
    {
      key: "plan",
      label: "Plan",
      width: 130,
      hideBelow: "sm",
      render: (row) => <Chip size="small" variant="outlined" label={row.plan} />,
    },
    {
      key: "devices",
      label: "Devices",
      width: 130,
      align: "right",
      render: (row) => `${row.device_count} / ${row.device_limit}`,
    },
    {
      key: "contact",
      label: "Contact",
      hideBelow: "lg",
      render: (row) => row.contact_email ?? "—",
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 120,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <Tooltip title="Tenant statistics">
            <IconButton size="small" onClick={() => setSelectedTenant(row)}>
              <BusinessOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Edit tenant">
            <IconButton size="small" onClick={() => openTenantEdit(row)}>
              <EditOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      ),
    },
  ];

  const version = versionQuery.data;
  const readiness = readinessQuery.data;
  const rules = rulesQuery.data?.items ?? [];
  const sessions = sessionsQuery.data ?? [];

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Your identity, credentials, sessions, alerting thresholds and platform-wide tenant administration."
        actions={
          <Button
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={() => {
              void readinessQuery.refetch();
              void versionQuery.refetch();
              if (activeTab === "sessions") void sessionsQuery.refetch();
              if (activeTab === "alerts") void rulesQuery.refetch();
              if (activeTab === "platform" && isSuperadmin) void tenantsQuery.refetch();
            }}
          >
            Refresh
          </Button>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={user?.username ?? "anonymous"} />
            <Chip size="small" variant="outlined" label={user?.auth_provider ?? "local"} />
            <Chip
              size="small"
              variant="outlined"
              color={user?.mfa_enabled ? "success" : "warning"}
              label={user?.mfa_enabled ? "MFA enabled" : "MFA disabled"}
            />
            {isSuperadmin && <Chip size="small" color="secondary" variant="outlined" label="SuperAdmin" />}
          </Stack>
        }
      />

      <Tabs
        value={activeTab}
        onChange={(_event, value: SettingsTab) => setTab(value)}
        variant="scrollable"
        allowScrollButtonsMobile
        sx={{ mb: 2 }}
      >
        {visibleTabs.map((entry) => (
          <Tab key={entry.key} value={entry.key} label={entry.label} />
        ))}
      </Tabs>

      {activeTab === "profile" && (
        <Grid container spacing={2}>
          <Grid item xs={12} lg={4}>
            <Card sx={{ height: "100%" }}>
              <CardContent>
                <Stack direction="row" spacing={2} alignItems="center">
                  <Avatar
                    sx={{
                      width: 58,
                      height: 58,
                      fontSize: 20,
                      fontWeight: 700,
                      bgcolor: alpha(theme.palette.primary.main, 0.16),
                      color: "primary.main",
                    }}
                  >
                    {initials(user?.full_name ?? user?.username)}
                  </Avatar>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="h5" noWrap>
                      {user?.full_name ?? user?.username ?? "Unknown user"}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" noWrap>
                      {user?.email ?? EMPTY}
                    </Typography>
                  </Box>
                </Stack>
                <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 2 }}>
                  {(user?.roles ?? []).map((role) => (
                    <Chip key={role} size="small" variant="outlined" label={role} />
                  ))}
                </Stack>
                <Divider sx={{ my: 2 }} />
                <DetailGrid
                  columns={1}
                  dense
                  items={[
                    { label: "Username", value: user?.username ?? EMPTY },
                    { label: "Tenant", value: user?.tenant_id ?? "platform" },
                    { label: "Authentication", value: user?.auth_provider ?? EMPTY },
                    { label: "MFA", value: user?.mfa_enabled ? "TOTP enrolled" : "not enrolled" },
                    {
                      label: "Last login",
                      value: user?.last_login_at ? formatDateTime(user.last_login_at) : "never",
                    },
                    { label: "Permissions", value: `${user?.permissions.length ?? 0} granted` },
                  ]}
                />
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} lg={8}>
            <Card>
              <CardContent>
                <Typography variant="h5" sx={{ mb: 0.5 }}>
                  Profile details
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Display name and email address are visible to other administrators and in audit exports.
                </Typography>
                {!canEditProfile && (
                  <Alert severity="info" sx={{ mb: 2 }}>
                    Editing profile details requires user:write. Contact a tenant administrator to change your
                    email address.
                  </Alert>
                )}
                {profileError && (
                  <Alert severity="error" sx={{ mb: 2 }}>
                    {profileError}
                  </Alert>
                )}
                <Stack spacing={2} sx={{ maxWidth: 520 }}>
                  <TextField
                    label="Display name"
                    value={profileForm.full_name}
                    onChange={(event) =>
                      setProfileForm((value) => ({ ...value, full_name: event.target.value }))
                    }
                    disabled={!canEditProfile}
                  />
                  <TextField
                    label="Email address"
                    type="email"
                    value={profileForm.email}
                    onChange={(event) =>
                      setProfileForm((value) => ({ ...value, email: event.target.value }))
                    }
                    disabled={!canEditProfile}
                    required
                  />
                  <Stack direction="row" spacing={1}>
                    <Button
                      variant="contained"
                      onClick={() => profileMutation.mutate()}
                      disabled={
                        !canEditProfile ||
                        profileMutation.isPending ||
                        !profileForm.email.trim() ||
                        (profileForm.full_name === (user?.full_name ?? "") &&
                          profileForm.email === (user?.email ?? ""))
                      }
                    >
                      Save profile
                    </Button>
                    <Button
                      color="inherit"
                      disabled={!canEditProfile}
                      onClick={() =>
                        setProfileForm({
                          full_name: user?.full_name ?? "",
                          email: user?.email ?? "",
                        })
                      }
                    >
                      Reset
                    </Button>
                  </Stack>
                </Stack>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {activeTab === "security" && (
        <Grid container spacing={2}>
          <Grid item xs={12} lg={6}>
            <Card sx={{ height: "100%" }}>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                  <LockOutlinedIcon fontSize="small" color="action" />
                  <Typography variant="h5">Password</Typography>
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Changing your password revokes every refresh token. You will be asked to sign in again.
                </Typography>
                {passwordError && (
                  <Alert severity="error" sx={{ mb: 2 }}>
                    {passwordError}
                  </Alert>
                )}
                <Stack spacing={2}>
                  <TextField
                    label="Current password"
                    type="password"
                    value={passwordForm.current}
                    onChange={(event) =>
                      setPasswordForm((value) => ({ ...value, current: event.target.value }))
                    }
                  />
                  <TextField
                    label="New password"
                    type="password"
                    value={passwordForm.next}
                    onChange={(event) =>
                      setPasswordForm((value) => ({ ...value, next: event.target.value }))
                    }
                    helperText={`${passwordForm.next.length} of 12 minimum characters`}
                  />
                  <TextField
                    label="Confirm new password"
                    type="password"
                    value={passwordForm.confirm}
                    onChange={(event) =>
                      setPasswordForm((value) => ({ ...value, confirm: event.target.value }))
                    }
                  />
                  <Button
                    variant="contained"
                    onClick={submitPassword}
                    disabled={
                      passwordMutation.isPending ||
                      !passwordForm.current ||
                      passwordForm.next.length < 12
                    }
                    sx={{ alignSelf: "flex-start" }}
                  >
                    Update password
                  </Button>
                </Stack>
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} lg={6}>
            <Card sx={{ height: "100%" }}>
              <CardContent>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                  <FingerprintOutlinedIcon fontSize="small" color="action" />
                  <Typography variant="h5">Multi-factor authentication</Typography>
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  TOTP is supported by every authenticator app. Backup codes are shown once at enrolment and
                  can each be used a single time.
                </Typography>

                {user?.mfa_enabled ? (
                  <>
                    <Alert severity="success" sx={{ mb: 2 }}>
                      TOTP is active for this account. Sign-in requires a six-digit code after the password
                      step.
                    </Alert>
                    {disableError && (
                      <Alert severity="error" sx={{ mb: 2 }}>
                        {disableError}
                      </Alert>
                    )}
                    <Stack spacing={2}>
                      <TextField
                        label="Password"
                        type="password"
                        value={disablePassword}
                        onChange={(event) => setDisablePassword(event.target.value)}
                      />
                      <TextField
                        label="Current TOTP code"
                        value={disableCode}
                        onChange={(event) => setDisableCode(event.target.value)}
                        inputProps={{ inputMode: "numeric", maxLength: 12 }}
                        helperText="Disabling MFA weakens the account; the action is audited."
                      />
                      <Button
                        color="error"
                        variant="outlined"
                        onClick={() => mfaDisableMutation.mutate()}
                        disabled={
                          mfaDisableMutation.isPending || !disablePassword || disableCode.length < 6
                        }
                        sx={{ alignSelf: "flex-start" }}
                      >
                        Disable MFA
                      </Button>
                    </Stack>
                  </>
                ) : mfaSetup ? (
                  <>
                    <Alert severity="info" sx={{ mb: 2 }}>
                      Scan the provisioning URI or enter the secret manually. Confirm with a generated code to
                      finish enrolment.
                    </Alert>
                    {mfaError && (
                      <Alert severity="error" sx={{ mb: 2 }}>
                        {mfaError}
                      </Alert>
                    )}
                    <Stack spacing={2}>
                      <CodeBlock code={mfaSetup.secret} title="TOTP secret" maxHeight={80} />
                      <CodeBlock
                        code={mfaSetup.provisioning_uri}
                        title="Provisioning URI"
                        maxHeight={120}
                      />
                      <CodeBlock
                        code={mfaSetup.backup_codes.join("\n")}
                        title="Backup codes (store offline)"
                        maxHeight={160}
                      />
                      <TextField
                        label="Verification code"
                        value={mfaCode}
                        onChange={(event) => setMfaCode(event.target.value)}
                        inputProps={{ inputMode: "numeric", maxLength: 12 }}
                        autoFocus
                      />
                      <Stack direction="row" spacing={1}>
                        <Button
                          variant="contained"
                          onClick={() => mfaVerifyMutation.mutate()}
                          disabled={mfaVerifyMutation.isPending || mfaCode.length < 6}
                        >
                          Verify and enable
                        </Button>
                        <Button
                          color="inherit"
                          onClick={() => {
                            setMfaSetup(null);
                            setMfaCode("");
                            setMfaError(null);
                          }}
                        >
                          Cancel
                        </Button>
                      </Stack>
                    </Stack>
                  </>
                ) : (
                  <>
                    {mfaError && (
                      <Alert severity="error" sx={{ mb: 2 }}>
                        {mfaError}
                      </Alert>
                    )}
                    <Button
                      variant="contained"
                      startIcon={<SecurityOutlinedIcon />}
                      onClick={() => mfaSetupMutation.mutate()}
                      disabled={mfaSetupMutation.isPending}
                    >
                      Start enrolment
                    </Button>
                  </>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {activeTab === "sessions" && (
        <DataTable
          columns={sessionColumns}
          rows={sessions}
          getRowId={(row) => row.id}
          loading={sessionsQuery.isLoading}
          error={sessionsQuery.error ? toApiError(sessionsQuery.error).message : null}
          onRetry={() => sessionsQuery.refetch()}
          dense
          emptyTitle="No active sessions"
          emptyDescription="Refresh tokens appear here after sign-in. Expired or revoked tokens are removed automatically."
          toolbar={
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={1}
              alignItems={{ xs: "stretch", sm: "center" }}
              justifyContent="space-between"
            >
              <Typography variant="caption" color="text.secondary">
                {sessions.length} active refresh session{sessions.length === 1 ? "" : "s"} · revoking all
                signs this browser out too
              </Typography>
              <Button
                variant="outlined"
                color="error"
                onClick={() => setSessionsOpen(true)}
                disabled={sessions.length === 0 || revokeSessionsMutation.isPending}
              >
                Revoke all sessions
              </Button>
            </Stack>
          }
        />
      )}

      {activeTab === "alerts" && canAlerts && (
        <>
          <Stack direction="row" justifyContent="flex-end" sx={{ mb: 2 }}>
            {canWriteAlerts && (
              <Button variant="contained" startIcon={<AddIcon />} onClick={openRuleCreate}>
                New alert rule
              </Button>
            )}
          </Stack>
          <DataTable
            columns={ruleColumns}
            rows={rules}
            getRowId={(row) => row.id}
            loading={rulesQuery.isLoading}
            error={rulesQuery.error ? toApiError(rulesQuery.error).message : null}
            onRetry={() => rulesQuery.refetch()}
            page={rulePage}
            size={ruleSize}
            total={rulesQuery.data?.meta.total}
            onPageChange={setRulePage}
            onSizeChange={setRuleSize}
            emptyTitle="No alert rules"
            emptyDescription="Thresholds evaluate telemetry snapshots and open alerts when a condition persists for the configured duration."
            emptyAction={
              canWriteAlerts ? (
                <Button variant="contained" startIcon={<AddIcon />} onClick={openRuleCreate}>
                  New alert rule
                </Button>
              ) : undefined
            }
            toolbar={
              <Stack
                direction={{ xs: "column", md: "row" }}
                spacing={1}
                justifyContent="space-between"
                alignItems={{ xs: "stretch", md: "center" }}
              >
                <Typography variant="body2" color="text.secondary">
                  Rules are tenant-scoped. Channels are delivered by the notification service; a failing
                  channel never blocks alert creation.
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {rulesQuery.data?.meta.total ?? 0} rules
                </Typography>
              </Stack>
            }
          />
        </>
      )}

      {activeTab === "platform" && (
        <Stack spacing={2}>
          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <Card sx={{ height: "100%" }}>
                <CardContent>
                  <Typography variant="h5" sx={{ mb: 0.5 }}>
                    Build information
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    Running control-plane build and API contract versions.
                  </Typography>
                  {versionQuery.isError ? (
                    <Alert severity="error">{toApiError(versionQuery.error).message}</Alert>
                  ) : (
                    <DetailGrid
                      columns={2}
                      dense
                      items={[
                        { label: "Product", value: version?.name ?? EMPTY },
                        { label: "Version", value: version?.version ?? EMPTY },
                        { label: "API version", value: version?.api_version ?? EMPTY },
                        { label: "Python", value: version?.python ?? EMPTY },
                        { label: "Environment", value: version?.environment ?? EMPTY },
                        {
                          label: "Server time",
                          value: version ? formatDateTime(version.server_time) : EMPTY,
                        },
                      ]}
                    />
                  )}
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={6}>
              <Card sx={{ height: "100%" }}>
                <CardContent>
                  <Stack
                    direction="row"
                    spacing={1}
                    alignItems="center"
                    justifyContent="space-between"
                    sx={{ mb: 0.5 }}
                  >
                    <Typography variant="h5">Dependency health</Typography>
                    <Chip
                      size="small"
                      variant="outlined"
                      color={scoreColor(readiness?.status)}
                      label={readiness?.status ?? "unknown"}
                    />
                  </Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    Live checks for PostgreSQL, Redis, broker and object storage.
                  </Typography>
                  {readinessQuery.isError ? (
                    <Alert severity="error">{toApiError(readinessQuery.error).message}</Alert>
                  ) : (
                    <Stack spacing={1}>
                      {Object.entries(readiness?.components ?? {}).map(([name, health]) => (
                        <Stack
                          key={name}
                          direction="row"
                          spacing={1}
                          alignItems="center"
                          justifyContent="space-between"
                          sx={{
                            px: 1.25,
                            py: 0.75,
                            border: 1,
                            borderColor: "divider",
                            borderRadius: 1.5,
                          }}
                        >
                          <Stack direction="row" spacing={1} alignItems="center">
                            <Box
                              sx={{
                                width: 8,
                                height: 8,
                                borderRadius: "50%",
                                bgcolor:
                                  scoreColor(health.status) === "success"
                                    ? "success.main"
                                    : scoreColor(health.status) === "warning"
                                      ? "warning.main"
                                      : "error.main",
                              }}
                            />
                            <Typography variant="body2" fontFamily="monospace">
                              {name}
                            </Typography>
                          </Stack>
                          <Stack direction="row" spacing={1} alignItems="center">
                            {health.latency_ms !== null && (
                              <Typography variant="caption" color="text.secondary">
                                {health.latency_ms.toFixed(1)} ms
                              </Typography>
                            )}
                            <Chip
                              size="small"
                              variant="outlined"
                              color={scoreColor(health.status)}
                              label={health.status}
                            />
                          </Stack>
                        </Stack>
                      ))}
                    </Stack>
                  )}
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          <Card>
            <CardContent>
              <Stack
                direction={{ xs: "column", sm: "row" }}
                spacing={1}
                justifyContent="space-between"
                alignItems={{ xs: "flex-start", sm: "center" }}
                sx={{ mb: 2 }}
              >
                <Box>
                  <Typography variant="h5">Tenant administration</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Platform-wide tenant lifecycle, plans and device quotas. Only SuperAdmins can read or
                    modify this section.
                  </Typography>
                </Box>
                {isSuperadmin && (
                  <Button variant="contained" startIcon={<AddIcon />} onClick={openTenantCreate}>
                    New tenant
                  </Button>
                )}
              </Stack>

              {!isSuperadmin ? (
                <Alert severity="info">
                  Your account is scoped to a single tenant. Tenant lifecycle management is restricted to
                  platform SuperAdmins.
                </Alert>
              ) : (
                <DataTable
                  columns={tenantColumns}
                  rows={tenantsQuery.data?.items ?? []}
                  getRowId={(row) => row.id}
                  loading={tenantsQuery.isLoading}
                  error={tenantsQuery.error ? toApiError(tenantsQuery.error).message : null}
                  onRetry={() => tenantsQuery.refetch()}
                  page={tenantPage}
                  size={25}
                  total={tenantsQuery.data?.meta.total}
                  onPageChange={setTenantPage}
                  emptyTitle="No tenants"
                  emptyDescription="Create the first tenant to isolate devices, policies and audit records."
                  emptyAction={
                    <Button variant="contained" startIcon={<AddIcon />} onClick={openTenantCreate}>
                      New tenant
                    </Button>
                  }
                />
              )}
            </CardContent>
          </Card>
        </Stack>
      )}

      <FormDialog
        open={ruleDialogOpen}
        title={editingRule ? `Edit ${editingRule.name}` : "New alert rule"}
        description={
          <Typography variant="body2" color="text.secondary">
            A rule fires when the metric crosses the threshold for at least the configured duration. Device
            selectors narrow evaluation to a subset of the tenant fleet.
          </Typography>
        }
        submitLabel={editingRule ? "Save rule" : "Create rule"}
        loading={saveRuleMutation.isPending}
        error={ruleError}
        submitDisabled={!ruleForm.name.trim()}
        onSubmit={submitRule}
        onClose={() => setRuleDialogOpen(false)}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "center" }}>
          <TextField
            label="Rule name"
            value={ruleForm.name}
            onChange={(event) => setRuleForm((value) => ({ ...value, name: event.target.value }))}
            required
            autoFocus
            fullWidth
          />
          <FormControlLabel
            control={
              <Switch
                checked={ruleForm.enabled}
                onChange={(event) =>
                  setRuleForm((value) => ({ ...value, enabled: event.target.checked }))
                }
              />
            }
            label="Enabled"
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Metric"
            value={ruleForm.metric}
            onChange={(event) => setRuleForm((value) => ({ ...value, metric: event.target.value }))}
            fullWidth
          >
            {ALERT_METRICS.map((metric) => (
              <MenuItem key={metric} value={metric}>
                {metric}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Operator"
            value={ruleForm.operator}
            onChange={(event) =>
              setRuleForm((value) => ({ ...value, operator: event.target.value }))
            }
            sx={{ minWidth: 120 }}
          >
            {ALERT_OPERATORS.map((operator) => (
              <MenuItem key={operator} value={operator}>
                {operator}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Threshold"
            type="number"
            value={ruleForm.threshold}
            onChange={(event) =>
              setRuleForm((value) => ({ ...value, threshold: event.target.value }))
            }
            sx={{ minWidth: 140 }}
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Duration (seconds)"
            type="number"
            value={ruleForm.duration_seconds}
            onChange={(event) =>
              setRuleForm((value) => ({ ...value, duration_seconds: event.target.value }))
            }
            inputProps={{ min: 0, max: 86_400 }}
            helperText="Condition must hold for this long before an alert opens"
          />
          <TextField
            select
            label="Severity"
            value={ruleForm.severity}
            onChange={(event) =>
              setRuleForm((value) => ({ ...value, severity: event.target.value }))
            }
          >
            {SEVERITIES.map((severity) => (
              <MenuItem key={severity} value={severity}>
                {severity}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Box>
          <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
            Notification channels
          </Typography>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
            {ALERT_CHANNELS.map((channel) => (
              <FormControlLabel
                key={channel}
                control={
                  <Checkbox
                    size="small"
                    checked={ruleForm.channels.includes(channel)}
                    onChange={(event) => toggleRuleChannel(channel, event.target.checked)}
                  />
                }
                label={channel}
              />
            ))}
          </Stack>
        </Box>
        <TextField
          label="Device selector (JSON)"
          value={ruleForm.device_selector}
          onChange={(event) =>
            setRuleForm((value) => ({ ...value, device_selector: event.target.value }))
          }
          multiline
          minRows={4}
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 12.5 },
          }}
          helperText='Examples: {} for the whole tenant, {"site_id": "…"} or {"device_ids": ["…"]}'
        />
      </FormDialog>

      <FormDialog
        open={tenantDialogOpen}
        title={editingTenant ? `Edit ${editingTenant.name}` : "Create tenant"}
        description={
          <Typography variant="body2" color="text.secondary">
            Tenants are hard isolation boundaries: devices, policies, backups and audit records never cross
            them.
          </Typography>
        }
        submitLabel={editingTenant ? "Save tenant" : "Create tenant"}
        loading={saveTenantMutation.isPending}
        error={tenantError}
        submitDisabled={
          !tenantForm.name.trim() || (!editingTenant && !tenantForm.slug.trim())
        }
        onSubmit={() => saveTenantMutation.mutate()}
        onClose={() => setTenantDialogOpen(false)}
        maxWidth="sm"
      >
        <TextField
          label="Tenant name"
          value={tenantForm.name}
          onChange={(event) => setTenantForm((value) => ({ ...value, name: event.target.value }))}
          required
          autoFocus
        />
        <TextField
          label="Slug"
          value={tenantForm.slug}
          onChange={(event) => setTenantForm((value) => ({ ...value, slug: event.target.value }))}
          disabled={Boolean(editingTenant)}
          required={!editingTenant}
          helperText={
            editingTenant ? "Slugs are immutable" : "Lowercase identifier used in URLs and JWT claims"
          }
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Plan"
            value={tenantForm.plan}
            onChange={(event) => setTenantForm((value) => ({ ...value, plan: event.target.value }))}
          >
            {TENANT_PLANS.map((plan) => (
              <MenuItem key={plan} value={plan}>
                {plan}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Status"
            value={tenantForm.status}
            onChange={(event) => setTenantForm((value) => ({ ...value, status: event.target.value }))}
            disabled={!editingTenant}
            helperText={editingTenant ? undefined : "New tenants start in the active state"}
          >
            {TENANT_STATUSES.map((status) => (
              <MenuItem key={status} value={status}>
                {status}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Device limit"
            type="number"
            value={tenantForm.device_limit}
            onChange={(event) =>
              setTenantForm((value) => ({ ...value, device_limit: event.target.value }))
            }
            inputProps={{ min: 1 }}
          />
          <TextField
            label="Contact email"
            type="email"
            value={tenantForm.contact_email}
            onChange={(event) =>
              setTenantForm((value) => ({ ...value, contact_email: event.target.value }))
            }
          />
        </Stack>
      </FormDialog>

      <FormDialog
        open={Boolean(selectedTenant)}
        title={selectedTenant ? selectedTenant.name : "Tenant"}
        description={
          selectedTenant ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <StatusChip status={selectedTenant.status} />
              <Chip size="small" variant="outlined" label={selectedTenant.plan} />
              <Chip size="small" variant="outlined" label={selectedTenant.slug} />
              <Chip
                size="small"
                variant="outlined"
                label={`${selectedTenant.device_count} / ${selectedTenant.device_limit} devices`}
              />
            </Stack>
          ) : undefined
        }
        submitLabel="Close"
        onSubmit={() => setSelectedTenant(null)}
        onClose={() => setSelectedTenant(null)}
        maxWidth="md"
      >
        {tenantStatsQuery.isError ? (
          <Alert severity="error">{toApiError(tenantStatsQuery.error).message}</Alert>
        ) : tenantStatsQuery.data ? (
          <DetailGrid
            items={[
              { label: "Devices total", value: tenantStatsQuery.data.devices_total },
              { label: "Online", value: tenantStatsQuery.data.devices_online },
              { label: "Offline", value: tenantStatsQuery.data.devices_offline },
              { label: "Active alerts", value: tenantStatsQuery.data.active_alerts },
              { label: "Users", value: tenantStatsQuery.data.users },
              { label: "Backup storage", value: formatBytes(tenantStatsQuery.data.storage_bytes) },
            ]}
          />
        ) : (
          <Typography variant="body2" color="text.secondary">
            Loading tenant statistics…
          </Typography>
        )}
        {selectedTenant && (
          <DetailGrid
            columns={2}
            dense
            items={[
              { label: "Tenant ID", value: selectedTenant.id },
              { label: "Contact", value: selectedTenant.contact_email ?? "—" },
              { label: "Created", value: formatDateTime(selectedTenant.created_at) },
              { label: "Updated", value: formatDateTime(selectedTenant.updated_at) },
            ]}
          />
        )}
      </FormDialog>

      <ConfirmDialog
        open={sessionsOpen}
        title="Revoke all sessions"
        description="Every refresh token for your account is revoked immediately, including this browser. You will be signed out and must authenticate again."
        confirmLabel="Revoke and sign out"
        confirmColor="error"
        loading={revokeSessionsMutation.isPending}
        onConfirm={() => revokeSessionsMutation.mutate()}
        onClose={() => setSessionsOpen(false)}
      />

      <ConfirmDialog
        open={Boolean(deleteRuleTarget)}
        title="Delete alert rule"
        description={
          deleteRuleTarget
            ? `Delete ${deleteRuleTarget.name}? Alerts already open stay open; only future evaluations stop.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteRuleMutation.isPending}
        onConfirm={() => deleteRuleTarget && deleteRuleMutation.mutate(deleteRuleTarget)}
        onClose={() => setDeleteRuleTarget(null)}
      />
    </>
  );
}

export default SettingsPage;
