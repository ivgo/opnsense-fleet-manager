import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import BoltOutlinedIcon from "@mui/icons-material/BoltOutlined";
import CloudDownloadOutlinedIcon from "@mui/icons-material/CloudDownloadOutlined";
import CloudUploadOutlinedIcon from "@mui/icons-material/CloudUploadOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import PauseCircleOutlineIcon from "@mui/icons-material/PauseCircleOutline";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import RadarOutlinedIcon from "@mui/icons-material/RadarOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { bulkApi, devicesApi, groupsApi, sitesApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type {
  BulkAction,
  BulkDeviceResponse,
  CsvImportResult,
  Device,
  DeviceCreate,
  DeviceGroup,
  DeviceStatus,
  DeviceSummary,
  DeviceUpdate,
  DiscoveryResult,
  Site,
} from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useDebounce } from "@/hooks/useDebounce";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE, BULK_ACTION_LABELS, BULK_COMMAND_ACTIONS, DEVICE_STATUS_LABELS } from "@/utils/constants";
import { downloadBlob, formatDateTime, fromNow, parseLines } from "@/utils/format";

interface DeviceFormState {
  name: string;
  hostname: string;
  description: string;
  ip_address: string;
  api_port: string;
  site_id: string;
  group_id: string;
  serial_number: string;
  model: string;
  is_ha: boolean;
  ha_role: string;
  tags: string;
  api_key: string;
  api_secret: string;
  status: DeviceStatus;
}

const EMPTY_FORM: DeviceFormState = {
  name: "",
  hostname: "",
  description: "",
  ip_address: "",
  api_port: "443",
  site_id: "",
  group_id: "",
  serial_number: "",
  model: "",
  is_ha: false,
  ha_role: "",
  tags: "",
  api_key: "",
  api_secret: "",
  status: "registered",
};

const BULK_DESCRIPTIONS: Record<BulkAction, string> = {
  maintenance_on:
    "Creates one maintenance window covering the selected devices, starting now. Alerts and notifications are silenced for its duration.",
  maintenance_off:
    "Ends every active maintenance window that covers the selected devices. Alerts resume immediately.",
  command:
    "Queues an agent command on each selected device. Only actions supported by the os-fleet-agent are listed.",
  backup: "Queues a signed configuration backup for every selected device.",
  firmware_upgrade:
    "Queues a firmware upgrade job. The worker upgrades devices one by one and reports failures per device.",
  reboot:
    "Queues a reboot job. Devices drop their tunnels and return once the agent reconnects.",
};

const BULK_CONFIRM_ACTIONS: BulkAction[] = ["maintenance_off", "reboot", "firmware_upgrade"];

export function DevicesPage() {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [sort, setSort] = useState("name");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [siteFilter, setSiteFilter] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);

  const [formOpen, setFormOpen] = useState(params.get("new") === "1");
  const [editing, setEditing] = useState<Device | null>(null);
  const [form, setForm] = useState<DeviceFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Device | null>(null);

  const [discoverOpen, setDiscoverOpen] = useState(false);
  const [discoverCidr, setDiscoverCidr] = useState("192.168.1.0/24");
  const [discoverPort, setDiscoverPort] = useState("443");
  const [discoverResults, setDiscoverResults] = useState<DiscoveryResult[]>([]);
  const [discoverError, setDiscoverError] = useState<string | null>(null);

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkAction, setBulkAction] = useState<BulkAction | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkDeviceResponse | null>(null);
  const [bulkForm, setBulkForm] = useState({
    command: BULK_COMMAND_ACTIONS[0].value as string,
    payload: "",
    duration_minutes: "60",
    name: "",
    package: "",
  });
  const [csvResult, setCsvResult] = useState<CsvImportResult | null>(null);
  const [csvError, setCsvError] = useState<string | null>(null);
  const csvInputRef = useRef<HTMLInputElement>(null);

  const listParams = useMemo(
    () => ({
      page,
      size,
      sort,
      order,
      search: debouncedSearch || undefined,
      status: statusFilter || undefined,
      site_id: siteFilter || undefined,
      group_id: groupFilter || undefined,
    }),
    [page, size, sort, order, debouncedSearch, statusFilter, siteFilter, groupFilter],
  );

  const devicesQuery = useQuery({
    queryKey: qk.devices.list(listParams),
    queryFn: () => devicesApi.list(listParams),
    refetchInterval: 30_000,
  });

  const summaryQuery = useQuery({
    queryKey: qk.devices.summary,
    queryFn: () => devicesApi.summary(),
    staleTime: 30_000,
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

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, statusFilter, siteFilter, groupFilter]);

  const siteName = (id: string | null) =>
    id ? sitesQuery.data?.items.find((site: Site) => site.id === id)?.name ?? "—" : "—";
  const groupName = (id: string | null) =>
    id ? groupsQuery.data?.items.find((group: DeviceGroup) => group.id === id)?.name ?? "—" : "—";

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.devices.all });
    void queryClient.invalidateQueries({ queryKey: qk.sites.all });
    void queryClient.invalidateQueries({ queryKey: qk.groups.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      const base: DeviceCreate = {
        name: form.name.trim(),
        hostname: form.hostname.trim() || null,
        description: form.description.trim() || null,
        ip_address: form.ip_address.trim() || null,
        api_port: Number(form.api_port) || 443,
        site_id: form.site_id || null,
        group_id: form.group_id || null,
        serial_number: form.serial_number.trim() || null,
        model: form.model.trim() || null,
        is_ha: form.is_ha,
        ha_role: form.ha_role || null,
        tags: parseLines(form.tags),
      };
      if (form.api_key.trim()) base.api_key = form.api_key.trim();
      if (form.api_secret.trim()) base.api_secret = form.api_secret.trim();

      if (editing) {
        const update: DeviceUpdate = {
          name: base.name,
          hostname: base.hostname,
          description: base.description,
          ip_address: base.ip_address,
          api_port: base.api_port,
          site_id: base.site_id,
          group_id: base.group_id,
          is_ha: base.is_ha,
          ha_role: base.ha_role,
          tags: base.tags,
          status: form.status,
        };
        if (base.api_key) update.api_key = base.api_key;
        if (base.api_secret) update.api_secret = base.api_secret;
        return devicesApi.update(editing.id, update);
      }
      return devicesApi.create(base);
    },
    onSuccess: (device) => {
      invalidate();
      setFormOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(
        showToast({ message: `Device ${device.name} ${editing ? "updated" : "registered"}`, severity: "success" }),
      );
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => devicesApi.remove(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Device deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const maintenanceMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => devicesApi.maintenance(id, enabled),
    onSuccess: (device) => {
      invalidate();
      dispatch(
        showToast({
          message: `${device.name} ${device.status === "maintenance" ? "entered" : "left"} maintenance mode`,
          severity: "success",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const discoverMutation = useMutation({
    mutationFn: () =>
      devicesApi.discover({
        cidr: discoverCidr.trim(),
        port: Number(discoverPort) || 443,
        timeout: 2,
      }),
    onSuccess: (results) => {
      setDiscoverResults(results);
      setDiscoverError(null);
    },
    onError: (error) => setDiscoverError(toApiError(error).message),
  });

  const bulkMutation = useMutation({
    mutationFn: (action: BulkAction) => {
      const params: Record<string, unknown> = {};
      if (action === "command") {
        params.action = bulkForm.command;
        if (bulkForm.payload.trim()) params.payload = JSON.parse(bulkForm.payload);
      }
      if (action === "maintenance_on") {
        params.duration_minutes = Number(bulkForm.duration_minutes) || 60;
        if (bulkForm.name.trim()) params.name = bulkForm.name.trim();
      }
      if (action === "firmware_upgrade" && bulkForm.package.trim()) {
        params.package = bulkForm.package.trim();
      }
      return bulkApi.devices({ action, device_ids: selectedIds, params });
    },
    onSuccess: (response) => {
      invalidate();
      setBulkAction(null);
      setBulkError(null);
      setSelectedIds([]);
      setBulkResult(response);
      dispatch(
        showToast({
          message: `${BULK_ACTION_LABELS[response.action] ?? response.action}: ${response.succeeded} of ${response.total} devices succeeded`,
          severity: response.failed > 0 ? "warning" : "success",
        }),
      );
    },
    onError: (error) => setBulkError(toApiError(error).message),
  });

  const importMutation = useMutation({
    mutationFn: (file: File) => bulkApi.importCsv(file),
    onSuccess: (result) => {
      invalidate();
      setCsvError(null);
      setCsvResult(result);
      dispatch(
        showToast({
          message: `CSV import: ${result.created} created, ${result.skipped} skipped`,
          severity: result.errors.length > 0 ? "warning" : "success",
        }),
      );
    },
    onError: (error) => {
      setCsvResult(null);
      setCsvError(toApiError(error).message);
    },
  });

  const exportMutation = useMutation({
    mutationFn: () => bulkApi.exportCsv(),
    onSuccess: (blob) => {
      downloadBlob(blob, `ofme-devices-${new Date().toISOString().slice(0, 10)}.csv`);
      dispatch(showToast({ message: "Device inventory exported", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openBulk = (action: BulkAction) => {
    setBulkError(null);
    setBulkAction(action);
  };

  const submitBulk = () => {
    if (!bulkAction) return;
    if (bulkAction === "command" && bulkForm.payload.trim()) {
      try {
        JSON.parse(bulkForm.payload);
      } catch {
        setBulkError("The command payload must be valid JSON.");
        return;
      }
    }
    if (bulkAction === "maintenance_on") {
      const minutes = Number(bulkForm.duration_minutes);
      if (!Number.isInteger(minutes) || minutes < 1 || minutes > 10080) {
        setBulkError("The maintenance duration must be between 1 and 10080 minutes (7 days).");
        return;
      }
    }
    setBulkError(null);
    bulkMutation.mutate(bulkAction);
  };

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = (device: Device) => {
    setEditing(device);
    setForm({
      name: device.name,
      hostname: device.hostname ?? "",
      description: device.description ?? "",
      ip_address: device.ip_address ?? "",
      api_port: String(device.api_port),
      site_id: device.site_id ?? "",
      group_id: device.group_id ?? "",
      serial_number: device.serial_number ?? "",
      model: device.model ?? "",
      is_ha: device.is_ha,
      ha_role: device.ha_role ?? "",
      tags: device.tags.join(", "),
      api_key: "",
      api_secret: "",
      status: device.status,
    });
    setFormError(null);
    setFormOpen(true);
  };

  const summary: DeviceSummary | undefined = summaryQuery.data;

  const columns: Array<DataTableColumn<Device>> = [
    {
      key: "name",
      label: "Device",
      sortable: true,
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.name}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {row.hostname ?? row.serial_number ?? row.id.slice(0, 8)}
          </Typography>
        </Box>
      ),
    },
    { key: "status", label: "Status", width: 120, render: (row) => <StatusChip status={row.status} /> },
    {
      key: "connection_status",
      label: "Agent",
      width: 130,
      hideBelow: "md",
      render: (row) => <StatusChip status={row.connection_status} />,
    },
    {
      key: "ip_address",
      label: "Management IP",
      width: 170,
      hideBelow: "sm",
      monospace: true,
      render: (row) => (row.ip_address ? `${row.ip_address}:${row.api_port}` : "—"),
    },
    { key: "site", label: "Site", width: 150, hideBelow: "md", render: (row) => siteName(row.site_id) },
    { key: "group", label: "Group", width: 150, hideBelow: "lg", render: (row) => groupName(row.group_id) },
    {
      key: "firmware",
      label: "Firmware",
      width: 120,
      hideBelow: "lg",
      render: (row) => row.firmware_version ?? "—",
    },
    {
      key: "last_seen",
      label: "Last seen",
      width: 140,
      hideBelow: "lg",
      render: (row) => (
        <Tooltip title={row.last_seen_at ? formatDateTime(row.last_seen_at) : "Never"}>
          <span>{row.last_seen_at ? fromNow(row.last_seen_at) : "Never"}</span>
        </Tooltip>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 130,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="device:write">
            <Tooltip title={row.status === "maintenance" ? "Leave maintenance" : "Enter maintenance"}>
              <IconButton
                size="small"
                disabled={maintenanceMutation.isPending}
                onClick={(event) => {
                  event.stopPropagation();
                  maintenanceMutation.mutate({ id: row.id, enabled: row.status !== "maintenance" });
                }}
              >
                {row.status === "maintenance" ? (
                  <PlayCircleOutlineIcon fontSize="small" />
                ) : (
                  <PauseCircleOutlineIcon fontSize="small" />
                )}
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="device:write">
            <Tooltip title="Edit">
              <IconButton
                size="small"
                onClick={(event) => {
                  event.stopPropagation();
                  openEdit(row);
                }}
              >
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="device:delete">
            <Tooltip title="Delete">
              <IconButton
                size="small"
                color="error"
                onClick={(event) => {
                  event.stopPropagation();
                  setDeleteTarget(row);
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
        title="Devices"
        subtitle="Every OPNsense appliance managed by this tenant, its agent state and management endpoint."
        actions={
          <>
            <PermissionGate permission="device:read">
              <Button
                variant="outlined"
                startIcon={<CloudDownloadOutlinedIcon />}
                onClick={() => exportMutation.mutate()}
                disabled={exportMutation.isPending}
              >
                Export CSV
              </Button>
            </PermissionGate>
            <PermissionGate permission="device:write">
              <Button
                variant="outlined"
                startIcon={<CloudUploadOutlinedIcon />}
                onClick={() => csvInputRef.current?.click()}
                disabled={importMutation.isPending}
              >
                Import CSV
              </Button>
            </PermissionGate>
            <PermissionGate permission="device:write">
              <Button variant="outlined" startIcon={<RadarOutlinedIcon />} onClick={() => setDiscoverOpen(true)}>
                Discover
              </Button>
            </PermissionGate>
            <PermissionGate permission="device:write">
              <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
                Register device
              </Button>
            </PermissionGate>
          </>
        }
        meta={
          summary && (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
              <Chip size="small" label={`${summary.total} total`} />
              <Chip size="small" color="success" variant="outlined" label={`${summary.online} online`} />
              <Chip size="small" color="error" variant="outlined" label={`${summary.offline} offline`} />
              <Chip size="small" color="warning" variant="outlined" label={`${summary.error} error`} />
              <Chip size="small" variant="outlined" label={`${summary.maintenance} maintenance`} />
              <Chip size="small" variant="outlined" label={`${summary.unregistered} unregistered`} />
            </Stack>
          )
        }
      />

      {selectedIds.length > 0 && (
        <Paper
          variant="outlined"
          sx={{ p: 1.25, mb: 2, borderColor: "primary.main", bgcolor: "action.hover" }}
        >
          <Stack
            direction={{ xs: "column", md: "row" }}
            spacing={1}
            alignItems={{ xs: "stretch", md: "center" }}
            justifyContent="space-between"
          >
            <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
              <Chip color="primary" size="small" label={`${selectedIds.length} selected`} />
              <Typography variant="caption" color="text.secondary">
                Bulk actions run once per device and are recorded in the audit trail.
              </Typography>
            </Stack>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <PermissionGate permission="device:exec">
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<BoltOutlinedIcon />}
                  onClick={() => openBulk("command")}
                >
                  Run command
                </Button>
                <Button size="small" variant="outlined" onClick={() => openBulk("maintenance_on")}>
                  Maintenance on
                </Button>
                <Button size="small" variant="outlined" onClick={() => openBulk("maintenance_off")}>
                  Maintenance off
                </Button>
                <Button size="small" variant="outlined" onClick={() => openBulk("backup")}>
                  Back up
                </Button>
                <Button size="small" variant="outlined" onClick={() => openBulk("reboot")}>
                  Reboot
                </Button>
                <Button size="small" variant="outlined" onClick={() => openBulk("firmware_upgrade")}>
                  Upgrade firmware
                </Button>
              </PermissionGate>
              <Button size="small" color="inherit" onClick={() => setSelectedIds([])}>
                Clear
              </Button>
            </Stack>
          </Stack>
        </Paper>
      )}

      <input
        ref={csvInputRef}
        type="file"
        accept=".csv,text/csv"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) importMutation.mutate(file);
        }}
      />

      <DataTable
        columns={columns}
        rows={devicesQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={devicesQuery.isLoading}
        error={devicesQuery.error ? toApiError(devicesQuery.error).message : null}
        onRetry={() => devicesQuery.refetch()}
        page={page}
        size={size}
        total={devicesQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        sort={sort}
        order={order}
        onSortChange={(key, nextOrder) => {
          setSort(key);
          setOrder(nextOrder);
        }}
        onRowClick={(row) => navigate(`/devices/${row.id}`)}
        selection={{ selectedIds, onChange: setSelectedIds }}
        emptyTitle="No devices match the filters"
        emptyDescription="Register a device manually or run a subnet discovery to enroll appliances."
        emptyAction={
          <PermissionGate permission="device:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              Register device
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack
            direction={{ xs: "column", lg: "row" }}
            spacing={1}
            alignItems={{ xs: "stretch", lg: "center" }}
            justifyContent="space-between"
          >
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap>
              <TextField
                placeholder="Search name, host, IP or serial"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                sx={{ width: { xs: "100%", sm: 260 } }}
              />
              <TextField
                select
                label="Status"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 150 } }}
              >
                <MenuItem value="">All</MenuItem>
                {Object.entries(DEVICE_STATUS_LABELS).map(([value, label]) => (
                  <MenuItem key={value} value={value}>
                    {label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Site"
                value={siteFilter}
                onChange={(event) => setSiteFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 170 } }}
              >
                <MenuItem value="">All sites</MenuItem>
                {(sitesQuery.data?.items ?? []).map((site) => (
                  <MenuItem key={site.id} value={site.id}>
                    {site.name}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Group"
                value={groupFilter}
                onChange={(event) => setGroupFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 170 } }}
              >
                <MenuItem value="">All groups</MenuItem>
                {(groupsQuery.data?.items ?? []).map((group) => (
                  <MenuItem key={group.id} value={group.id}>
                    {group.name}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              {devicesQuery.data?.meta.total ?? 0} devices
            </Typography>
          </Stack>
        }
      />

      <FormDialog
        open={formOpen}
        title={editing ? `Edit ${editing.name}` : "Register device"}
        description={
          <Typography variant="body2" color="text.secondary">
            {editing
              ? "Update inventory metadata and the management endpoint. Credentials are only sent when provided."
              : "Register an appliance that already runs the os-fleet-agent plugin. The API key is optional; the agent can enroll with a certificate instead."}
          </Typography>
        }
        submitLabel={editing ? "Save changes" : "Register"}
        loading={saveMutation.isPending}
        error={formError}
        submitDisabled={!form.name.trim()}
        onSubmit={() => saveMutation.mutate()}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Name"
            value={form.name}
            onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
            required
            autoFocus
          />
          <TextField
            label="Hostname"
            value={form.hostname}
            onChange={(event) => setForm((value) => ({ ...value, hostname: event.target.value }))}
          />
        </Stack>
        <TextField
          label="Description"
          value={form.description}
          onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))}
          multiline
          minRows={2}
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Management IP"
            value={form.ip_address}
            onChange={(event) => setForm((value) => ({ ...value, ip_address: event.target.value }))}
            placeholder="10.0.0.1"
          />
          <TextField
            label="API port"
            type="number"
            value={form.api_port}
            onChange={(event) => setForm((value) => ({ ...value, api_port: event.target.value }))}
            sx={{ maxWidth: { sm: 140 } }}
            inputProps={{ min: 1, max: 65535 }}
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Site"
            value={form.site_id}
            onChange={(event) => setForm((value) => ({ ...value, site_id: event.target.value }))}
          >
            <MenuItem value="">Unassigned</MenuItem>
            {(sitesQuery.data?.items ?? []).map((site) => (
              <MenuItem key={site.id} value={site.id}>
                {site.name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Group"
            value={form.group_id}
            onChange={(event) => setForm((value) => ({ ...value, group_id: event.target.value }))}
          >
            <MenuItem value="">Unassigned</MenuItem>
            {(groupsQuery.data?.items ?? []).map((group) => (
              <MenuItem key={group.id} value={group.id}>
                {group.name}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Serial number"
            value={form.serial_number}
            onChange={(event) => setForm((value) => ({ ...value, serial_number: event.target.value }))}
            disabled={Boolean(editing)}
          />
          <TextField
            label="Model"
            value={form.model}
            onChange={(event) => setForm((value) => ({ ...value, model: event.target.value }))}
            disabled={Boolean(editing)}
          />
        </Stack>
        {editing && (
          <TextField
            select
            label="Status"
            value={form.status}
            onChange={(event) =>
              setForm((value) => ({ ...value, status: event.target.value as DeviceStatus }))
            }
            helperText="Status is normally driven by heartbeats. Manual override is audited."
          >
            {Object.entries(DEVICE_STATUS_LABELS).map(([value, label]) => (
              <MenuItem key={value} value={value}>
                {label}
              </MenuItem>
            ))}
          </TextField>
        )}
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems="center">
          <FormControlLabel
            control={
              <Checkbox
                checked={form.is_ha}
                onChange={(event) => setForm((value) => ({ ...value, is_ha: event.target.checked }))}
              />
            }
            label="High availability pair"
          />
          {form.is_ha && (
            <TextField
              select
              label="HA role"
              value={form.ha_role}
              onChange={(event) => setForm((value) => ({ ...value, ha_role: event.target.value }))}
              sx={{ maxWidth: 220 }}
            >
              <MenuItem value="">Unspecified</MenuItem>
              <MenuItem value="primary">Primary</MenuItem>
              <MenuItem value="secondary">Secondary</MenuItem>
            </TextField>
          )}
        </Stack>
        <TextField
          label="Tags"
          value={form.tags}
          onChange={(event) => setForm((value) => ({ ...value, tags: event.target.value }))}
          helperText="Comma-separated labels, for example branch, eu-west, pci"
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="API key"
            value={form.api_key}
            onChange={(event) => setForm((value) => ({ ...value, api_key: event.target.value }))}
            type="password"
            autoComplete="new-password"
            helperText={editing ? "Leave blank to keep the stored key" : "Optional"}
          />
          <TextField
            label="API secret"
            value={form.api_secret}
            onChange={(event) => setForm((value) => ({ ...value, api_secret: event.target.value }))}
            type="password"
            autoComplete="new-password"
            helperText={editing ? "Leave blank to keep the stored secret" : "Optional"}
          />
        </Stack>
      </FormDialog>

      <FormDialog
        open={discoverOpen}
        title="Discover OPNsense appliances"
        description={
          <Typography variant="body2" color="text.secondary">
            Probes a CIDR range for the OPNsense web interface. Discovery never stores credentials and is
            limited to the requested range.
          </Typography>
        }
        submitLabel="Run discovery"
        loading={discoverMutation.isPending}
        error={discoverError}
        onSubmit={() => discoverMutation.mutate()}
        onClose={() => setDiscoverOpen(false)}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="CIDR range"
            value={discoverCidr}
            onChange={(event) => setDiscoverCidr(event.target.value)}
            placeholder="192.168.1.0/24"
            required
          />
          <TextField
            label="API port"
            type="number"
            value={discoverPort}
            onChange={(event) => setDiscoverPort(event.target.value)}
            sx={{ maxWidth: { sm: 140 } }}
          />
        </Stack>
        {discoverResults.length > 0 && (
          <Stack spacing={1}>
            <Typography variant="subtitle2">{discoverResults.length} candidate host(s)</Typography>
            {discoverResults.map((result) => (
              <Stack
                key={`${result.ip_address}:${result.port}`}
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                sx={{ p: 1.25, border: 1, borderColor: "divider", borderRadius: 1.5 }}
              >
                <Box>
                  <Typography variant="body2" fontWeight={600}>
                    {result.ip_address}:{result.port}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {result.hostname ?? "unknown host"} · {result.firmware_version ?? "firmware unknown"}
                  </Typography>
                </Box>
                <Stack direction="row" spacing={1} alignItems="center">
                  {result.already_managed && <Chip size="small" label="Managed" />}
                  <StatusChip status={result.reachable ? "online" : "offline"} />
                </Stack>
              </Stack>
            ))}
          </Stack>
        )}
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete device"
        description={
          deleteTarget
            ? `Delete ${deleteTarget.name}? Backups, policies and the audit trail are retained, but the device is removed from inventory and stops receiving configuration.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onClose={() => setDeleteTarget(null)}
      />

      <FormDialog
        open={Boolean(bulkAction)}
        title={
          bulkAction
            ? `${BULK_ACTION_LABELS[bulkAction] ?? bulkAction} — ${selectedIds.length} device(s)`
            : "Bulk action"
        }
        description={
          bulkAction ? (
            <Typography variant="body2" color="text.secondary">
              {BULK_DESCRIPTIONS[bulkAction]}
            </Typography>
          ) : undefined
        }
        submitLabel={bulkAction ? BULK_ACTION_LABELS[bulkAction] ?? "Run" : "Run"}
        loading={bulkMutation.isPending}
        error={bulkError}
        submitDisabled={selectedIds.length === 0}
        onSubmit={submitBulk}
        onClose={() => {
          setBulkAction(null);
          setBulkError(null);
        }}
        maxWidth="sm"
      >
        {bulkAction === "command" && (
          <>
            <TextField
              select
              label="Agent command"
              value={bulkForm.command}
              onChange={(event) => setBulkForm((value) => ({ ...value, command: event.target.value }))}
              helperText="Firmware actions are available through the dedicated bulk actions instead."
            >
              {BULK_COMMAND_ACTIONS.map((action) => (
                <MenuItem key={action.value} value={action.value}>
                  {action.label}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Command payload (JSON)"
              value={bulkForm.payload}
              onChange={(event) => setBulkForm((value) => ({ ...value, payload: event.target.value }))}
              multiline
              minRows={2}
              placeholder='{"interface": "wan"}'
              helperText="Optional. Must be a JSON object; leave empty to send no payload."
            />
          </>
        )}

        {bulkAction === "maintenance_on" && (
          <>
            <TextField
              label="Duration (minutes)"
              type="number"
              value={bulkForm.duration_minutes}
              onChange={(event) =>
                setBulkForm((value) => ({ ...value, duration_minutes: event.target.value }))
              }
              inputProps={{ min: 1, max: 10080 }}
              helperText="Between 1 minute and 7 days. Defaults to 60 minutes."
            />
            <TextField
              label="Window name"
              value={bulkForm.name}
              onChange={(event) => setBulkForm((value) => ({ ...value, name: event.target.value }))}
              helperText="Optional. A timestamped name is generated when left blank."
            />
          </>
        )}

        {bulkAction === "firmware_upgrade" && (
          <TextField
            label="Firmware package"
            value={bulkForm.package}
            onChange={(event) => setBulkForm((value) => ({ ...value, package: event.target.value }))}
            helperText="Optional. Leave blank to let the worker pick the latest available package."
          />
        )}

        {bulkAction && BULK_CONFIRM_ACTIONS.includes(bulkAction) && (
          <Alert severity={bulkAction === "maintenance_off" ? "info" : "warning"}>
            {bulkAction === "maintenance_off"
              ? "Ending maintenance early may raise alerts for conditions that are still present."
              : "This action changes device state. Confirm that the selected devices are the intended targets."}
          </Alert>
        )}
      </FormDialog>

      <FormDialog
        open={Boolean(bulkResult)}
        title="Bulk action results"
        description={
          bulkResult ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip size="small" label={`${bulkResult.total} devices`} />
              <Chip size="small" color="success" variant="outlined" label={`${bulkResult.succeeded} succeeded`} />
              <Chip
                size="small"
                color={bulkResult.failed > 0 ? "error" : "default"}
                variant="outlined"
                label={`${bulkResult.failed} failed`}
              />
            </Stack>
          ) : undefined
        }
        submitLabel="Close"
        onSubmit={() => setBulkResult(null)}
        onClose={() => setBulkResult(null)}
        maxWidth="md"
      >
        <Stack spacing={1} sx={{ maxHeight: 380, overflowY: "auto" }}>
          {bulkResult?.results.map((result) => (
            <Stack
              key={result.device_id}
              direction="row"
              justifyContent="space-between"
              alignItems="center"
              spacing={1}
              sx={{ p: 1, border: 1, borderColor: "divider", borderRadius: 1.5 }}
            >
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body2" fontWeight={600} noWrap>
                  {result.name}
                </Typography>
                {result.message && (
                  <Typography variant="caption" color="text.secondary">
                    {result.message}
                  </Typography>
                )}
              </Box>
              <StatusChip status={result.status} />
            </Stack>
          ))}
        </Stack>
      </FormDialog>

      <FormDialog
        open={Boolean(csvResult) || Boolean(csvError)}
        title="CSV import"
        description={
          <Typography variant="body2" color="text.secondary">
            Devices are matched by name. Existing devices are skipped; unknown site names are reported per row.
          </Typography>
        }
        submitLabel="Close"
        onSubmit={() => {
          setCsvResult(null);
          setCsvError(null);
        }}
        onClose={() => {
          setCsvResult(null);
          setCsvError(null);
        }}
        maxWidth="md"
      >
        {csvError && <Alert severity="error">{csvError}</Alert>}
        {csvResult && (
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip size="small" color="success" variant="outlined" label={`${csvResult.created} created`} />
              <Chip size="small" variant="outlined" label={`${csvResult.skipped} skipped`} />
              {csvResult.errors.length > 0 && (
                <Chip
                  size="small"
                  color="error"
                  variant="outlined"
                  label={`${csvResult.errors.length} row error(s)`}
                />
              )}
            </Stack>
            {csvResult.errors.length > 0 && (
              <Stack spacing={0.5} sx={{ maxHeight: 280, overflowY: "auto" }}>
                {csvResult.errors.map((error, index) => (
                  <Typography key={`${error.row}-${index}`} variant="caption" color="error">
                    Row {error.row}: {error.error}
                  </Typography>
                ))}
              </Stack>
            )}
          </Stack>
        )}
      </FormDialog>
    </>
  );
}

export default DevicesPage;
