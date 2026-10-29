import { useEffect, useMemo, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Autocomplete,
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  FormControlLabel,
  Grid,
  IconButton,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
  alpha,
  useTheme,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import ExpandMoreOutlinedIcon from "@mui/icons-material/ExpandMoreOutlined";
import KeyOutlinedIcon from "@mui/icons-material/KeyOutlined";
import LockOpenOutlinedIcon from "@mui/icons-material/LockOpenOutlined";
import LockResetOutlinedIcon from "@mui/icons-material/LockResetOutlined";
import PeopleOutlinedIcon from "@mui/icons-material/PeopleOutlined";
import RefreshIcon from "@mui/icons-material/Refresh";
import SearchIcon from "@mui/icons-material/Search";
import SecurityOutlinedIcon from "@mui/icons-material/SecurityOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiKeysApi, rolesApi, usersApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type {
  ApiKey,
  ApiKeyCreated,
  Permission,
  Role,
  User,
  UserPayload,
  UserUpdatePayload,
} from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import EmptyState from "@/components/EmptyState";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useDebounce } from "@/hooks/useDebounce";
import { usePermissions } from "@/hooks/usePermissions";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { formatDateTime, fromNow } from "@/utils/format";

type AdminTab = "users" | "roles" | "api-keys";

const USER_STATUSES = ["active", "inactive", "locked", "pending"] as const;

const AUTH_PROVIDERS = [
  { value: "local", label: "Local password" },
  { value: "ldap", label: "LDAP" },
  { value: "ad", label: "Active Directory" },
  { value: "oidc", label: "OIDC" },
  { value: "entra_id", label: "Microsoft Entra ID" },
  { value: "saml", label: "SAML" },
] as const;

interface CreateUserForm {
  username: string;
  email: string;
  full_name: string;
  password: string;
  auth_provider: string;
  role_ids: string[];
  is_superadmin: boolean;
}

const EMPTY_CREATE_USER: CreateUserForm = {
  username: "",
  email: "",
  full_name: "",
  password: "",
  auth_provider: "local",
  role_ids: [],
  is_superadmin: false,
};

interface EditUserForm {
  email: string;
  full_name: string;
  status: string;
  role_ids: string[];
}

interface RoleForm {
  name: string;
  description: string;
  permissions: string[];
}

const EMPTY_ROLE: RoleForm = { name: "", description: "", permissions: [] };

interface ApiKeyForm {
  name: string;
  scopes: string;
  expires_in_days: string;
}

const EMPTY_API_KEY: ApiKeyForm = { name: "", scopes: "", expires_in_days: "365" };

function initials(value: string): string {
  const parts = value.trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}

function apiKeyState(key: ApiKey): { label: string; color: "success" | "default" | "warning" } {
  if (key.revoked_at) return { label: "revoked", color: "default" };
  if (key.expires_at && new Date(key.expires_at).getTime() < Date.now()) {
    return { label: "expired", color: "warning" };
  }
  return { label: "active", color: "success" };
}

interface PermissionPickerProps {
  permissions: Permission[];
  value: string[];
  onChange: (next: string[]) => void;
}

function PermissionPicker({ permissions, value, onChange }: PermissionPickerProps) {
  const groups = useMemo(() => {
    const map = new Map<string, Permission[]>();
    for (const permission of permissions) {
      const category = permission.category ?? "general";
      const bucket = map.get(category);
      if (bucket) {
        bucket.push(permission);
      } else {
        map.set(category, [permission]);
      }
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [permissions]);

  const toggle = (code: string, checked: boolean) => {
    onChange(checked ? [...value, code] : value.filter((item) => item !== code));
  };

  if (permissions.length === 0) {
    return (
      <Alert severity="info">
        The permission catalogue is unavailable to your account. Ask an administrator to grant role:read.
      </Alert>
    );
  }

  return (
    <Box
      sx={{
        maxHeight: 340,
        overflowY: "auto",
        border: 1,
        borderColor: "divider",
        borderRadius: 1.5,
        p: 1.5,
      }}
    >
      {groups.map(([category, items]) => (
        <Box key={category} sx={{ mb: 1.5, "&:last-of-type": { mb: 0 } }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
            <Typography variant="overline" color="text.secondary">
              {category.replace(/_/g, " ")}
            </Typography>
            <Chip size="small" variant="outlined" label={items.length} />
          </Stack>
          <Grid container spacing={0}>
            {items.map((permission) => (
              <Grid item xs={12} sm={6} key={permission.code}>
                <FormControlLabel
                  sx={{ alignItems: "flex-start", m: 0, pr: 1 }}
                  control={
                    <Checkbox
                      size="small"
                      checked={value.includes(permission.code)}
                      onChange={(event) => toggle(permission.code, event.target.checked)}
                    />
                  }
                  label={
                    <Box sx={{ py: 0.5 }}>
                      <Typography variant="body2" fontFamily="monospace" fontSize={12}>
                        {permission.code}
                      </Typography>
                      {permission.description && (
                        <Typography variant="caption" color="text.secondary">
                          {permission.description}
                        </Typography>
                      )}
                    </Box>
                  }
                />
              </Grid>
            ))}
          </Grid>
        </Box>
      ))}
    </Box>
  );
}

export function UsersPage() {
  const theme = useTheme();
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const { can, isSuperadmin } = usePermissions();

  const canUsers = can("user:read");
  const canRoles = can("role:read");
  const canKeys = can("apikey:read");

  const availableTabs = useMemo(() => {
    const tabs: Array<{ key: AdminTab; label: string }> = [];
    if (canUsers) tabs.push({ key: "users", label: "Users" });
    if (canRoles) tabs.push({ key: "roles", label: "Roles & permissions" });
    if (canKeys) tabs.push({ key: "api-keys", label: "API keys" });
    return tabs;
  }, [canUsers, canRoles, canKeys]);

  const [tab, setTab] = useState(0);
  const activeTab = availableTabs[Math.min(tab, Math.max(availableTabs.length - 1, 0))]?.key;

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search, 350);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);

  const [createUserOpen, setCreateUserOpen] = useState(false);
  const [createUserForm, setCreateUserForm] = useState<CreateUserForm>(EMPTY_CREATE_USER);
  const [createUserError, setCreateUserError] = useState<string | null>(null);

  const [editUser, setEditUser] = useState<User | null>(null);
  const [editUserForm, setEditUserForm] = useState<EditUserForm>({
    email: "",
    full_name: "",
    status: "active",
    role_ids: [],
  });
  const [editUserError, setEditUserError] = useState<string | null>(null);

  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetRevoke, setResetRevoke] = useState(true);
  const [resetError, setResetError] = useState<string | null>(null);

  const [deleteUserTarget, setDeleteUserTarget] = useState<User | null>(null);

  const [roleDialogOpen, setRoleDialogOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [roleForm, setRoleForm] = useState<RoleForm>(EMPTY_ROLE);
  const [roleError, setRoleError] = useState<string | null>(null);

  const [createKeyOpen, setCreateKeyOpen] = useState(false);
  const [keyForm, setKeyForm] = useState<ApiKeyForm>(EMPTY_API_KEY);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch]);

  const usersQuery = useQuery({
    queryKey: qk.users.list({ page, size, search: debouncedSearch || undefined }),
    queryFn: () =>
      usersApi.list({ page, size, search: debouncedSearch || undefined }),
    enabled: canUsers,
  });

  const rolesQuery = useQuery({
    queryKey: qk.roles.list,
    queryFn: () => rolesApi.list(),
    enabled: canRoles || canUsers,
  });

  const matrixQuery = useQuery({
    queryKey: qk.roles.matrix,
    queryFn: () => rolesApi.matrix(),
    enabled: canRoles,
  });

  const permissionsQuery = useQuery({
    queryKey: qk.roles.permissions,
    queryFn: () => rolesApi.permissions(),
    enabled: canRoles,
  });

  const apiKeysQuery = useQuery({
    queryKey: qk.apiKeys.list,
    queryFn: () => apiKeysApi.list(),
    enabled: canKeys,
  });

  const roles = rolesQuery.data ?? [];
  const permissions = permissionsQuery.data ?? [];
  const users = usersQuery.data?.items ?? [];

  const invalidateUsers = () => {
    void queryClient.invalidateQueries({ queryKey: qk.users.all });
  };

  const invalidateRoles = () => {
    void queryClient.invalidateQueries({ queryKey: qk.roles.all });
    void queryClient.invalidateQueries({ queryKey: qk.users.all });
  };

  const invalidateKeys = () => {
    void queryClient.invalidateQueries({ queryKey: qk.apiKeys.all });
  };

  const createUserMutation = useMutation({
    mutationFn: (payload: UserPayload) => usersApi.create(payload),
    onSuccess: (user) => {
      invalidateUsers();
      setCreateUserOpen(false);
      setCreateUserForm(EMPTY_CREATE_USER);
      setCreateUserError(null);
      dispatch(showToast({ message: `User ${user.username} created`, severity: "success" }));
    },
    onError: (error) => setCreateUserError(toApiError(error).message),
  });

  const updateUserMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UserUpdatePayload }) =>
      usersApi.update(id, payload),
    onSuccess: (user) => {
      invalidateUsers();
      setEditUser(null);
      setEditUserError(null);
      dispatch(showToast({ message: `User ${user.username} updated`, severity: "success" }));
    },
    onError: (error) => setEditUserError(toApiError(error).message),
  });

  const deleteUserMutation = useMutation({
    mutationFn: (user: User) => usersApi.remove(user.id),
    onSuccess: () => {
      invalidateUsers();
      setDeleteUserTarget(null);
      dispatch(showToast({ message: "User deleted", severity: "success" }));
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const unlockMutation = useMutation({
    mutationFn: (user: User) => usersApi.unlock(user.id),
    onSuccess: (result) => {
      invalidateUsers();
      dispatch(
        showToast({
          message: result.locked_until
            ? `Lockout still active until ${formatDateTime(result.locked_until)}`
            : "Account unlocked",
          severity: result.locked_until ? "warning" : "success",
        }),
      );
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const resetPasswordMutation = useMutation({
    mutationFn: () => {
      if (!resetTarget) throw new Error("No user selected");
      return usersApi.resetPassword(resetTarget.id, resetPassword, resetRevoke);
    },
    onSuccess: (message) => {
      invalidateUsers();
      setResetTarget(null);
      setResetPassword("");
      setResetError(null);
      dispatch(showToast({ message: message.message, severity: "success" }));
    },
    onError: (error) => setResetError(toApiError(error).message),
  });

  const saveRoleMutation = useMutation({
    mutationFn: () => {
      const payload = {
        description: roleForm.description.trim() || null,
        permissions: roleForm.permissions,
      };
      return editingRole
        ? rolesApi.update(editingRole.id, payload)
        : rolesApi.create({ ...payload, name: roleForm.name.trim() });
    },
    onSuccess: (role) => {
      invalidateRoles();
      setRoleDialogOpen(false);
      setEditingRole(null);
      setRoleForm(EMPTY_ROLE);
      setRoleError(null);
      dispatch(showToast({ message: `Role ${role.name} saved`, severity: "success" }));
    },
    onError: (error) => setRoleError(toApiError(error).message),
  });

  const createKeyMutation = useMutation({
    mutationFn: () => {
      const scopes = keyForm.scopes
        .split(/[\s,]+/)
        .map((scope) => scope.trim())
        .filter(Boolean);
      return apiKeysApi.create({
        name: keyForm.name.trim(),
        scopes: scopes.length > 0 ? scopes : undefined,
        expires_in_days: keyForm.expires_in_days ? Number(keyForm.expires_in_days) : null,
      });
    },
    onSuccess: (key) => {
      invalidateKeys();
      setCreateKeyOpen(false);
      setKeyForm(EMPTY_API_KEY);
      setKeyError(null);
      setCreatedKey(key);
    },
    onError: (error) => setKeyError(toApiError(error).message),
  });

  const revokeKeyMutation = useMutation({
    mutationFn: (key: ApiKey) => apiKeysApi.revoke(key.id),
    onSuccess: () => {
      invalidateKeys();
      setRevokeTarget(null);
      dispatch(showToast({ message: "API key revoked", severity: "success" }));
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreateUser = () => {
    setCreateUserForm(EMPTY_CREATE_USER);
    setCreateUserError(null);
    setCreateUserOpen(true);
  };

  const openEditUser = (user: User) => {
    const ids = roles.filter((role) => user.roles.includes(role.name)).map((role) => role.id);
    setEditUser(user);
    setEditUserForm({
      email: user.email,
      full_name: user.full_name ?? "",
      status: user.status,
      role_ids: ids,
    });
    setEditUserError(null);
  };

  const openReset = (user: User) => {
    setResetTarget(user);
    setResetPassword("");
    setResetRevoke(true);
    setResetError(null);
  };

  const openCreateRole = () => {
    setEditingRole(null);
    setRoleForm(EMPTY_ROLE);
    setRoleError(null);
    setRoleDialogOpen(true);
  };

  const openEditRole = (role: Role) => {
    setEditingRole(role);
    setRoleForm({
      name: role.name,
      description: role.description ?? "",
      permissions: [...role.permissions],
    });
    setRoleError(null);
    setRoleDialogOpen(true);
  };

  const openCreateKey = () => {
    setKeyForm(EMPTY_API_KEY);
    setKeyError(null);
    setCreateKeyOpen(true);
  };

  const submitCreateUser = () => {
    if (createUserForm.password && createUserForm.password.length < 12) {
      setCreateUserError("Passwords must be at least 12 characters.");
      return;
    }
    createUserMutation.mutate({
      username: createUserForm.username.trim(),
      email: createUserForm.email.trim(),
      full_name: createUserForm.full_name.trim() || null,
      password: createUserForm.password || null,
      auth_provider: createUserForm.auth_provider,
      role_ids: createUserForm.role_ids,
      is_superadmin: isSuperadmin && createUserForm.is_superadmin,
    });
  };

  const submitEditUser = () => {
    if (!editUser) return;
    updateUserMutation.mutate({
      id: editUser.id,
      payload: {
        email: editUserForm.email.trim(),
        full_name: editUserForm.full_name.trim() || null,
        status: editUserForm.status,
        role_ids: editUserForm.role_ids,
      },
    });
  };

  const submitRole = () => {
    if (!editingRole && !roleForm.name.trim()) {
      setRoleError("A role name is required.");
      return;
    }
    saveRoleMutation.mutate();
  };

  const submitReset = () => {
    if (resetPassword.length < 12) {
      setResetError("Passwords must be at least 12 characters.");
      return;
    }
    resetPasswordMutation.mutate();
  };

  const userColumns: Array<DataTableColumn<User>> = [
    {
      key: "user",
      label: "User",
      render: (row) => (
        <Stack direction="row" spacing={1.25} alignItems="center">
          <Avatar sx={{ width: 32, height: 32, fontSize: 13, bgcolor: alpha(theme.palette.primary.main, 0.16), color: "primary.main" }}>
            {initials(row.full_name ?? row.username)}
          </Avatar>
          <Box sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={0.75} alignItems="center">
              <Typography variant="body2" fontWeight={600} noWrap>
                {row.full_name ?? row.username}
              </Typography>
              {row.is_superadmin && (
                <Chip size="small" color="secondary" variant="outlined" label="superadmin" />
              )}
            </Stack>
            <Typography variant="caption" color="text.secondary" display="block" noWrap>
              {row.username} · {row.email}
            </Typography>
          </Box>
        </Stack>
      ),
    },
    {
      key: "status",
      label: "Status",
      width: 120,
      render: (row) => <StatusChip status={row.status} />,
    },
    {
      key: "roles",
      label: "Roles",
      hideBelow: "md",
      render: (row) => (
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          {row.roles.length > 0 ? (
            row.roles.map((role) => (
              <Chip key={role} size="small" variant="outlined" label={role} />
            ))
          ) : (
            <Typography variant="caption" color="text.disabled">
              no roles
            </Typography>
          )}
        </Stack>
      ),
    },
    {
      key: "auth",
      label: "Provider",
      width: 130,
      hideBelow: "lg",
      render: (row) =>
        AUTH_PROVIDERS.find((provider) => provider.value === row.auth_provider)?.label ??
        row.auth_provider,
    },
    {
      key: "mfa",
      label: "MFA",
      width: 110,
      hideBelow: "sm",
      render: (row) => (
        <Chip
          size="small"
          variant="outlined"
          color={row.mfa_enabled ? "success" : "default"}
          label={row.mfa_enabled ? "enabled" : "off"}
        />
      ),
    },
    {
      key: "last_login",
      label: "Last login",
      width: 160,
      hideBelow: "lg",
      render: (row) => (
        <Tooltip title={formatDateTime(row.last_login_at)}>
          <span>{row.last_login_at ? fromNow(row.last_login_at) : "never"}</span>
        </Tooltip>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 160,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="user:write">
            <Tooltip title="Edit user">
              <IconButton size="small" onClick={() => openEditUser(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="user:write">
            <Tooltip title="Reset password">
              <IconButton size="small" onClick={() => openReset(row)}>
                <LockResetOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="user:write">
            <Tooltip title="Clear lockout">
              <IconButton
                size="small"
                onClick={() => unlockMutation.mutate(row)}
                disabled={unlockMutation.isPending}
              >
                <LockOpenOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="user:delete">
            <Tooltip title="Delete user">
              <IconButton size="small" color="error" onClick={() => setDeleteUserTarget(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        </Stack>
      ),
    },
  ];

  const roleColumns: Array<DataTableColumn<Role>> = [
    {
      key: "name",
      label: "Role",
      render: (row) => (
        <Box>
          <Stack direction="row" spacing={0.75} alignItems="center">
            <Typography variant="body2" fontWeight={600}>
              {row.name}
            </Typography>
            <Chip
              size="small"
              variant="outlined"
              color={row.is_system ? "default" : "primary"}
              label={row.is_system ? "built-in" : "custom"}
            />
          </Stack>
          <Typography variant="caption" color="text.secondary">
            {row.description ?? "No description"}
          </Typography>
        </Box>
      ),
    },
    {
      key: "permissions",
      label: "Permissions",
      width: 140,
      render: (row) => (
        <Chip size="small" label={`${row.permissions.length} granted`} variant="outlined" />
      ),
    },
    {
      key: "tenant",
      label: "Scope",
      width: 180,
      hideBelow: "md",
      render: (row) => (
        <Typography variant="caption" fontFamily="monospace" color="text.secondary">
          {row.tenant_id ?? "platform"}
        </Typography>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 90,
      render: (row) =>
        row.is_system ? (
          <Tooltip title="Built-in roles cannot be edited">
            <Typography variant="caption" color="text.disabled">
              locked
            </Typography>
          </Tooltip>
        ) : (
          <PermissionGate permission="role:write">
            <Tooltip title="Edit custom role">
              <IconButton size="small" onClick={() => openEditRole(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        ),
    },
  ];

  const apiKeyColumns: Array<DataTableColumn<ApiKey>> = [
    {
      key: "name",
      label: "Key",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.name}
          </Typography>
          <Typography variant="caption" color="text.secondary" fontFamily="monospace">
            {row.key_prefix}…
          </Typography>
        </Box>
      ),
    },
    {
      key: "scopes",
      label: "Scopes",
      hideBelow: "md",
      render: (row) => (
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          {row.scopes.length > 0 ? (
            row.scopes.map((scope) => (
              <Chip key={scope} size="small" variant="outlined" label={scope} />
            ))
          ) : (
            <Chip size="small" label="all permissions" variant="outlined" />
          )}
        </Stack>
      ),
    },
    {
      key: "expires",
      label: "Expires",
      width: 170,
      hideBelow: "lg",
      render: (row) => (row.expires_at ? formatDateTime(row.expires_at) : "never"),
    },
    {
      key: "last_used",
      label: "Last used",
      width: 150,
      hideBelow: "lg",
      render: (row) => (
        <Tooltip title={formatDateTime(row.last_used_at)}>
          <span>{row.last_used_at ? fromNow(row.last_used_at) : "never"}</span>
        </Tooltip>
      ),
    },
    {
      key: "state",
      label: "State",
      width: 110,
      render: (row) => {
        const state = apiKeyState(row);
        return <Chip size="small" color={state.color} variant="outlined" label={state.label} />;
      },
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 70,
      render: (row) =>
        row.revoked_at ? null : (
          <PermissionGate permission="apikey:write">
            <Tooltip title="Revoke key">
              <IconButton size="small" color="error" onClick={() => setRevokeTarget(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Access control"
        subtitle="Local, directory and federated identities with role-based access control, MFA and scoped API keys."
        actions={
          <>
            <Button
              variant="outlined"
              startIcon={<RefreshIcon />}
              onClick={() => {
                if (activeTab === "users") void usersQuery.refetch();
                if (activeTab === "roles") {
                  void rolesQuery.refetch();
                  void matrixQuery.refetch();
                  void permissionsQuery.refetch();
                }
                if (activeTab === "api-keys") void apiKeysQuery.refetch();
              }}
            >
              Refresh
            </Button>
            {activeTab === "users" && (
              <PermissionGate permission="user:write">
                <Button variant="contained" startIcon={<AddIcon />} onClick={openCreateUser}>
                  New user
                </Button>
              </PermissionGate>
            )}
            {activeTab === "roles" && (
              <PermissionGate permission="role:write">
                <Button variant="contained" startIcon={<AddIcon />} onClick={openCreateRole}>
                  New role
                </Button>
              </PermissionGate>
            )}
            {activeTab === "api-keys" && (
              <PermissionGate permission="apikey:write">
                <Button variant="contained" startIcon={<AddIcon />} onClick={openCreateKey}>
                  New API key
                </Button>
              </PermissionGate>
            )}
          </>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" icon={<PeopleOutlinedIcon />} label={`${usersQuery.data?.meta.total ?? 0} users`} />
            <Chip size="small" icon={<SecurityOutlinedIcon />} variant="outlined" label={`${roles.length} roles`} />
            <Chip size="small" icon={<KeyOutlinedIcon />} variant="outlined" label={`${apiKeysQuery.data?.length ?? 0} API keys`} />
          </Stack>
        }
      />

      {availableTabs.length === 0 ? (
        <EmptyState
          title="No access-control permissions"
          description="Your account can use the platform but cannot read users, roles or API keys. Ask a tenant administrator for the relevant permissions."
        />
      ) : (
        <>
          <Tabs
            value={Math.min(tab, availableTabs.length - 1)}
            onChange={(_event, value: number) => setTab(value)}
            sx={{ mb: 2 }}
            variant="scrollable"
            allowScrollButtonsMobile
          >
            {availableTabs.map((entry) => (
              <Tab key={entry.key} label={entry.label} />
            ))}
          </Tabs>

          {activeTab === "users" && (
            <>
              <DataTable
                columns={userColumns}
                rows={users}
                getRowId={(row) => row.id}
                loading={usersQuery.isLoading}
                error={usersQuery.error ? toApiError(usersQuery.error).message : null}
                onRetry={() => usersQuery.refetch()}
                page={page}
                size={size}
                total={usersQuery.data?.meta.total}
                onPageChange={setPage}
                onSizeChange={setSize}
                onRowClick={openEditUser}
                emptyTitle={search ? "No users match the search" : "No users yet"}
                emptyDescription={
                  search
                    ? "Try a different username, email address or display name."
                    : "Create local accounts or provision directory users on their first login."
                }
                emptyAction={
                  <PermissionGate permission="user:write">
                    <Button variant="contained" startIcon={<AddIcon />} onClick={openCreateUser}>
                      New user
                    </Button>
                  </PermissionGate>
                }
                toolbar={
                  <Stack
                    direction={{ xs: "column", sm: "row" }}
                    spacing={1}
                    alignItems={{ xs: "stretch", sm: "center" }}
                    justifyContent="space-between"
                  >
                    <TextField
                      size="small"
                      placeholder="Search username, email or name"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      sx={{ width: { xs: "100%", sm: 320 } }}
                      InputProps={{
                        startAdornment: <SearchIcon fontSize="small" sx={{ mr: 1, color: "action" }} />,
                      }}
                    />
                    <Typography variant="caption" color="text.secondary">
                      Tenant-scoped identities. SuperAdmins only appear in the platform tenant.
                    </Typography>
                  </Stack>
                }
              />
            </>
          )}

          {activeTab === "roles" && (
            <Stack spacing={2}>
              <Alert severity="info">
                Built-in roles are immutable and enforced by the backend. Custom roles may only be edited by
                holders of role:write; every change is written to the audit trail.
              </Alert>

              <DataTable
                columns={roleColumns}
                rows={roles}
                getRowId={(row) => row.id}
                loading={rolesQuery.isLoading}
                error={rolesQuery.error ? toApiError(rolesQuery.error).message : null}
                onRetry={() => rolesQuery.refetch()}
                emptyTitle="No roles defined"
                emptyDescription="Create a custom role to grant a least-privilege permission set."
                emptyAction={
                  <PermissionGate permission="role:write">
                    <Button variant="contained" startIcon={<AddIcon />} onClick={openCreateRole}>
                      New role
                    </Button>
                  </PermissionGate>
                }
              />

              <Card>
                <CardContent>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <SecurityOutlinedIcon fontSize="small" color="action" />
                    <Typography variant="h5">Built-in role matrix</Typography>
                  </Stack>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    Reference permissions for the six platform roles. SuperAdmin implicitly holds every
                    permission.
                  </Typography>
                  {matrixQuery.isLoading ? (
                    <Typography variant="body2" color="text.secondary">
                      Loading matrix…
                    </Typography>
                  ) : matrixQuery.isError ? (
                    <Alert severity="error">{toApiError(matrixQuery.error).message}</Alert>
                  ) : (
                    <Stack spacing={1}>
                      {(matrixQuery.data ?? []).map((entry) => (
                        <Accordion key={entry.role} disableGutters variant="outlined">
                          <AccordionSummary expandIcon={<ExpandMoreOutlinedIcon />}>
                            <Stack
                              direction={{ xs: "column", sm: "row" }}
                              spacing={{ xs: 0.25, sm: 1.5 }}
                              alignItems={{ xs: "flex-start", sm: "center" }}
                              sx={{ width: "100%" }}
                            >
                              <Typography variant="subtitle2" sx={{ minWidth: 130 }}>
                                {entry.role}
                              </Typography>
                              <Typography variant="body2" color="text.secondary" sx={{ flexGrow: 1 }}>
                                {entry.description}
                              </Typography>
                              <Chip size="small" variant="outlined" label={`${entry.permissions.length} permissions`} />
                            </Stack>
                          </AccordionSummary>
                          <AccordionDetails>
                            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                              {entry.permissions.length === 0 ? (
                                <Typography variant="caption" color="text.secondary">
                                  Read-only baseline with no explicit writes.
                                </Typography>
                              ) : (
                                entry.permissions.map((permission) => (
                                  <Chip
                                    key={permission}
                                    size="small"
                                    variant="outlined"
                                    label={permission}
                                    sx={{ fontFamily: "monospace", fontSize: 11 }}
                                  />
                                ))
                              )}
                            </Stack>
                          </AccordionDetails>
                        </Accordion>
                      ))}
                    </Stack>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardContent>
                  <Typography variant="h5" sx={{ mb: 0.5 }}>
                    Permission catalogue
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                    {permissions.length} permissions across{" "}
                    {new Set(permissions.map((permission) => permission.category ?? "general")).size}{" "}
                    categories.
                  </Typography>
                  {permissionsQuery.isError ? (
                    <Alert severity="error">{toApiError(permissionsQuery.error).message}</Alert>
                  ) : (
                    <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                      {permissions.map((permission) => (
                        <Tooltip key={permission.code} title={permission.description ?? permission.code}>
                          <Chip
                            size="small"
                            variant="outlined"
                            label={permission.code}
                            sx={{ fontFamily: "monospace", fontSize: 11 }}
                          />
                        </Tooltip>
                      ))}
                    </Stack>
                  )}
                </CardContent>
              </Card>
            </Stack>
          )}

          {activeTab === "api-keys" && (
            <Stack spacing={2}>
              <Alert severity="info">
                API keys authenticate automation with a permission subset. The plaintext value is returned
                exactly once at creation and is never stored.
              </Alert>
              <DataTable
                columns={apiKeyColumns}
                rows={apiKeysQuery.data ?? []}
                getRowId={(row) => row.id}
                loading={apiKeysQuery.isLoading}
                error={apiKeysQuery.error ? toApiError(apiKeysQuery.error).message : null}
                onRetry={() => apiKeysQuery.refetch()}
                emptyTitle="No API keys"
                emptyDescription="Create a scoped key for CI pipelines, GitOps controllers or monitoring exporters."
                emptyAction={
                  <PermissionGate permission="apikey:write">
                    <Button variant="contained" startIcon={<AddIcon />} onClick={openCreateKey}>
                      New API key
                    </Button>
                  </PermissionGate>
                }
              />
            </Stack>
          )}
        </>
      )}

      <FormDialog
        open={createUserOpen}
        title="Create user"
        description={
          <Typography variant="body2" color="text.secondary">
            Local users receive the password you set; directory and federated users authenticate upstream and
            are linked by external identity.
          </Typography>
        }
        submitLabel="Create user"
        loading={createUserMutation.isPending}
        error={createUserError}
        submitDisabled={!createUserForm.username.trim() || !createUserForm.email.trim()}
        onSubmit={submitCreateUser}
        onClose={() => setCreateUserOpen(false)}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Username"
            value={createUserForm.username}
            onChange={(event) =>
              setCreateUserForm((value) => ({ ...value, username: event.target.value }))
            }
            required
            autoFocus
            fullWidth
          />
          <TextField
            label="Email"
            type="email"
            value={createUserForm.email}
            onChange={(event) =>
              setCreateUserForm((value) => ({ ...value, email: event.target.value }))
            }
            required
            fullWidth
          />
        </Stack>
        <TextField
          label="Full name"
          value={createUserForm.full_name}
          onChange={(event) =>
            setCreateUserForm((value) => ({ ...value, full_name: event.target.value }))
          }
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Authentication provider"
            value={createUserForm.auth_provider}
            onChange={(event) =>
              setCreateUserForm((value) => ({ ...value, auth_provider: event.target.value }))
            }
          >
            {AUTH_PROVIDERS.map((provider) => (
              <MenuItem key={provider.value} value={provider.value}>
                {provider.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Initial password"
            type="password"
            value={createUserForm.password}
            onChange={(event) =>
              setCreateUserForm((value) => ({ ...value, password: event.target.value }))
            }
            helperText="Minimum 12 characters. Leave empty for federated accounts."
          />
        </Stack>
        <TextField
          select
          label="Roles"
          value={createUserForm.role_ids}
          onChange={(event) => {
            const value = event.target.value;
            setCreateUserForm((current) => ({
              ...current,
              role_ids: typeof value === "string" ? value.split(",") : (value as string[]),
            }));
          }}
          SelectProps={{
            multiple: true,
            renderValue: (selected) =>
              roles
                .filter((role) => (selected as string[]).includes(role.id))
                .map((role) => role.name)
                .join(", "),
          }}
          helperText="Operators get read/write on configuration; Auditors receive read-only evidence access."
        >
          {roles.map((role) => (
            <MenuItem key={role.id} value={role.id}>
              <Checkbox size="small" checked={createUserForm.role_ids.includes(role.id)} />
              <Box>
                <Typography variant="body2">{role.name}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {role.description ?? (role.is_system ? "Built-in role" : "Custom role")}
                </Typography>
              </Box>
            </MenuItem>
          ))}
        </TextField>
        {isSuperadmin && (
          <FormControlLabel
            control={
              <Checkbox
                checked={createUserForm.is_superadmin}
                onChange={(event) =>
                  setCreateUserForm((value) => ({ ...value, is_superadmin: event.target.checked }))
                }
              />
            }
            label="Grant platform SuperAdmin (all tenants)"
          />
        )}
      </FormDialog>

      <FormDialog
        open={Boolean(editUser)}
        title={editUser ? `Edit ${editUser.username}` : "Edit user"}
        description={
          editUser ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <StatusChip status={editUser.status} />
              <Chip size="small" variant="outlined" label={editUser.auth_provider} />
              <Chip
                size="small"
                variant="outlined"
                color={editUser.mfa_enabled ? "success" : "default"}
                label={editUser.mfa_enabled ? "MFA enabled" : "MFA disabled"}
              />
              <Chip size="small" variant="outlined" label={`last login ${fromNow(editUser.last_login_at)}`} />
            </Stack>
          ) : undefined
        }
        submitLabel="Save changes"
        loading={updateUserMutation.isPending}
        error={editUserError}
        submitDisabled={!editUserForm.email.trim()}
        onSubmit={submitEditUser}
        onClose={() => setEditUser(null)}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Email"
            type="email"
            value={editUserForm.email}
            onChange={(event) =>
              setEditUserForm((value) => ({ ...value, email: event.target.value }))
            }
            required
          />
          <TextField
            select
            label="Status"
            value={editUserForm.status}
            onChange={(event) =>
              setEditUserForm((value) => ({ ...value, status: event.target.value }))
            }
          >
            {USER_STATUSES.map((status) => (
              <MenuItem key={status} value={status}>
                {status}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <TextField
          label="Full name"
          value={editUserForm.full_name}
          onChange={(event) =>
            setEditUserForm((value) => ({ ...value, full_name: event.target.value }))
          }
        />
        <TextField
          select
          label="Roles"
          value={editUserForm.role_ids}
          onChange={(event) => {
            const value = event.target.value;
            setEditUserForm((current) => ({
              ...current,
              role_ids: typeof value === "string" ? value.split(",") : (value as string[]),
            }));
          }}
          SelectProps={{
            multiple: true,
            renderValue: (selected) =>
              roles
                .filter((role) => (selected as string[]).includes(role.id))
                .map((role) => role.name)
                .join(", "),
          }}
        >
          {roles.map((role) => (
            <MenuItem key={role.id} value={role.id}>
              <Checkbox size="small" checked={editUserForm.role_ids.includes(role.id)} />
              <Box>
                <Typography variant="body2">{role.name}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {role.permissions.length} permissions
                </Typography>
              </Box>
            </MenuItem>
          ))}
        </TextField>
      </FormDialog>

      <FormDialog
        open={Boolean(resetTarget)}
        title={resetTarget ? `Reset password for ${resetTarget.username}` : "Reset password"}
        description={
          <Typography variant="body2" color="text.secondary">
            The new password must satisfy the platform policy (minimum 12 characters). Revoking sessions
            invalidates every refresh token for this user immediately.
          </Typography>
        }
        submitLabel="Reset password"
        loading={resetPasswordMutation.isPending}
        error={resetError}
        submitDisabled={resetPassword.length < 12}
        onSubmit={submitReset}
        onClose={() => setResetTarget(null)}
      >
        <TextField
          label="New password"
          type="password"
          value={resetPassword}
          onChange={(event) => setResetPassword(event.target.value)}
          autoFocus
          helperText={`${resetPassword.length} characters`}
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={resetRevoke}
              onChange={(event) => setResetRevoke(event.target.checked)}
            />
          }
          label="Revoke all active sessions for this user"
        />
      </FormDialog>

      <FormDialog
        open={roleDialogOpen}
        title={editingRole ? `Edit role ${editingRole.name}` : "Create custom role"}
        description={
          <Typography variant="body2" color="text.secondary">
            Select the exact permission set. Roles are additive; users inherit the union of all assigned
            roles and API-key scopes are intersected at request time.
          </Typography>
        }
        submitLabel={editingRole ? "Save role" : "Create role"}
        loading={saveRoleMutation.isPending}
        error={roleError}
        submitDisabled={!editingRole && !roleForm.name.trim()}
        onSubmit={submitRole}
        onClose={() => setRoleDialogOpen(false)}
        maxWidth="md"
      >
        <TextField
          label="Role name"
          value={roleForm.name}
          onChange={(event) => setRoleForm((value) => ({ ...value, name: event.target.value }))}
          disabled={Boolean(editingRole)}
          required={!editingRole}
          helperText={editingRole ? "Role names are immutable" : "For example: SiteOperator"}
        />
        <TextField
          label="Description"
          value={roleForm.description}
          onChange={(event) =>
            setRoleForm((value) => ({ ...value, description: event.target.value }))
          }
          multiline
          minRows={2}
        />
        <Box>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle2">Permissions</Typography>
            <Chip size="small" variant="outlined" label={`${roleForm.permissions.length} selected`} />
          </Stack>
          <PermissionPicker
            permissions={permissions}
            value={roleForm.permissions}
            onChange={(next) => setRoleForm((value) => ({ ...value, permissions: next }))}
          />
        </Box>
      </FormDialog>

      <FormDialog
        open={createKeyOpen}
        title="Create API key"
        description={
          <Typography variant="body2" color="text.secondary">
            The key inherits your tenant and is limited to the listed scopes. Leave scopes empty to grant the
            key every permission you currently hold.
          </Typography>
        }
        submitLabel="Create key"
        loading={createKeyMutation.isPending}
        error={keyError}
        submitDisabled={!keyForm.name.trim()}
        onSubmit={() => createKeyMutation.mutate()}
        onClose={() => setCreateKeyOpen(false)}
        maxWidth="md"
      >
        <TextField
          label="Key name"
          value={keyForm.name}
          onChange={(event) => setKeyForm((value) => ({ ...value, name: event.target.value }))}
          required
          autoFocus
          helperText="Use a name that identifies the consumer, for example gitlab-ci-policy-sync"
        />
        <Autocomplete
          multiple
          freeSolo
          options={permissions.map((permission) => permission.code)}
          value={keyForm.scopes
            .split(/[\s,]+/)
            .map((scope) => scope.trim())
            .filter(Boolean)}
          onChange={(_event, value) =>
            setKeyForm((current) => ({ ...current, scopes: value.join(", ") }))
          }
          renderInput={(params) => (
            <TextField
              {...params}
              label="Scopes"
              placeholder="device:read, policy:read"
              helperText="Empty means all permissions held by you; '*' is also accepted by automation that seeds keys."
            />
          )}
        />
        <TextField
          label="Expires in days"
          type="number"
          value={keyForm.expires_in_days}
          onChange={(event) =>
            setKeyForm((value) => ({ ...value, expires_in_days: event.target.value }))
          }
          inputProps={{ min: 1, max: 3650 }}
          helperText="Empty means the key never expires. Rotation is still recommended."
        />
      </FormDialog>

      <FormDialog
        open={Boolean(createdKey)}
        title="API key created"
        description={
          createdKey ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip size="small" label={createdKey.name} />
              <Chip size="small" variant="outlined" label={createdKey.key_prefix} />
              <Chip
                size="small"
                variant="outlined"
                label={
                  createdKey.expires_at ? `expires ${formatDateTime(createdKey.expires_at)}` : "no expiry"
                }
              />
            </Stack>
          ) : undefined
        }
        submitLabel="Done"
        onSubmit={() => setCreatedKey(null)}
        onClose={() => setCreatedKey(null)}
        maxWidth="md"
      >
        {createdKey && (
          <>
            <Alert severity="warning">
              Copy the key now. This is the only time the plaintext secret is shown; only its prefix and
              hash are stored.
            </Alert>
            <CodeBlock code={createdKey.key} language="api-key" maxHeight={120} />
            <Typography variant="caption" color="text.secondary">
              Set it as <code>X-API-Key</code> or <code>Authorization: Bearer &lt;key&gt;</code> in your
              automation. Revoke it from this page if it leaks.
            </Typography>
          </>
        )}
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteUserTarget)}
        title="Delete user"
        description={
          deleteUserTarget
            ? `Delete ${deleteUserTarget.username}? The account is soft-deleted, its sessions are revoked and the audit trail is retained.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteUserMutation.isPending}
        onConfirm={() => deleteUserTarget && deleteUserMutation.mutate(deleteUserTarget)}
        onClose={() => setDeleteUserTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(revokeTarget)}
        title="Revoke API key"
        description={
          revokeTarget
            ? `Revoke ${revokeTarget.name} (${revokeTarget.key_prefix}…)? Automation using this key fails immediately with 401.`
            : undefined
        }
        confirmLabel="Revoke"
        confirmColor="error"
        loading={revokeKeyMutation.isPending}
        onConfirm={() => revokeTarget && revokeKeyMutation.mutate(revokeTarget)}
        onClose={() => setRevokeTarget(null)}
      />
    </>
  );
}

export default UsersPage;
