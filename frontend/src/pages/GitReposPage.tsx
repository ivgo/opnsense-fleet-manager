import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import SyncOutlinedIcon from "@mui/icons-material/SyncOutlined";
import CommitOutlinedIcon from "@mui/icons-material/CommitOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { gitApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { GitRepository, GitRepositoryPayload } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import { useDebounce } from "@/hooks/useDebounce";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { EMPTY, formatDateTime, formatNumber, fromNow, titleCase, truncate } from "@/utils/format";

const PROVIDERS: Array<{ value: GitRepository["provider"]; label: string }> = [
  { value: "github", label: "GitHub" },
  { value: "gitlab", label: "GitLab" },
  { value: "azure_devops", label: "Azure DevOps" },
  { value: "generic", label: "Generic Git" },
];

const AUTH_TYPES: Array<{ value: GitRepository["auth_type"]; label: string }> = [
  { value: "token", label: "Personal access token" },
  { value: "ssh", label: "SSH key" },
  { value: "oauth", label: "OAuth" },
];

interface RepoFormState {
  name: string;
  provider: GitRepository["provider"];
  url: string;
  default_branch: string;
  auth_type: GitRepository["auth_type"];
  token: string;
  auto_sync: boolean;
  sync_interval_minutes: string;
}

const EMPTY_FORM: RepoFormState = {
  name: "",
  provider: "github",
  url: "",
  default_branch: "main",
  auth_type: "token",
  token: "",
  auto_sync: false,
  sync_interval_minutes: "60",
};

export function GitReposPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<GitRepository | null>(null);
  const [form, setForm] = useState<RepoFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<GitRepository | null>(null);

  const listParams = useMemo(
    () => ({
      page,
      size,
      search: debouncedSearch || undefined,
    }),
    [page, size, debouncedSearch],
  );

  const reposQuery = useQuery({
    queryKey: qk.git.repositories(listParams),
    queryFn: () => gitApi.repositories(listParams),
  });

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.git.all });
    void queryClient.invalidateQueries({ queryKey: qk.policies.all });
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const interval = Number(form.sync_interval_minutes) || 60;
      if (editing) {
        return gitApi.updateRepository(editing.id, {
          default_branch: form.default_branch.trim() || "main",
          auto_sync: form.auto_sync,
          sync_interval_minutes: interval,
          token: form.token.trim() || undefined,
        });
      }
      const payload: GitRepositoryPayload = {
        name: form.name.trim(),
        provider: form.provider,
        url: form.url.trim(),
        default_branch: form.default_branch.trim() || "main",
        auth_type: form.auth_type,
        auto_sync: form.auto_sync,
        sync_interval_minutes: interval,
        token: form.token.trim() || null,
      };
      return gitApi.createRepository(payload);
    },
    onSuccess: (repo) => {
      invalidate();
      setDialogOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(showToast({ message: `Repository ${repo.name} saved`, severity: "success" }));
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const syncMutation = useMutation({
    mutationFn: (repo: GitRepository) => gitApi.sync(repo.id),
    onSuccess: (result) => {
      invalidate();
      dispatch(
        showToast({
          message: `Sync complete: ${result.created} created, ${result.updated} updated, ${result.invalid} invalid`,
          severity: result.invalid > 0 ? "warning" : "success",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => gitApi.removeRepository(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Repository disconnected", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setDialogOpen(true);
  };

  const openEdit = (repo: GitRepository) => {
    setEditing(repo);
    setForm({
      name: repo.name,
      provider: repo.provider,
      url: repo.url,
      default_branch: repo.default_branch,
      auth_type: repo.auth_type,
      token: "",
      auto_sync: repo.auto_sync,
      sync_interval_minutes: String(repo.sync_interval_minutes),
    });
    setFormError(null);
    setDialogOpen(true);
  };

  const columns: Array<DataTableColumn<GitRepository>> = [
    {
      key: "name",
      label: "Repository",
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <CommitOutlinedIcon fontSize="small" color="action" />
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" fontWeight={600}>
              {row.name}
            </Typography>
            <Tooltip title={row.url}>
              <Typography variant="caption" color="text.secondary" display="block">
                {truncate(row.url, 56)}
              </Typography>
            </Tooltip>
          </Box>
        </Stack>
      ),
    },
    {
      key: "provider",
      label: "Provider",
      width: 140,
      render: (row) => (
        <Chip size="small" variant="outlined" label={titleCase(row.provider)} />
      ),
    },
    {
      key: "default_branch",
      label: "Branch",
      width: 120,
      monospace: true,
      render: (row) => row.default_branch,
    },
    {
      key: "auth_type",
      label: "Auth",
      width: 110,
      hideBelow: "md",
      render: (row) => titleCase(row.auth_type),
    },
    {
      key: "auto_sync",
      label: "Auto-sync",
      width: 130,
      hideBelow: "md",
      render: (row) =>
        row.auto_sync ? (
          <Chip size="small" color="success" label={`Every ${row.sync_interval_minutes} min`} />
        ) : (
          <Chip size="small" variant="outlined" label="Manual" />
        ),
    },
    {
      key: "last_sync_at",
      label: "Last sync",
      width: 150,
      hideBelow: "sm",
      render: (row) => (
        <Tooltip title={formatDateTime(row.last_sync_at)}>
          <span>{row.last_sync_at ? fromNow(row.last_sync_at) : EMPTY}</span>
        </Tooltip>
      ),
    },
    {
      key: "last_commit_sha",
      label: "Commit",
      width: 120,
      hideBelow: "lg",
      monospace: true,
      render: (row) => (row.last_commit_sha ? row.last_commit_sha.slice(0, 8) : EMPTY),
    },
    {
      key: "status",
      label: "Status",
      width: 120,
      render: (row) => (
        <Chip
          size="small"
          color={row.status === "error" ? "error" : row.status === "synced" ? "success" : "default"}
          variant={row.status === "error" ? "filled" : "outlined"}
          label={titleCase(row.status)}
        />
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 140,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="git:write">
            <Tooltip title="Sync now">
              <span>
                <IconButton
                  size="small"
                  disabled={syncMutation.isPending}
                  onClick={() => syncMutation.mutate(row)}
                >
                  <SyncOutlinedIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="git:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEdit(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="git:write">
            <Tooltip title="Disconnect">
              <IconButton size="small" color="error" onClick={() => setDeleteTarget(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        </Stack>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Git repositories"
        subtitle="Connect GitOps repositories, sync policy files and publish validated changes back as commits."
        actions={
          <PermissionGate permission="git:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              Connect repository
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip
              size="small"
              label={`${formatNumber(reposQuery.data?.meta.total ?? 0)} repositories`}
            />
          </Stack>
        }
      />

      <DataTable
        columns={columns}
        rows={reposQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={reposQuery.isLoading}
        error={reposQuery.error ? toApiError(reposQuery.error).message : null}
        onRetry={() => reposQuery.refetch()}
        page={page}
        size={size}
        total={reposQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        emptyTitle="No Git repositories"
        emptyDescription="Connect GitHub, GitLab, Azure DevOps or a generic Git remote to manage policies as code."
        emptyAction={
          <PermissionGate permission="git:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              Connect repository
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <TextField
              placeholder="Search name or URL"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              sx={{ width: { xs: "100%", sm: 300 } }}
            />
          </Stack>
        }
      />

      <FormDialog
        open={dialogOpen}
        title={editing ? `Edit ${editing.name}` : "Connect Git repository"}
        loading={saveMutation.isPending}
        error={formError}
        submitLabel={editing ? "Save changes" : "Connect"}
        submitDisabled={!editing && (!form.name.trim() || !form.url.trim())}
        onSubmit={() => saveMutation.mutate()}
        onClose={() => {
          setDialogOpen(false);
          setEditing(null);
        }}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Name"
            value={form.name}
            onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
            disabled={Boolean(editing)}
            required
            fullWidth
            autoFocus
          />
          <TextField
            select
            label="Provider"
            value={form.provider}
            onChange={(event) =>
              setForm((value) => ({ ...value, provider: event.target.value as GitRepository["provider"] }))
            }
            disabled={Boolean(editing)}
            fullWidth
          >
            {PROVIDERS.map((provider) => (
              <MenuItem key={provider.value} value={provider.value}>
                {provider.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <TextField
          label="Repository URL"
          value={form.url}
          onChange={(event) => setForm((value) => ({ ...value, url: event.target.value }))}
          placeholder="https://github.com/acme/network-policies.git"
          disabled={Boolean(editing)}
          required
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Default branch"
            value={form.default_branch}
            onChange={(event) => setForm((value) => ({ ...value, default_branch: event.target.value }))}
            placeholder="main"
            fullWidth
          />
          <TextField
            select
            label="Authentication"
            value={form.auth_type}
            onChange={(event) =>
              setForm((value) => ({ ...value, auth_type: event.target.value as GitRepository["auth_type"] }))
            }
            disabled={Boolean(editing)}
            fullWidth
          >
            {AUTH_TYPES.map((auth) => (
              <MenuItem key={auth.value} value={auth.value}>
                {auth.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <TextField
          label={editing ? "Rotate access token" : "Access token"}
          value={form.token}
          onChange={(event) => setForm((value) => ({ ...value, token: event.target.value }))}
          type="password"
          placeholder={editing ? "Leave empty to keep the current token" : "ghp_…"}
          helperText="Encrypted at rest; only used for clone, sync and publish"
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Auto-sync"
            value={form.auto_sync ? "on" : "off"}
            onChange={(event) =>
              setForm((value) => ({ ...value, auto_sync: event.target.value === "on" }))
            }
            fullWidth
          >
            <MenuItem value="off">Manual only</MenuItem>
            <MenuItem value="on">Scheduled sync</MenuItem>
          </TextField>
          <TextField
            label="Sync interval (minutes)"
            value={form.sync_interval_minutes}
            onChange={(event) =>
              setForm((value) => ({ ...value, sync_interval_minutes: event.target.value }))
            }
            inputProps={{ inputMode: "numeric" }}
            helperText="5 – 1,440 minutes"
            disabled={!form.auto_sync}
            fullWidth
          />
        </Stack>
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Disconnect repository"
        description={
          deleteTarget
            ? `Disconnect ${deleteTarget.name}? Linked policies stay in OFME but stop syncing.`
            : undefined
        }
        confirmLabel="Disconnect"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onClose={() => setDeleteTarget(null)}
      />
    </>
  );
}

export default GitReposPage;
