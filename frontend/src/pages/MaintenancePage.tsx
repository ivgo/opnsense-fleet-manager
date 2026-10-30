import { useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
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
import EventBusyOutlinedIcon from "@mui/icons-material/EventBusyOutlined";
import PauseCircleOutlineIcon from "@mui/icons-material/PauseCircleOutline";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import dayjs from "dayjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toApiError } from "@/api/client";
import { devicesApi, groupsApi, maintenanceApi, sitesApi } from "@/api/endpoints";
import { qk } from "@/api/queryKeys";
import type { MaintenanceTarget, MaintenanceWindow } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { MAINTENANCE_TARGET_LABELS } from "@/utils/constants";
import { formatDateTime, formatDuration, fromNow } from "@/utils/format";

interface WindowFormState {
  name: string;
  description: string;
  starts_at: string;
  ends_at: string;
  target_type: MaintenanceTarget;
  target_ids: string[];
  silence_alerts: boolean;
  silence_notifications: boolean;
  enabled: boolean;
}

const TARGETS: MaintenanceTarget[] = ["fleet", "device", "site", "group"];

function toLocalInput(value: string): string {
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DDTHH:mm") : "";
}

function toIso(value: string): string {
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.toISOString() : "";
}

function defaultForm(): WindowFormState {
  const start = dayjs().add(5, "minute").second(0);
  return {
    name: "",
    description: "",
    starts_at: start.format("YYYY-MM-DDTHH:mm"),
    ends_at: start.add(2, "hour").format("YYYY-MM-DDTHH:mm"),
    target_type: "fleet",
    target_ids: [],
    silence_alerts: true,
    silence_notifications: true,
    enabled: true,
  };
}

function windowState(window: MaintenanceWindow): string {
  if (!window.enabled) return "disabled";
  if (window.active) return "active";
  if (dayjs(window.ends_at).isBefore(dayjs())) return "expired";
  return "scheduled";
}

export function MaintenancePage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<MaintenanceWindow | null>(null);
  const [form, setForm] = useState<WindowFormState>(defaultForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<MaintenanceWindow | null>(null);

  const windowsQuery = useQuery({
    queryKey: qk.maintenance.list,
    queryFn: () => maintenanceApi.list(),
    refetchInterval: 60_000,
  });

  const devicesQuery = useQuery({
    queryKey: qk.devices.list({ size: 500 }),
    queryFn: () => devicesApi.list({ size: 500 }),
    staleTime: 120_000,
  });

  const sitesQuery = useQuery({
    queryKey: qk.sites.list({ size: 200 }),
    queryFn: () => sitesApi.list({ size: 200 }),
    staleTime: 120_000,
  });

  const groupsQuery = useQuery({
    queryKey: qk.groups.list({ size: 200 }),
    queryFn: () => groupsApi.list({ size: 200 }),
    staleTime: 120_000,
  });

  const windows = useMemo(() => windowsQuery.data ?? [], [windowsQuery.data]);
  const devices = devicesQuery.data?.items ?? [];
  const sites = sitesQuery.data?.items ?? [];
  const groups = groupsQuery.data?.items ?? [];

  const activeCount = windows.filter((window) => window.active).length;
  const scheduledCount = windows.filter((window) => windowState(window) === "scheduled").length;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.maintenance.all });
    void queryClient.invalidateQueries({ queryKey: qk.alerts.all });
  };

  const targetLabel = (window: MaintenanceWindow) => {
    const base = MAINTENANCE_TARGET_LABELS[window.target_type] ?? window.target_type;
    if (window.target_type === "fleet") return base;
    return `${base} · ${window.target_ids.length}`;
  };

  const targetNames = (window: MaintenanceWindow) => {
    if (window.target_type === "fleet") return "Every device in the tenant";
    const lookup =
      window.target_type === "device"
        ? devices
        : window.target_type === "site"
          ? sites
          : groups;
    const names = window.target_ids
      .map((id) => lookup.find((item) => item.id === id)?.name)
      .filter((name): name is string => Boolean(name));
    return names.length > 0 ? names.join(", ") : `${window.target_ids.length} target(s)`;
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        starts_at: toIso(form.starts_at),
        ends_at: toIso(form.ends_at),
        enabled: form.enabled,
        target_type: form.target_type,
        target_ids: form.target_type === "fleet" ? [] : form.target_ids,
        silence_alerts: form.silence_alerts,
        silence_notifications: form.silence_notifications,
      };
      return editing
        ? maintenanceApi.update(editing.id, payload)
        : maintenanceApi.create(payload);
    },
    onSuccess: (window) => {
      invalidate();
      setDialogOpen(false);
      setEditing(null);
      setForm(defaultForm());
      setFormError(null);
      dispatch(
        showToast({
          message: `Maintenance window "${window.name}" ${editing ? "updated" : "created"}`,
          severity: "success",
        }),
      );
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ window, enabled }: { window: MaintenanceWindow; enabled: boolean }) =>
      maintenanceApi.update(window.id, { enabled }),
    onSuccess: (window) => {
      invalidate();
      dispatch(
        showToast({
          message: `Window "${window.name}" ${window.enabled ? "enabled" : "disabled"}`,
          severity: "success",
        }),
      );
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const deleteMutation = useMutation({
    mutationFn: (window: MaintenanceWindow) => maintenanceApi.remove(window.id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Maintenance window deleted", severity: "success" }));
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreate = () => {
    setEditing(null);
    setForm(defaultForm());
    setFormError(null);
    setDialogOpen(true);
  };

  const openEdit = (window: MaintenanceWindow) => {
    setEditing(window);
    setForm({
      name: window.name,
      description: window.description ?? "",
      starts_at: toLocalInput(window.starts_at),
      ends_at: toLocalInput(window.ends_at),
      target_type: window.target_type,
      target_ids: window.target_ids,
      silence_alerts: window.silence_alerts,
      silence_notifications: window.silence_notifications,
      enabled: window.enabled,
    });
    setFormError(null);
    setDialogOpen(true);
  };

  const submit = () => {
    if (form.name.trim().length < 2) {
      setFormError("Give the window a name of at least two characters.");
      return;
    }
    if (!form.starts_at || !form.ends_at) {
      setFormError("Both the start and end time are required.");
      return;
    }
    if (dayjs(form.ends_at).isBefore(dayjs(form.starts_at)) || dayjs(form.ends_at).isSame(dayjs(form.starts_at))) {
      setFormError("The window must end after it starts.");
      return;
    }
    if (form.target_type !== "fleet" && form.target_ids.length === 0) {
      setFormError(`Select at least one ${form.target_type}.`);
      return;
    }
    setFormError(null);
    saveMutation.mutate();
  };

  const targetOptions = useMemo(() => {
    if (form.target_type === "device") return devices.map((device) => ({ id: device.id, name: device.name }));
    if (form.target_type === "site") return sites.map((site) => ({ id: site.id, name: site.name }));
    if (form.target_type === "group") return groups.map((group) => ({ id: group.id, name: group.name }));
    return [];
  }, [form.target_type, devices, sites, groups]);

  const columns: Array<DataTableColumn<MaintenanceWindow>> = [
    {
      key: "name",
      label: "Window",
      render: (window) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {window.name}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {window.description ?? targetNames(window)}
          </Typography>
        </Box>
      ),
    },
    {
      key: "target",
      label: "Target",
      width: 180,
      render: (window) => (
        <Tooltip title={targetNames(window)}>
          <Chip size="small" variant="outlined" label={targetLabel(window)} />
        </Tooltip>
      ),
    },
    {
      key: "schedule",
      label: "Schedule",
      width: 220,
      render: (window) => {
        const minutes = Math.max(0, dayjs(window.ends_at).diff(dayjs(window.starts_at), "minute"));
        return (
          <Box>
            <Typography variant="body2">
              {formatDateTime(window.starts_at)} → {dayjs(window.ends_at).format("HH:mm")}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {formatDuration(minutes * 60)} · {window.active ? "active now" : fromNow(window.starts_at)}
            </Typography>
          </Box>
        );
      },
    },
    {
      key: "state",
      label: "State",
      width: 130,
      render: (window) => <StatusChip status={windowState(window)} />,
    },
    {
      key: "silence",
      label: "Silences",
      width: 200,
      hideBelow: "md",
      render: (window) => (
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          <Chip
            size="small"
            label="Alerts"
            color={window.silence_alerts ? "warning" : "default"}
            variant={window.silence_alerts ? "filled" : "outlined"}
          />
          <Chip
            size="small"
            label="Notifications"
            color={window.silence_notifications ? "warning" : "default"}
            variant={window.silence_notifications ? "filled" : "outlined"}
          />
        </Stack>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 140,
      render: (window) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="alert:write">
            <Tooltip title={window.enabled ? "Disable window" : "Enable window"}>
              <IconButton
                size="small"
                disabled={toggleMutation.isPending}
                onClick={(event) => {
                  event.stopPropagation();
                  toggleMutation.mutate({ window, enabled: !window.enabled });
                }}
              >
                {window.enabled ? (
                  <PauseCircleOutlineIcon fontSize="small" />
                ) : (
                  <PlayCircleOutlineIcon fontSize="small" />
                )}
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="alert:write">
            <Tooltip title="Edit">
              <IconButton
                size="small"
                onClick={(event) => {
                  event.stopPropagation();
                  openEdit(window);
                }}
              >
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="alert:write">
            <Tooltip title="Delete">
              <IconButton
                size="small"
                color="error"
                onClick={(event) => {
                  event.stopPropagation();
                  setDeleteTarget(window);
                }}
              >
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
        title="Maintenance windows"
        subtitle="Quiet hours suppress alert creation and notifications for the fleet, a site, a group or individual devices."
        actions={
          <PermissionGate permission="alert:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New window
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
            <Chip size="small" label={`${windows.length} windows`} />
            <Chip size="small" color="success" variant="outlined" label={`${activeCount} active`} />
            <Chip size="small" variant="outlined" label={`${scheduledCount} scheduled`} />
          </Stack>
        }
      />

      <DataTable
        columns={columns}
        rows={windows}
        getRowId={(window) => window.id}
        loading={windowsQuery.isLoading}
        error={windowsQuery.error ? toApiError(windowsQuery.error).message : null}
        onRetry={() => windowsQuery.refetch()}
        onRowClick={openEdit}
        emptyTitle="No maintenance windows"
        emptyDescription="Create a window to silence alerts during planned changes, upgrades or migrations."
        emptyAction={
          <PermissionGate permission="alert:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New window
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
            <Stack direction="row" spacing={1} alignItems="center">
              <EventBusyOutlinedIcon fontSize="small" color="disabled" />
              <Typography variant="body2" color="text.secondary">
                Active windows are evaluated on every heartbeat.
              </Typography>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              {activeCount > 0 ? `${activeCount} window(s) silencing now` : "Nothing silenced"}
            </Typography>
          </Stack>
        }
      />

      <FormDialog
        open={dialogOpen}
        title={editing ? `Edit ${editing.name}` : "New maintenance window"}
        description={
          <Typography variant="body2" color="text.secondary">
            Times are entered in your local timezone and stored as UTC. While a window is active, matching
            devices do not raise alerts (and optionally no notifications are delivered).
          </Typography>
        }
        submitLabel={editing ? "Save changes" : "Create window"}
        loading={saveMutation.isPending}
        error={formError}
        onSubmit={submit}
        onClose={() => {
          setDialogOpen(false);
          setEditing(null);
        }}
        maxWidth="md"
      >
        <TextField
          label="Name"
          value={form.name}
          onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
          required
          autoFocus
          helperText="For example: Core switch upgrade, Q4 change window"
        />
        <TextField
          label="Description"
          value={form.description}
          onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))}
          multiline
          minRows={2}
          helperText="Optional context stored with the window and shown in the list"
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Starts at"
            type="datetime-local"
            value={form.starts_at}
            onChange={(event) => setForm((value) => ({ ...value, starts_at: event.target.value }))}
            InputLabelProps={{ shrink: true }}
            required
          />
          <TextField
            label="Ends at"
            type="datetime-local"
            value={form.ends_at}
            onChange={(event) => setForm((value) => ({ ...value, ends_at: event.target.value }))}
            InputLabelProps={{ shrink: true }}
            required
          />
        </Stack>
        <TextField
          select
          label="Target"
          value={form.target_type}
          onChange={(event) =>
            setForm((value) => ({
              ...value,
              target_type: event.target.value as MaintenanceTarget,
              target_ids: [],
            }))
          }
        >
          {TARGETS.map((target) => (
            <MenuItem key={target} value={target}>
              {MAINTENANCE_TARGET_LABELS[target] ?? target}
            </MenuItem>
          ))}
        </TextField>
        {form.target_type !== "fleet" && (
          <TextField
            select
            label={`${MAINTENANCE_TARGET_LABELS[form.target_type]} to silence`}
            value={form.target_ids}
            onChange={(event) => {
              const value = event.target.value;
              setForm((state) => ({
                ...state,
                target_ids: Array.isArray(value) ? value : [value],
              }));
            }}
            SelectProps={{ multiple: true }}
            helperText="Several targets can be selected. Empty selection is rejected by the API."
          >
            {targetOptions.map((option) => (
              <MenuItem key={option.id} value={option.id}>
                {option.name}
              </MenuItem>
            ))}
          </TextField>
        )}
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <FormControlLabel
            control={
              <Checkbox
                checked={form.silence_alerts}
                onChange={(event) =>
                  setForm((value) => ({ ...value, silence_alerts: event.target.checked }))
                }
              />
            }
            label="Suppress alert creation"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={form.silence_notifications}
                onChange={(event) =>
                  setForm((value) => ({ ...value, silence_notifications: event.target.checked }))
                }
              />
            }
            label="Suppress notifications"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={form.enabled}
                onChange={(event) => setForm((value) => ({ ...value, enabled: event.target.checked }))}
              />
            }
            label="Enabled"
          />
        </Stack>
        {!form.silence_alerts && form.silence_notifications && (
          <Alert severity="info">
            Alerts are still created but notifications are muted. Use this when you want the incident
            recorded without paging anyone.
          </Alert>
        )}
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete maintenance window"
        description={
          deleteTarget
            ? `Delete "${deleteTarget.name}"? Alerts resume immediately for its targets; the deletion is audited.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
      />
    </>
  );
}

export default MaintenancePage;
