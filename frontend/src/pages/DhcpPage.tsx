import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  IconButton,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import LanOutlinedIcon from "@mui/icons-material/LanOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { devicesApi, dhcpApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type {
  DhcpReservation,
  DhcpReservationPayload,
  DhcpScope,
  DhcpScopePayload,
} from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import { useDebounce } from "@/hooks/useDebounce";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { EMPTY, formatDuration, formatNumber } from "@/utils/format";

interface ScopeFormState {
  device_id: string;
  name: string;
  description: string;
  subnet: string;
  pool_start: string;
  pool_end: string;
  gateway: string;
  dns_servers: string;
  domain_name: string;
  lease_time_seconds: string;
  enabled: boolean;
}

interface ReservationFormState {
  scope_id: string;
  hostname: string;
  mac_address: string;
  ip_address: string;
  description: string;
  enabled: boolean;
}

const EMPTY_SCOPE: ScopeFormState = {
  device_id: "",
  name: "",
  description: "",
  subnet: "",
  pool_start: "",
  pool_end: "",
  gateway: "",
  dns_servers: "",
  domain_name: "",
  lease_time_seconds: "86400",
  enabled: true,
};

const EMPTY_RESERVATION: ReservationFormState = {
  scope_id: "",
  hostname: "",
  mac_address: "",
  ip_address: "",
  description: "",
  enabled: true,
};

function optionalInteger(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
}

export function DhcpPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState(0);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);
  const [deviceFilter, setDeviceFilter] = useState("");
  const [scopeFilter, setScopeFilter] = useState("");
  const [scopeSort, setScopeSort] = useState("name");
  const [scopeOrder, setScopeOrder] = useState<"asc" | "desc">("asc");
  const [reservationSort, setReservationSort] = useState("hostname");
  const [reservationOrder, setReservationOrder] = useState<"asc" | "desc">("asc");

  const [scopeDialogOpen, setScopeDialogOpen] = useState(false);
  const [editingScope, setEditingScope] = useState<DhcpScope | null>(null);
  const [scopeForm, setScopeForm] = useState<ScopeFormState>(EMPTY_SCOPE);
  const [scopeError, setScopeError] = useState<string | null>(null);
  const [scopeDelete, setScopeDelete] = useState<DhcpScope | null>(null);

  const [reservationDialogOpen, setReservationDialogOpen] = useState(false);
  const [editingReservation, setEditingReservation] = useState<DhcpReservation | null>(null);
  const [reservationForm, setReservationForm] = useState<ReservationFormState>(EMPTY_RESERVATION);
  const [reservationError, setReservationError] = useState<string | null>(null);
  const [reservationDelete, setReservationDelete] = useState<DhcpReservation | null>(null);

  const [applyOpen, setApplyOpen] = useState(false);
  const [dryRun, setDryRun] = useState(false);

  const devicesQuery = useQuery({
    queryKey: qk.devices.list({ size: 200, sort: "name", order: "asc" }),
    queryFn: () => devicesApi.list({ size: 200, sort: "name", order: "asc" }),
    staleTime: 60_000,
  });

  const scopesQuery = useQuery({
    queryKey: qk.dhcp.scopes({
      page,
      size,
      search: debouncedSearch || undefined,
      device_id: deviceFilter || undefined,
      sort: scopeSort,
      order: scopeOrder,
      tab,
    }),
    queryFn: () =>
      dhcpApi.scopes({
        page,
        size,
        sort: scopeSort,
        order: scopeOrder,
        search: debouncedSearch || undefined,
        device_id: deviceFilter || undefined,
      }),
  });

  const scopeOptionsQuery = useQuery({
    queryKey: qk.dhcp.scopes({ size: 500, sort: "name", order: "asc", options: true }),
    queryFn: () => dhcpApi.scopes({ size: 500, sort: "name", order: "asc" }),
    staleTime: 30_000,
  });

  const reservationsQuery = useQuery({
    queryKey: qk.dhcp.reservations({
      page,
      size,
      search: debouncedSearch || undefined,
      scope_id: scopeFilter || undefined,
      device_id: deviceFilter || undefined,
      sort: reservationSort,
      order: reservationOrder,
      tab,
    }),
    queryFn: () =>
      dhcpApi.reservations({
        page,
        size,
        sort: reservationSort,
        order: reservationOrder,
        search: debouncedSearch || undefined,
        scope_id: scopeFilter || undefined,
        device_id: deviceFilter || undefined,
      }),
  });

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, deviceFilter, scopeFilter, tab]);

  useEffect(() => {
    setSearch("");
    setPage(1);
  }, [tab]);

  const devices = useMemo(() => devicesQuery.data?.items ?? [], [devicesQuery.data]);
  const scopeOptions = useMemo(
    () => scopeOptionsQuery.data?.items ?? [],
    [scopeOptionsQuery.data],
  );
  const deviceName = useMemo(() => {
    const map = new Map(devices.map((device) => [device.id, device.name]));
    return (id: string) => map.get(id) ?? id;
  }, [devices]);
  const scopeName = useMemo(() => {
    const map = new Map(scopeOptions.map((scope) => [scope.id, `${scope.name} (${scope.subnet})`]));
    return (id: string) => map.get(id) ?? id;
  }, [scopeOptions]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.dhcp.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const saveScope = useMutation({
    mutationFn: () => {
      const payload: DhcpScopePayload = {
        device_id: scopeForm.device_id,
        name: scopeForm.name.trim(),
        description: scopeForm.description.trim() || null,
        subnet: scopeForm.subnet.trim(),
        pool_start: scopeForm.pool_start.trim(),
        pool_end: scopeForm.pool_end.trim(),
        gateway: scopeForm.gateway.trim() || null,
        dns_servers: scopeForm.dns_servers
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        domain_name: scopeForm.domain_name.trim() || null,
        lease_time_seconds: optionalInteger(scopeForm.lease_time_seconds) ?? 86_400,
        enabled: scopeForm.enabled,
      };
      if (editingScope) {
        return dhcpApi.updateScope(editingScope.id, {
          description: payload.description,
          pool_start: payload.pool_start,
          pool_end: payload.pool_end,
          gateway: payload.gateway,
          dns_servers: payload.dns_servers,
          domain_name: payload.domain_name,
          lease_time_seconds: payload.lease_time_seconds,
          enabled: payload.enabled,
        });
      }
      return dhcpApi.createScope(payload);
    },
    onSuccess: (scope) => {
      invalidate();
      setScopeDialogOpen(false);
      setEditingScope(null);
      setScopeForm(EMPTY_SCOPE);
      setScopeError(null);
      dispatch(showToast({ message: `DHCP scope ${scope.name} saved`, severity: "success" }));
    },
    onError: (error) => setScopeError(toApiError(error).message),
  });

  const deleteScope = useMutation({
    mutationFn: (id: string) => dhcpApi.removeScope(id),
    onSuccess: () => {
      invalidate();
      setScopeDelete(null);
      dispatch(showToast({ message: "DHCP scope deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const saveReservation = useMutation({
    mutationFn: () => {
      if (editingReservation) {
        return dhcpApi.updateReservation(editingReservation.id, {
          hostname: reservationForm.hostname.trim(),
          mac_address: reservationForm.mac_address.trim(),
          ip_address: reservationForm.ip_address.trim(),
          description: reservationForm.description.trim() || null,
          enabled: reservationForm.enabled,
        });
      }
      const payload: DhcpReservationPayload = {
        scope_id: reservationForm.scope_id,
        hostname: reservationForm.hostname.trim(),
        mac_address: reservationForm.mac_address.trim(),
        ip_address: reservationForm.ip_address.trim(),
        description: reservationForm.description.trim() || null,
        enabled: reservationForm.enabled,
      };
      return dhcpApi.createReservation(payload);
    },
    onSuccess: (reservation) => {
      invalidate();
      setReservationDialogOpen(false);
      setEditingReservation(null);
      setReservationForm(EMPTY_RESERVATION);
      setReservationError(null);
      dispatch(
        showToast({ message: `Reservation ${reservation.hostname} saved`, severity: "success" }),
      );
    },
    onError: (error) => setReservationError(toApiError(error).message),
  });

  const deleteReservation = useMutation({
    mutationFn: (id: string) => dhcpApi.removeReservation(id),
    onSuccess: () => {
      invalidate();
      setReservationDelete(null);
      dispatch(showToast({ message: "DHCP reservation deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const applyMutation = useMutation({
    mutationFn: () => dhcpApi.apply({ device_id: deviceFilter, dry_run: dryRun, apply: !dryRun }),
    onSuccess: () => {
      setApplyOpen(false);
      dispatch(
        showToast({
          message: dryRun ? "Dry run completed — review the API response" : "DHCP configuration applied",
          severity: "success",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreateScope = () => {
    setEditingScope(null);
    setScopeForm({ ...EMPTY_SCOPE, device_id: deviceFilter || devices[0]?.id || "" });
    setScopeError(null);
    setScopeDialogOpen(true);
  };

  const openEditScope = (scope: DhcpScope) => {
    setEditingScope(scope);
    setScopeForm({
      device_id: scope.device_id,
      name: scope.name,
      description: scope.description ?? "",
      subnet: scope.subnet,
      pool_start: scope.pool_start,
      pool_end: scope.pool_end,
      gateway: scope.gateway ?? "",
      dns_servers: scope.dns_servers.join(", "),
      domain_name: scope.domain_name ?? "",
      lease_time_seconds: String(scope.lease_time_seconds),
      enabled: scope.enabled,
    });
    setScopeError(null);
    setScopeDialogOpen(true);
  };

  const openCreateReservation = () => {
    setEditingReservation(null);
    setReservationForm({
      ...EMPTY_RESERVATION,
      scope_id: scopeFilter || scopeOptions[0]?.id || "",
    });
    setReservationError(null);
    setReservationDialogOpen(true);
  };

  const openEditReservation = (reservation: DhcpReservation) => {
    setEditingReservation(reservation);
    setReservationForm({
      scope_id: reservation.scope_id,
      hostname: reservation.hostname,
      mac_address: reservation.mac_address,
      ip_address: reservation.ip_address,
      description: reservation.description ?? "",
      enabled: reservation.enabled,
    });
    setReservationError(null);
    setReservationDialogOpen(true);
  };

  const scopeColumns: Array<DataTableColumn<DhcpScope>> = [
    {
      key: "name",
      label: "Scope",
      sortable: true,
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <LanOutlinedIcon fontSize="small" color="action" />
          <Box>
            <Typography variant="body2" fontWeight={600}>
              {row.name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {deviceName(row.device_id)}
            </Typography>
          </Box>
        </Stack>
      ),
    },
    { key: "subnet", label: "Subnet", sortable: true, monospace: true },
    {
      key: "pool",
      label: "Dynamic pool",
      hideBelow: "md",
      monospace: true,
      render: (row) => `${row.pool_start} – ${row.pool_end}`,
    },
    { key: "gateway", label: "Gateway", width: 140, hideBelow: "lg", monospace: true, render: (row) => row.gateway ?? EMPTY },
    {
      key: "lease_time_seconds",
      label: "Lease",
      width: 110,
      sortable: true,
      hideBelow: "sm",
      render: (row) => formatDuration(row.lease_time_seconds),
    },
    {
      key: "dns_servers",
      label: "DNS",
      hideBelow: "lg",
      render: (row) => (row.dns_servers.length ? row.dns_servers.join(", ") : EMPTY),
    },
    {
      key: "enabled",
      label: "State",
      width: 110,
      render: (row) => (
        <Chip
          size="small"
          color={row.enabled ? "success" : "default"}
          variant={row.enabled ? "filled" : "outlined"}
          label={row.enabled ? "Enabled" : "Disabled"}
        />
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 100,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="dhcp:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEditScope(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="dhcp:write">
            <Tooltip title="Delete">
              <IconButton size="small" color="error" onClick={() => setScopeDelete(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        </Stack>
      ),
    },
  ];

  const reservationColumns: Array<DataTableColumn<DhcpReservation>> = [
    {
      key: "hostname",
      label: "Host",
      sortable: true,
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.hostname}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {scopeName(row.scope_id)}
          </Typography>
        </Box>
      ),
    },
    { key: "mac_address", label: "MAC address", sortable: true, monospace: true, width: 190 },
    { key: "ip_address", label: "IP address", sortable: true, monospace: true, width: 160 },
    { key: "description", label: "Description", hideBelow: "md", render: (row) => row.description ?? EMPTY },
    {
      key: "enabled",
      label: "State",
      width: 110,
      render: (row) => (
        <Chip
          size="small"
          color={row.enabled ? "success" : "default"}
          variant={row.enabled ? "filled" : "outlined"}
          label={row.enabled ? "Enabled" : "Disabled"}
        />
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 100,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="dhcp:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEditReservation(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="dhcp:write">
            <Tooltip title="Delete">
              <IconButton size="small" color="error" onClick={() => setReservationDelete(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        </Stack>
      ),
    },
  ];

  const activeQuery = tab === 0 ? scopesQuery : reservationsQuery;
  const total = activeQuery.data?.meta.total ?? 0;
  const applyDevice = devices.find((device) => device.id === deviceFilter);

  return (
    <>
      <PageHeader
        title="DHCP"
        subtitle="Kea/ISC scopes and static reservations for every managed firewall."
        actions={
          <Stack direction="row" spacing={1}>
            <PermissionGate permission="dhcp:write">
              <Tooltip
                title={
                  applyDevice
                    ? `Apply the stored DHCP scopes of ${applyDevice.name}`
                    : "Filter by a device to enable applying"
                }
              >
                <span>
                  <Button
                    variant="outlined"
                    onClick={() => setApplyOpen(true)}
                    disabled={!applyDevice}
                  >
                    Apply DHCP
                  </Button>
                </span>
              </Tooltip>
            </PermissionGate>
            <PermissionGate permission="dhcp:write">
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={tab === 0 ? openCreateScope : openCreateReservation}
                disabled={devices.length === 0 || (tab === 1 && scopeOptions.length === 0)}
              >
                {tab === 0 ? "New scope" : "New reservation"}
              </Button>
            </PermissionGate>
          </Stack>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${formatNumber(scopesQuery.data?.meta.total ?? 0)} scopes`} />
            <Chip
              size="small"
              variant="outlined"
              label={`${formatNumber(reservationsQuery.data?.meta.total ?? 0)} reservations`}
            />
          </Stack>
        }
      />

      <Box sx={{ borderBottom: 1, borderColor: "divider", mb: 2 }}>
        <Tabs value={tab} onChange={(_, value: number) => setTab(value)}>
          <Tab label="Scopes" />
          <Tab label="Reservations" />
        </Tabs>
      </Box>

      {tab === 0 ? (
        <DataTable
          columns={scopeColumns}
          rows={scopesQuery.data?.items ?? []}
          getRowId={(row) => row.id}
          loading={scopesQuery.isLoading}
          error={scopesQuery.error ? toApiError(scopesQuery.error).message : null}
          onRetry={() => scopesQuery.refetch()}
          page={page}
          size={size}
          total={total}
          onPageChange={setPage}
          onSizeChange={setSize}
          sort={scopeSort}
          order={scopeOrder}
          onSortChange={(key, nextOrder) => {
            setScopeSort(key);
            setScopeOrder(nextOrder);
          }}
          emptyTitle="No DHCP scopes"
          emptyDescription="Create a scope to hand out leases on a managed firewall interface."
          emptyAction={
            <PermissionGate permission="dhcp:write">
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={openCreateScope}
                disabled={devices.length === 0}
              >
                New scope
              </Button>
            </PermissionGate>
          }
          toolbar={
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
              <TextField
                placeholder="Search scopes"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                sx={{ width: { xs: "100%", sm: 260 } }}
              />
              <TextField
                select
                label="Device"
                value={deviceFilter}
                onChange={(event) => setDeviceFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 220 } }}
              >
                <MenuItem value="">All devices</MenuItem>
                {devices.map((device) => (
                  <MenuItem key={device.id} value={device.id}>
                    {device.name}
                  </MenuItem>
                ))}
              </TextField>
              <Typography variant="caption" color="text.secondary">
                {formatNumber(total)} scopes
              </Typography>
            </Stack>
          }
        />
      ) : (
        <DataTable
          columns={reservationColumns}
          rows={reservationsQuery.data?.items ?? []}
          getRowId={(row) => row.id}
          loading={reservationsQuery.isLoading}
          error={reservationsQuery.error ? toApiError(reservationsQuery.error).message : null}
          onRetry={() => reservationsQuery.refetch()}
          page={page}
          size={size}
          total={total}
          onPageChange={setPage}
          onSizeChange={setSize}
          sort={reservationSort}
          order={reservationOrder}
          onSortChange={(key, nextOrder) => {
            setReservationSort(key);
            setReservationOrder(nextOrder);
          }}
          emptyTitle="No static reservations"
          emptyDescription="Pin a MAC address to an IP inside an existing DHCP scope."
          emptyAction={
            <PermissionGate permission="dhcp:write">
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={openCreateReservation}
                disabled={scopeOptions.length === 0}
              >
                New reservation
              </Button>
            </PermissionGate>
          }
          toolbar={
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
              <TextField
                placeholder="Search host, MAC or IP"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                sx={{ width: { xs: "100%", sm: 240 } }}
              />
              <TextField
                select
                label="Scope"
                value={scopeFilter}
                onChange={(event) => setScopeFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 240 } }}
              >
                <MenuItem value="">All scopes</MenuItem>
                {scopeOptions.map((scope) => (
                  <MenuItem key={scope.id} value={scope.id}>
                    {scope.name} · {scope.subnet}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Device"
                value={deviceFilter}
                onChange={(event) => setDeviceFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 200 } }}
              >
                <MenuItem value="">All devices</MenuItem>
                {devices.map((device) => (
                  <MenuItem key={device.id} value={device.id}>
                    {device.name}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
          }
        />
      )}

      <FormDialog
        open={scopeDialogOpen}
        title={editingScope ? `Edit ${editingScope.name}` : "New DHCP scope"}
        loading={saveScope.isPending}
        error={scopeError}
        submitLabel={editingScope ? "Save changes" : "Create scope"}
        submitDisabled={
          !scopeForm.device_id ||
          !scopeForm.name.trim() ||
          !scopeForm.subnet.trim() ||
          !scopeForm.pool_start.trim() ||
          !scopeForm.pool_end.trim()
        }
        onSubmit={() => saveScope.mutate()}
        onClose={() => {
          setScopeDialogOpen(false);
          setEditingScope(null);
        }}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Device"
            value={scopeForm.device_id}
            onChange={(event) => setScopeForm((value) => ({ ...value, device_id: event.target.value }))}
            disabled={Boolean(editingScope)}
            required
            fullWidth
          >
            {devices.map((device) => (
              <MenuItem key={device.id} value={device.id}>
                {device.name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Name"
            value={scopeForm.name}
            onChange={(event) => setScopeForm((value) => ({ ...value, name: event.target.value }))}
            disabled={Boolean(editingScope)}
            required
            autoFocus
            fullWidth
          />
        </Stack>
        <TextField
          label="Subnet (CIDR)"
          value={scopeForm.subnet}
          onChange={(event) => setScopeForm((value) => ({ ...value, subnet: event.target.value }))}
          placeholder="192.168.10.0/24"
          disabled={Boolean(editingScope)}
          required
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Pool start"
            value={scopeForm.pool_start}
            onChange={(event) => setScopeForm((value) => ({ ...value, pool_start: event.target.value }))}
            placeholder="192.168.10.100"
            required
            fullWidth
          />
          <TextField
            label="Pool end"
            value={scopeForm.pool_end}
            onChange={(event) => setScopeForm((value) => ({ ...value, pool_end: event.target.value }))}
            placeholder="192.168.10.200"
            required
            fullWidth
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Gateway"
            value={scopeForm.gateway}
            onChange={(event) => setScopeForm((value) => ({ ...value, gateway: event.target.value }))}
            placeholder="192.168.10.1"
            fullWidth
          />
          <TextField
            label="Domain name"
            value={scopeForm.domain_name}
            onChange={(event) => setScopeForm((value) => ({ ...value, domain_name: event.target.value }))}
            placeholder="branch.example.com"
            fullWidth
          />
        </Stack>
        <TextField
          label="DNS servers"
          value={scopeForm.dns_servers}
          onChange={(event) => setScopeForm((value) => ({ ...value, dns_servers: event.target.value }))}
          helperText="Comma-separated IPv4/IPv6 addresses"
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Lease time (seconds)"
            value={scopeForm.lease_time_seconds}
            onChange={(event) =>
              setScopeForm((value) => ({ ...value, lease_time_seconds: event.target.value }))
            }
            inputProps={{ inputMode: "numeric" }}
            helperText="60 – 31,536,000"
            fullWidth
          />
          <TextField
            select
            label="State"
            value={scopeForm.enabled ? "enabled" : "disabled"}
            onChange={(event) =>
              setScopeForm((value) => ({ ...value, enabled: event.target.value === "enabled" }))
            }
            fullWidth
          >
            <MenuItem value="enabled">Enabled</MenuItem>
            <MenuItem value="disabled">Disabled</MenuItem>
          </TextField>
        </Stack>
        <TextField
          label="Description"
          value={scopeForm.description}
          onChange={(event) => setScopeForm((value) => ({ ...value, description: event.target.value }))}
          multiline
          minRows={2}
          fullWidth
        />
      </FormDialog>

      <FormDialog
        open={reservationDialogOpen}
        title={editingReservation ? `Edit ${editingReservation.hostname}` : "New DHCP reservation"}
        loading={saveReservation.isPending}
        error={reservationError}
        submitLabel={editingReservation ? "Save changes" : "Create reservation"}
        submitDisabled={
          !reservationForm.scope_id ||
          !reservationForm.hostname.trim() ||
          !reservationForm.mac_address.trim() ||
          !reservationForm.ip_address.trim()
        }
        onSubmit={() => saveReservation.mutate()}
        onClose={() => {
          setReservationDialogOpen(false);
          setEditingReservation(null);
        }}
        maxWidth="sm"
      >
        <TextField
          select
          label="Scope"
          value={reservationForm.scope_id}
          onChange={(event) => setReservationForm((value) => ({ ...value, scope_id: event.target.value }))}
          disabled={Boolean(editingReservation)}
          required
          fullWidth
        >
          {scopeOptions.map((scope) => (
            <MenuItem key={scope.id} value={scope.id}>
              {scope.name} · {scope.subnet} · {deviceName(scope.device_id)}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Hostname"
          value={reservationForm.hostname}
          onChange={(event) => setReservationForm((value) => ({ ...value, hostname: event.target.value }))}
          required
          autoFocus
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="MAC address"
            value={reservationForm.mac_address}
            onChange={(event) =>
              setReservationForm((value) => ({ ...value, mac_address: event.target.value }))
            }
            placeholder="aa:bb:cc:dd:ee:ff"
            required
            fullWidth
          />
          <TextField
            label="IP address"
            value={reservationForm.ip_address}
            onChange={(event) =>
              setReservationForm((value) => ({ ...value, ip_address: event.target.value }))
            }
            placeholder="192.168.10.50"
            required
            fullWidth
          />
        </Stack>
        <TextField
          label="Description"
          value={reservationForm.description}
          onChange={(event) =>
            setReservationForm((value) => ({ ...value, description: event.target.value }))
          }
          multiline
          minRows={2}
          fullWidth
        />
        <TextField
          select
          label="State"
          value={reservationForm.enabled ? "enabled" : "disabled"}
          onChange={(event) =>
            setReservationForm((value) => ({ ...value, enabled: event.target.value === "enabled" }))
          }
          fullWidth
        >
          <MenuItem value="enabled">Enabled</MenuItem>
          <MenuItem value="disabled">Disabled</MenuItem>
        </TextField>
      </FormDialog>

      <ConfirmDialog
        open={Boolean(scopeDelete)}
        title="Delete DHCP scope"
        description={
          scopeDelete
            ? `Delete ${scopeDelete.name} (${scopeDelete.subnet}) and every reservation inside it?`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteScope.isPending}
        onConfirm={() => scopeDelete && deleteScope.mutate(scopeDelete.id)}
        onClose={() => setScopeDelete(null)}
      />

      <ConfirmDialog
        open={Boolean(reservationDelete)}
        title="Delete DHCP reservation"
        description={
          reservationDelete
            ? `Delete the reservation for ${reservationDelete.hostname} (${reservationDelete.ip_address})?`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteReservation.isPending}
        onConfirm={() => reservationDelete && deleteReservation.mutate(reservationDelete.id)}
        onClose={() => setReservationDelete(null)}
      />

      <FormDialog
        open={applyOpen}
        title="Apply DHCP configuration"
        description={
          applyDevice
            ? `Create, update and prune OFME-managed Kea subnets and reservations on ${applyDevice.name}.`
            : undefined
        }
        loading={applyMutation.isPending}
        submitLabel={dryRun ? "Run dry run" : "Apply"}
        onSubmit={() => applyMutation.mutate()}
        onClose={() => setApplyOpen(false)}
      >
        <TextField
          select
          label="Mode"
          value={dryRun ? "dry" : "apply"}
          onChange={(event) => setDryRun(event.target.value === "dry")}
          fullWidth
        >
          <MenuItem value="apply">Apply to the appliance</MenuItem>
          <MenuItem value="dry">Dry run (inspect the payload)</MenuItem>
        </TextField>
      </FormDialog>
    </>
  );
}

export default DhcpPage;
