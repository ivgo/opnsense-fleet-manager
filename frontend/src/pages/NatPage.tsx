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
import SwapHorizOutlinedIcon from "@mui/icons-material/SwapHorizOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { devicesApi, natApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { NatRule, NatRulePayload, NatRuleUpdatePayload, NatType } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import { useDebounce } from "@/hooks/useDebounce";
import { usePermissions } from "@/hooks/usePermissions";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { EMPTY, formatNumber, titleCase } from "@/utils/format";

const NAT_TYPES: Array<{ value: NatType; label: string }> = [
  { value: "port_forward", label: "Port forward" },
  { value: "outbound", label: "Outbound" },
  { value: "one_to_one", label: "One-to-one" },
];

const PROTOCOLS = ["any", "tcp", "udp", "icmp", "tcp/udp"] as const;

const TYPE_COLORS: Record<NatType, "primary" | "secondary" | "info"> = {
  port_forward: "primary",
  outbound: "secondary",
  one_to_one: "info",
};

interface NatFormState {
  device_id: string;
  name: string;
  description: string;
  type: NatType;
  interface: string;
  protocol: string;
  source: string;
  destination: string;
  destination_port: string;
  target: string;
  target_port: string;
  enabled: boolean;
  order_index: string;
}

const EMPTY_FORM: NatFormState = {
  device_id: "",
  name: "",
  description: "",
  type: "port_forward",
  interface: "wan",
  protocol: "tcp",
  source: "any",
  destination: "wan",
  destination_port: "",
  target: "",
  target_port: "",
  enabled: true,
  order_index: "0",
};

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function NatPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const { can } = usePermissions();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);
  const [typeFilter, setTypeFilter] = useState("");
  const [deviceFilter, setDeviceFilter] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<NatRule | null>(null);
  const [form, setForm] = useState<NatFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<NatRule | null>(null);
  const [applyOpen, setApplyOpen] = useState(false);
  const [dryRun, setDryRun] = useState(false);

  const listParams = useMemo(
    () => ({
      page,
      size,
      search: debouncedSearch || undefined,
      type: typeFilter || undefined,
      device_id: deviceFilter || undefined,
    }),
    [page, size, debouncedSearch, typeFilter, deviceFilter],
  );

  const natQuery = useQuery({
    queryKey: qk.nat.list(listParams),
    queryFn: () => natApi.list(listParams),
  });

  const devicesQuery = useQuery({
    queryKey: qk.devices.list({ size: 200, sort: "name", order: "asc" }),
    queryFn: () => devicesApi.list({ size: 200, sort: "name", order: "asc" }),
    staleTime: 60_000,
  });

  const devices = useMemo(() => devicesQuery.data?.items ?? [], [devicesQuery.data]);
  const deviceName = useMemo(() => {
    const map = new Map(devices.map((device) => [device.id, device.name]));
    return (id: string | null) => (id ? map.get(id) ?? id : "Tenant-wide");
  }, [devices]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, typeFilter, deviceFilter]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.nat.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const orderIndex = Number(form.order_index) || 0;
      if (editing) {
        const payload: NatRuleUpdatePayload = {
          description: optionalText(form.description),
          interface: form.interface.trim() || "wan",
          protocol: form.protocol,
          source: form.source.trim() || "any",
          destination: form.destination.trim() || "any",
          destination_port: optionalText(form.destination_port),
          target: form.target.trim(),
          target_port: optionalText(form.target_port),
          enabled: form.enabled,
          order_index: orderIndex,
        };
        return natApi.update(editing.id, payload);
      }
      const payload: NatRulePayload = {
        device_id: form.device_id || null,
        name: form.name.trim(),
        description: optionalText(form.description),
        type: form.type,
        interface: form.interface.trim() || "wan",
        protocol: form.protocol,
        source: form.source.trim() || "any",
        destination: form.destination.trim() || "any",
        destination_port: optionalText(form.destination_port),
        target: form.target.trim(),
        target_port: optionalText(form.target_port),
        enabled: form.enabled,
        order_index: orderIndex,
      };
      return natApi.create(payload);
    },
    onSuccess: (rule) => {
      invalidate();
      setDialogOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(showToast({ message: `NAT rule ${rule.name} saved`, severity: "success" }));
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => natApi.remove(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "NAT rule deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const applyMutation = useMutation({
    mutationFn: () => natApi.apply({ device_id: deviceFilter, dry_run: dryRun, apply: !dryRun }),
    onSuccess: () => {
      setApplyOpen(false);
      dispatch(
        showToast({
          message: dryRun ? "Dry run completed — review the API response" : "NAT configuration applied",
          severity: "success",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreate = () => {
    setEditing(null);
    setForm({ ...EMPTY_FORM, device_id: deviceFilter || devices[0]?.id || "" });
    setFormError(null);
    setDialogOpen(true);
  };

  const openEdit = (rule: NatRule) => {
    setEditing(rule);
    setForm({
      device_id: rule.device_id ?? "",
      name: rule.name,
      description: rule.description ?? "",
      type: rule.type as NatType,
      interface: rule.interface,
      protocol: rule.protocol,
      source: rule.source,
      destination: rule.destination,
      destination_port: rule.destination_port ?? "",
      target: rule.target ?? "",
      target_port: rule.target_port ?? "",
      enabled: rule.enabled,
      order_index: String(rule.order_index),
    });
    setFormError(null);
    setDialogOpen(true);
  };

  const columns: Array<DataTableColumn<NatRule>> = [
    {
      key: "name",
      label: "Rule",
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <SwapHorizOutlinedIcon fontSize="small" color="action" />
          <Box>
            <Typography variant="body2" fontWeight={600}>
              {row.name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {deviceName(row.device_id)}
              {row.description ? ` · ${row.description}` : ""}
            </Typography>
          </Box>
        </Stack>
      ),
    },
    {
      key: "type",
      label: "Type",
      width: 140,
      render: (row) => (
        <Chip
          size="small"
          color={TYPE_COLORS[row.type as NatType] ?? "default"}
          variant="outlined"
          label={titleCase(row.type)}
        />
      ),
    },
    {
      key: "interface",
      label: "Interface",
      width: 110,
      hideBelow: "md",
      render: (row) => row.interface,
    },
    {
      key: "match",
      label: "Match",
      hideBelow: "lg",
      render: (row) => (
        <Box sx={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          <Typography variant="body2" fontFamily="monospace" fontSize={12.5}>
            {row.protocol} {row.source} → {row.destination}
            {row.destination_port ? `:${row.destination_port}` : ""}
          </Typography>
        </Box>
      ),
    },
    {
      key: "target",
      label: "Target",
      hideBelow: "sm",
      render: (row) => (
        <Typography variant="body2" fontFamily="monospace" fontSize={12.5}>
          {row.target ?? EMPTY}
          {row.target_port ? `:${row.target_port}` : ""}
        </Typography>
      ),
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
          <PermissionGate permission="nat:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEdit(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="nat:write">
            <Tooltip title="Delete">
              <IconButton size="small" color="error" onClick={() => setDeleteTarget(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        </Stack>
      ),
    },
  ];

  const applyDevice = devices.find((device) => device.id === deviceFilter);

  return (
    <>
      <PageHeader
        title="NAT"
        subtitle="Port forwards, outbound translation and one-to-one mappings stored as desired state."
        actions={
          <Stack direction="row" spacing={1}>
            <PermissionGate permission="nat:write">
              <Tooltip
                title={
                  applyDevice
                    ? `Apply the stored NAT rules of ${applyDevice.name}`
                    : "Filter by a device to enable applying"
                }
              >
                <span>
                  <Button
                    variant="outlined"
                    onClick={() => setApplyOpen(true)}
                    disabled={!applyDevice || !can("nat:write")}
                  >
                    Apply NAT
                  </Button>
                </span>
              </Tooltip>
            </PermissionGate>
            <PermissionGate permission="nat:write">
              <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
                New NAT rule
              </Button>
            </PermissionGate>
          </Stack>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${formatNumber(natQuery.data?.meta.total ?? 0)} rules`} />
            <Chip
              size="small"
              variant="outlined"
              label={`${formatNumber(devicesQuery.isPending ? undefined : devices.length)} devices`}
            />
          </Stack>
        }
      />

      <DataTable
        columns={columns}
        rows={natQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={natQuery.isLoading}
        error={natQuery.error ? toApiError(natQuery.error).message : null}
        onRetry={() => natQuery.refetch()}
        page={page}
        size={size}
        total={natQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        emptyTitle="No NAT rules"
        emptyDescription="Create port forwards or outbound NAT rules for a managed firewall."
        emptyAction={
          <PermissionGate permission="nat:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New NAT rule
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <TextField
              placeholder="Search rule name"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              sx={{ width: { xs: "100%", sm: 240 } }}
            />
            <TextField
              select
              label="Type"
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
              sx={{ width: { xs: "100%", sm: 160 } }}
            >
              <MenuItem value="">All types</MenuItem>
              {NAT_TYPES.map((type) => (
                <MenuItem key={type.value} value={type.value}>
                  {type.label}
                </MenuItem>
              ))}
            </TextField>
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
          </Stack>
        }
      />

      <FormDialog
        open={dialogOpen}
        title={editing ? `Edit ${editing.name}` : "New NAT rule"}
        loading={saveMutation.isPending}
        error={formError}
        submitLabel={editing ? "Save changes" : "Create rule"}
        submitDisabled={!form.name.trim() || !form.target.trim()}
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
            label="Device"
            value={form.device_id}
            onChange={(event) => setForm((value) => ({ ...value, device_id: event.target.value }))}
            disabled={Boolean(editing)}
            helperText="Leave empty for a tenant-wide rule"
            fullWidth
          >
            <MenuItem value="">Tenant-wide</MenuItem>
            {devices.map((device) => (
              <MenuItem key={device.id} value={device.id}>
                {device.name}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Type"
            value={form.type}
            onChange={(event) => setForm((value) => ({ ...value, type: event.target.value as NatType }))}
            disabled={Boolean(editing)}
            fullWidth
          >
            {NAT_TYPES.map((type) => (
              <MenuItem key={type.value} value={type.value}>
                {type.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Interface"
            value={form.interface}
            onChange={(event) => setForm((value) => ({ ...value, interface: event.target.value }))}
            placeholder="wan"
            fullWidth
          />
          <TextField
            select
            label="Protocol"
            value={form.protocol}
            onChange={(event) => setForm((value) => ({ ...value, protocol: event.target.value }))}
            fullWidth
          >
            {PROTOCOLS.map((protocol) => (
              <MenuItem key={protocol} value={protocol}>
                {protocol}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Source"
            value={form.source}
            onChange={(event) => setForm((value) => ({ ...value, source: event.target.value }))}
            placeholder="any"
            fullWidth
          />
          <TextField
            label="Destination"
            value={form.destination}
            onChange={(event) => setForm((value) => ({ ...value, destination: event.target.value }))}
            placeholder="wan / 203.0.113.10"
            fullWidth
          />
          <TextField
            label="Destination port"
            value={form.destination_port}
            onChange={(event) =>
              setForm((value) => ({ ...value, destination_port: event.target.value }))
            }
            placeholder="443"
            fullWidth
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Target"
            value={form.target}
            onChange={(event) => setForm((value) => ({ ...value, target: event.target.value }))}
            placeholder="192.0.2.20"
            required
            fullWidth
          />
          <TextField
            label="Target port"
            value={form.target_port}
            onChange={(event) => setForm((value) => ({ ...value, target_port: event.target.value }))}
            placeholder="8443"
            fullWidth
          />
          <TextField
            label="Order index"
            value={form.order_index}
            onChange={(event) => setForm((value) => ({ ...value, order_index: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
            fullWidth
          />
        </Stack>
        <TextField
          select
          label="State"
          value={form.enabled ? "enabled" : "disabled"}
          onChange={(event) =>
            setForm((value) => ({ ...value, enabled: event.target.value === "enabled" }))
          }
          fullWidth
        >
          <MenuItem value="enabled">Enabled</MenuItem>
          <MenuItem value="disabled">Disabled</MenuItem>
        </TextField>
        <TextField
          label="Description"
          value={form.description}
          onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))}
          multiline
          minRows={2}
          fullWidth
        />
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete NAT rule"
        description={deleteTarget ? `Delete NAT rule ${deleteTarget.name}?` : undefined}
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onClose={() => setDeleteTarget(null)}
      />

      <FormDialog
        open={applyOpen}
        title="Apply NAT configuration"
        description={
          applyDevice
            ? `Create, update and prune OFME-managed NAT rules on ${applyDevice.name}.`
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

export default NatPage;
