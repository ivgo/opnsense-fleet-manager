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
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import GppGoodOutlinedIcon from "@mui/icons-material/GppGoodOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { devicesApi, rulesApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { Rule, RuleAction, RuleDirection, RulePayload, RuleUpdatePayload } from "@/api/types";
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
import { EMPTY, formatNumber, parseLines } from "@/utils/format";

const ACTIONS: Array<{ value: RuleAction; label: string }> = [
  { value: "pass", label: "Pass" },
  { value: "block", label: "Block" },
  { value: "reject", label: "Reject" },
];

const DIRECTIONS: Array<{ value: RuleDirection; label: string }> = [
  { value: "in", label: "In" },
  { value: "out", label: "Out" },
];

const PROTOCOLS = ["any", "tcp", "udp", "icmp", "icmp6", "esp", "ah", "gre", "tcp/udp"] as const;

const ACTION_COLORS: Record<RuleAction, "success" | "error" | "warning"> = {
  pass: "success",
  block: "error",
  reject: "warning",
};

interface RuleFormState {
  device_id: string;
  name: string;
  description: string;
  action: RuleAction;
  direction: RuleDirection;
  interface: string;
  protocol: string;
  source: string;
  destination: string;
  destination_port: string;
  source_port: string;
  gateway: string;
  log: boolean;
  enabled: boolean;
  order_index: string;
  tags: string;
}

const EMPTY_FORM: RuleFormState = {
  device_id: "",
  name: "",
  description: "",
  action: "pass",
  direction: "in",
  interface: "wan",
  protocol: "any",
  source: "any",
  destination: "any",
  destination_port: "",
  source_port: "",
  gateway: "",
  log: false,
  enabled: true,
  order_index: "",
  tags: "",
};

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function RulesPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const { can } = usePermissions();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);
  const [actionFilter, setActionFilter] = useState("");
  const [deviceFilter, setDeviceFilter] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Rule | null>(null);
  const [form, setForm] = useState<RuleFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Rule | null>(null);
  const [deployOpen, setDeployOpen] = useState(false);

  const listParams = useMemo(
    () => ({
      page,
      size,
      search: debouncedSearch || undefined,
      action: actionFilter || undefined,
      device_id: deviceFilter || undefined,
    }),
    [page, size, debouncedSearch, actionFilter, deviceFilter],
  );

  const rulesQuery = useQuery({
    queryKey: qk.rules.list(listParams),
    queryFn: () => rulesApi.list(listParams),
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
  }, [debouncedSearch, actionFilter, deviceFilter]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.rules.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const orderIndex = form.order_index.trim() ? Number(form.order_index) : null;
      if (editing) {
        const payload: RuleUpdatePayload = {
          description: optionalText(form.description),
          action: form.action,
          direction: form.direction,
          interface: optionalText(form.interface),
          protocol: form.protocol,
          source: form.source.trim() || "any",
          destination: form.destination.trim() || "any",
          destination_port: optionalText(form.destination_port),
          source_port: optionalText(form.source_port),
          gateway: optionalText(form.gateway),
          log: form.log,
          enabled: form.enabled,
          order_index: orderIndex,
          tags: parseLines(form.tags),
        };
        return rulesApi.update(editing.id, payload);
      }
      const payload: RulePayload = {
        device_id: form.device_id || null,
        name: form.name.trim(),
        description: optionalText(form.description),
        action: form.action,
        direction: form.direction,
        interface: optionalText(form.interface),
        protocol: form.protocol,
        source: form.source.trim() || "any",
        destination: form.destination.trim() || "any",
        destination_port: optionalText(form.destination_port),
        source_port: optionalText(form.source_port),
        gateway: optionalText(form.gateway),
        log: form.log,
        enabled: form.enabled,
        order_index: orderIndex,
        tags: parseLines(form.tags),
      };
      return rulesApi.create(payload);
    },
    onSuccess: (rule) => {
      invalidate();
      setDialogOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(
        showToast({
          message: `Rule ${rule.name} saved`,
          severity: "success",
        }),
      );
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => rulesApi.remove(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Firewall rule deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const conflictsMutation = useMutation({
    mutationFn: (id: string) => rulesApi.conflicts(id),
    onSuccess: (rows) => {
      dispatch(
        showToast({
          message:
            rows.length === 0
              ? "No shadowing or overlapping rules detected"
              : `${rows.length} conflicting rule(s) detected`,
          severity: rows.length === 0 ? "success" : "warning",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const deployMutation = useMutation({
    mutationFn: (deviceId: string) => rulesApi.deploy(deviceId, false),
    onSuccess: (result) => {
      setDeployOpen(false);
      dispatch(
        showToast({
          message: `Deployed to device: ${result.created} created, ${result.updated} updated`,
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

  const openEdit = (rule: Rule) => {
    setEditing(rule);
    setForm({
      device_id: rule.device_id ?? "",
      name: rule.name,
      description: rule.description ?? "",
      action: rule.action as RuleAction,
      direction: rule.direction as RuleDirection,
      interface: rule.interface ?? "",
      protocol: rule.protocol,
      source: rule.source,
      destination: rule.destination,
      destination_port: rule.destination_port ?? "",
      source_port: rule.source_port ?? "",
      gateway: rule.gateway ?? "",
      log: rule.log,
      enabled: rule.enabled,
      order_index: String(rule.order_index),
      tags: rule.tags.join(", "),
    });
    setFormError(null);
    setDialogOpen(true);
  };

  const columns: Array<DataTableColumn<Rule>> = [
    {
      key: "order_index",
      label: "#",
      width: 64,
      align: "right",
      hideBelow: "sm",
      render: (row) => <Typography variant="caption" color="text.secondary">{row.order_index}</Typography>,
    },
    {
      key: "name",
      label: "Rule",
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <GppGoodOutlinedIcon fontSize="small" color="action" />
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
      key: "action",
      label: "Action",
      width: 100,
      render: (row) => (
        <Chip
          size="small"
          color={ACTION_COLORS[row.action as RuleAction] ?? "default"}
          label={row.action.toUpperCase()}
        />
      ),
    },
    {
      key: "direction",
      label: "Dir.",
      width: 80,
      hideBelow: "sm",
      render: (row) => <Chip size="small" variant="outlined" label={row.direction.toUpperCase()} />,
    },
    {
      key: "interface",
      label: "Interface",
      width: 120,
      hideBelow: "md",
      render: (row) => row.interface ?? EMPTY,
    },
    {
      key: "protocol",
      label: "Proto",
      width: 90,
      hideBelow: "md",
      render: (row) => row.protocol,
    },
    {
      key: "source",
      label: "Source → destination",
      hideBelow: "lg",
      render: (row) => (
        <Box sx={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          <Typography variant="body2" fontFamily="monospace" fontSize={12.5}>
            {row.source} → {row.destination}
            {row.destination_port ? `:${row.destination_port}` : ""}
          </Typography>
        </Box>
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
      width: 140,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <Tooltip title="Check conflicts">
            <IconButton size="small" onClick={() => conflictsMutation.mutate(row.id)}>
              <FactCheckOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <PermissionGate permission="rule:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEdit(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="rule:delete">
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

  const deployDevice = devices.find((device) => device.id === deviceFilter);

  return (
    <>
      <PageHeader
        title="Firewall rules"
        subtitle="Ordered pass, block and reject rules stored as desired state and pushed to OPNsense."
        actions={
          <Stack direction="row" spacing={1}>
            <PermissionGate permission="policy:deploy">
              <Tooltip
                title={
                  deployDevice
                    ? `Push the stored rule set to ${deployDevice.name}`
                    : "Filter by a device to enable deployment"
                }
              >
                <span>
                  <Button
                    variant="outlined"
                    onClick={() => setDeployOpen(true)}
                    disabled={!deployDevice || !can("policy:deploy")}
                  >
                    Deploy rules
                  </Button>
                </span>
              </Tooltip>
            </PermissionGate>
            <PermissionGate permission="rule:write">
              <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
                New rule
              </Button>
            </PermissionGate>
          </Stack>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${formatNumber(rulesQuery.data?.meta.total ?? 0)} rules`} />
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
        rows={rulesQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={rulesQuery.isLoading}
        error={rulesQuery.error ? toApiError(rulesQuery.error).message : null}
        onRetry={() => rulesQuery.refetch()}
        page={page}
        size={size}
        total={rulesQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        emptyTitle="No firewall rules"
        emptyDescription="Create ordered rules for a managed firewall, then deploy them to the appliance."
        emptyAction={
          <PermissionGate permission="rule:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New rule
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
              label="Action"
              value={actionFilter}
              onChange={(event) => setActionFilter(event.target.value)}
              sx={{ width: { xs: "100%", sm: 140 } }}
            >
              <MenuItem value="">All actions</MenuItem>
              {ACTIONS.map((action) => (
                <MenuItem key={action.value} value={action.value}>
                  {action.label}
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
        title={editing ? `Edit ${editing.name}` : "New firewall rule"}
        loading={saveMutation.isPending}
        error={formError}
        submitLabel={editing ? "Save changes" : "Create rule"}
        submitDisabled={!form.name.trim()}
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
            helperText="Letters, digits, spaces and _ . : -"
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
            label="Action"
            value={form.action}
            onChange={(event) =>
              setForm((value) => ({ ...value, action: event.target.value as RuleAction }))
            }
            fullWidth
          >
            {ACTIONS.map((action) => (
              <MenuItem key={action.value} value={action.value}>
                {action.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Direction"
            value={form.direction}
            onChange={(event) =>
              setForm((value) => ({ ...value, direction: event.target.value as RuleDirection }))
            }
            fullWidth
          >
            {DIRECTIONS.map((direction) => (
              <MenuItem key={direction.value} value={direction.value}>
                {direction.label}
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
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
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
          <TextField
            label="Source"
            value={form.source}
            onChange={(event) => setForm((value) => ({ ...value, source: event.target.value }))}
            placeholder="any / alias / CIDR"
            fullWidth
          />
          <TextField
            label="Source port"
            value={form.source_port}
            onChange={(event) => setForm((value) => ({ ...value, source_port: event.target.value }))}
            placeholder="any"
            fullWidth
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Destination"
            value={form.destination}
            onChange={(event) => setForm((value) => ({ ...value, destination: event.target.value }))}
            placeholder="any / alias / CIDR"
            fullWidth
          />
          <TextField
            label="Destination port"
            value={form.destination_port}
            onChange={(event) =>
              setForm((value) => ({ ...value, destination_port: event.target.value }))
            }
            placeholder="443 / 8000-8100"
            fullWidth
          />
          <TextField
            label="Gateway"
            value={form.gateway}
            onChange={(event) => setForm((value) => ({ ...value, gateway: event.target.value }))}
            placeholder="optional"
            fullWidth
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Order index"
            value={form.order_index}
            onChange={(event) => setForm((value) => ({ ...value, order_index: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
            helperText="Empty appends to the end"
            fullWidth
          />
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
            select
            label="Logging"
            value={form.log ? "on" : "off"}
            onChange={(event) => setForm((value) => ({ ...value, log: event.target.value === "on" }))}
            fullWidth
          >
            <MenuItem value="off">No logging</MenuItem>
            <MenuItem value="on">Log matches</MenuItem>
          </TextField>
        </Stack>
        <TextField
          label="Tags"
          value={form.tags}
          onChange={(event) => setForm((value) => ({ ...value, tags: event.target.value }))}
          helperText="Comma-separated"
          fullWidth
        />
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
        title="Delete firewall rule"
        description={deleteTarget ? `Delete rule ${deleteTarget.name}?` : undefined}
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onClose={() => setDeleteTarget(null)}
      />

      <ConfirmDialog
        open={deployOpen}
        title="Deploy firewall rules"
        description={
          deployDevice
            ? `Push the stored rule set of ${deployDevice.name} to the appliance? Existing OFME-managed rules are updated and stale ones are pruned.`
            : undefined
        }
        confirmLabel="Deploy"
        loading={deployMutation.isPending}
        onConfirm={() => deployDevice && deployMutation.mutate(deployDevice.id)}
        onClose={() => setDeployOpen(false)}
      />
    </>
  );
}

export default RulesPage;
