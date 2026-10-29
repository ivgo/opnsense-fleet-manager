import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
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
import PauseCircleOutlineIcon from "@mui/icons-material/PauseCircleOutline";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import RadarOutlinedIcon from "@mui/icons-material/RadarOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { devicesApi, groupsApi, sitesApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type {
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
import { DEFAULT_PAGE_SIZE, DEVICE_STATUS_LABELS } from "@/utils/constants";
import { formatDateTime, fromNow, parseLines } from "@/utils/format";

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
    </>
  );
}

export default DevicesPage;
