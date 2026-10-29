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
import PublicOutlinedIcon from "@mui/icons-material/PublicOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { devicesApi, dnsApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { DnsRecord, DnsRecordPayload, DnsRecordType } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import { useDebounce } from "@/hooks/useDebounce";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { EMPTY, formatNumber } from "@/utils/format";

const RECORD_TYPES: DnsRecordType[] = ["A", "AAAA", "CNAME", "MX", "TXT", "SRV", "PTR", "NS"];

interface RecordFormState {
  device_id: string;
  name: string;
  record_type: DnsRecordType;
  value: string;
  ttl: string;
  priority: string;
  weight: string;
  port: string;
  description: string;
  enabled: boolean;
}

const EMPTY_FORM: RecordFormState = {
  device_id: "",
  name: "",
  record_type: "A",
  value: "",
  ttl: "300",
  priority: "",
  weight: "",
  port: "",
  description: "",
  enabled: true,
};

function optionalInteger(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
}

export function DnsPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [sort, setSort] = useState("name");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);
  const [typeFilter, setTypeFilter] = useState("");
  const [deviceFilter, setDeviceFilter] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<DnsRecord | null>(null);
  const [form, setForm] = useState<RecordFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DnsRecord | null>(null);

  const [applyOpen, setApplyOpen] = useState(false);
  const [dryRun, setDryRun] = useState(false);

  const listParams = useMemo(
    () => ({
      page,
      size,
      sort,
      order,
      search: debouncedSearch || undefined,
      record_type: typeFilter || undefined,
      device_id: deviceFilter || undefined,
    }),
    [page, size, sort, order, debouncedSearch, typeFilter, deviceFilter],
  );

  const recordsQuery = useQuery({
    queryKey: qk.dns.records(listParams),
    queryFn: () => dnsApi.records(listParams),
  });

  const devicesQuery = useQuery({
    queryKey: qk.devices.list({ size: 200, sort: "name", order: "asc" }),
    queryFn: () => devicesApi.list({ size: 200, sort: "name", order: "asc" }),
    staleTime: 60_000,
  });

  const devices = useMemo(() => devicesQuery.data?.items ?? [], [devicesQuery.data]);
  const deviceName = useMemo(() => {
    const map = new Map(devices.map((device) => [device.id, device.name]));
    return (id: string) => map.get(id) ?? id;
  }, [devices]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, typeFilter, deviceFilter]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.dns.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const priority =
        form.record_type === "MX" || form.record_type === "SRV" ? optionalInteger(form.priority) : null;
      const weight = form.record_type === "SRV" ? optionalInteger(form.weight) : null;
      const port = form.record_type === "SRV" ? optionalInteger(form.port) : null;
      const payload: DnsRecordPayload = {
        device_id: form.device_id,
        name: form.name.trim(),
        record_type: form.record_type,
        value: form.value.trim(),
        ttl: optionalInteger(form.ttl) ?? 300,
        priority,
        weight,
        port,
        description: form.description.trim() || null,
        enabled: form.enabled,
      };
      if (editing) {
        return dnsApi.updateRecord(editing.id, {
          value: payload.value,
          ttl: payload.ttl,
          priority: payload.priority,
          weight: payload.weight,
          port: payload.port,
          description: payload.description,
          enabled: payload.enabled,
        });
      }
      return dnsApi.createRecord(payload);
    },
    onSuccess: (record) => {
      invalidate();
      setDialogOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(
        showToast({
          message: `${record.record_type} record ${record.name} saved`,
          severity: "success",
        }),
      );
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => dnsApi.removeRecord(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "DNS record deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const applyMutation = useMutation({
    mutationFn: () => dnsApi.apply({ device_id: deviceFilter, dry_run: dryRun, apply: !dryRun }),
    onSuccess: () => {
      setApplyOpen(false);
      dispatch(
        showToast({
          message: dryRun ? "Dry run completed — review the API response" : "DNS configuration applied",
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

  const openEdit = (record: DnsRecord) => {
    setEditing(record);
    setForm({
      device_id: record.device_id,
      name: record.name,
      record_type: record.record_type,
      value: record.value,
      ttl: String(record.ttl),
      priority: record.priority !== null ? String(record.priority) : "",
      weight: record.weight !== null ? String(record.weight) : "",
      port: record.port !== null ? String(record.port) : "",
      description: record.description ?? "",
      enabled: record.enabled,
    });
    setFormError(null);
    setDialogOpen(true);
  };

  const columns: Array<DataTableColumn<DnsRecord>> = [
    {
      key: "name",
      label: "Name",
      sortable: true,
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <PublicOutlinedIcon fontSize="small" color="action" />
          <Box>
            <Typography variant="body2" fontWeight={600} fontFamily="monospace">
              {row.name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {deviceName(row.device_id)}
            </Typography>
          </Box>
        </Stack>
      ),
    },
    {
      key: "record_type",
      label: "Type",
      width: 100,
      sortable: true,
      render: (row) => <Chip size="small" variant="outlined" label={row.record_type} />,
    },
    {
      key: "value",
      label: "Value",
      monospace: true,
      render: (row) => (
        <Box sx={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {row.value}
        </Box>
      ),
    },
    {
      key: "ttl",
      label: "TTL",
      width: 90,
      align: "right",
      sortable: true,
      hideBelow: "sm",
      render: (row) => formatNumber(row.ttl),
    },
    {
      key: "priority",
      label: "Priority / port",
      width: 150,
      hideBelow: "md",
      render: (row) => {
        if (row.record_type === "SRV") {
          return `${row.priority ?? EMPTY} / ${row.port ?? EMPTY}`;
        }
        return row.priority !== null ? formatNumber(row.priority) : EMPTY;
      },
    },
    { key: "description", label: "Description", hideBelow: "lg", render: (row) => row.description ?? EMPTY },
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
          <PermissionGate permission="dns:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEdit(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="dns:write">
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
        title="DNS"
        subtitle="Authoritative A/AAAA, CNAME, MX, TXT, SRV, PTR and NS records for managed resolvers."
        actions={
          <Stack direction="row" spacing={1}>
            <PermissionGate permission="dns:write">
              <Tooltip
                title={
                  applyDevice
                    ? `Apply the stored DNS records of ${applyDevice.name}`
                    : "Filter by a device to enable applying"
                }
              >
                <span>
                  <Button
                    variant="outlined"
                    onClick={() => setApplyOpen(true)}
                    disabled={!applyDevice}
                  >
                    Apply DNS
                  </Button>
                </span>
              </Tooltip>
            </PermissionGate>
            <PermissionGate permission="dns:write">
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={openCreate}
                disabled={devices.length === 0}
              >
                New record
              </Button>
            </PermissionGate>
          </Stack>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${formatNumber(recordsQuery.data?.meta.total ?? 0)} records`} />
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
        rows={recordsQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={recordsQuery.isLoading}
        error={recordsQuery.error ? toApiError(recordsQuery.error).message : null}
        onRetry={() => recordsQuery.refetch()}
        page={page}
        size={size}
        total={recordsQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        sort={sort}
        order={order}
        onSortChange={(key, nextOrder) => {
          setSort(key);
          setOrder(nextOrder);
        }}
        emptyTitle="No DNS records"
        emptyDescription="Publish authoritative records for the Unbound resolver on a managed firewall."
        emptyAction={
          <PermissionGate permission="dns:write">
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={openCreate}
              disabled={devices.length === 0}
            >
              New record
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <TextField
              placeholder="Search name or value"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              sx={{ width: { xs: "100%", sm: 260 } }}
            />
            <TextField
              select
              label="Type"
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
              sx={{ width: { xs: "100%", sm: 140 } }}
            >
              <MenuItem value="">All types</MenuItem>
              {RECORD_TYPES.map((type) => (
                <MenuItem key={type} value={type}>
                  {type}
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
        title={editing ? `Edit ${editing.name}` : "New DNS record"}
        loading={saveMutation.isPending}
        error={formError}
        submitLabel={editing ? "Save changes" : "Create record"}
        submitDisabled={
          !form.device_id || !form.name.trim() || !form.value.trim() || !form.ttl.trim()
        }
        onSubmit={() => saveMutation.mutate()}
        onClose={() => {
          setDialogOpen(false);
          setEditing(null);
        }}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Device"
            value={form.device_id}
            onChange={(event) => setForm((value) => ({ ...value, device_id: event.target.value }))}
            disabled={Boolean(editing)}
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
            select
            label="Record type"
            value={form.record_type}
            onChange={(event) =>
              setForm((value) => ({ ...value, record_type: event.target.value as DnsRecordType }))
            }
            disabled={Boolean(editing)}
            fullWidth
          >
            {RECORD_TYPES.map((type) => (
              <MenuItem key={type} value={type}>
                {type}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <TextField
          label="Name"
          value={form.name}
          onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
          placeholder={form.record_type === "PTR" ? "10.0.0.1.in-addr.arpa" : "www.example.com"}
          helperText="Relative or fully-qualified owner name; '@' is the zone root"
          disabled={Boolean(editing)}
          required
          autoFocus
          fullWidth
        />
        <TextField
          label="Value"
          value={form.value}
          onChange={(event) => setForm((value) => ({ ...value, value: event.target.value }))}
          placeholder={form.record_type === "A" ? "192.0.2.10" : form.record_type === "TXT" ? "v=spf1 -all" : "target.example.com"}
          required
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="TTL (seconds)"
            value={form.ttl}
            onChange={(event) => setForm((value) => ({ ...value, ttl: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
            helperText="0 – 604,800"
            fullWidth
          />
          {(form.record_type === "MX" || form.record_type === "SRV") && (
            <TextField
              label="Priority"
              value={form.priority}
              onChange={(event) => setForm((value) => ({ ...value, priority: event.target.value }))}
              inputProps={{ inputMode: "numeric" }}
              required
              fullWidth
            />
          )}
        </Stack>
        {form.record_type === "SRV" && (
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField
              label="Weight"
              value={form.weight}
              onChange={(event) => setForm((value) => ({ ...value, weight: event.target.value }))}
              inputProps={{ inputMode: "numeric" }}
              required
              fullWidth
            />
            <TextField
              label="Port"
              value={form.port}
              onChange={(event) => setForm((value) => ({ ...value, port: event.target.value }))}
              inputProps={{ inputMode: "numeric" }}
              required
              fullWidth
            />
          </Stack>
        )}
        <TextField
          label="Description"
          value={form.description}
          onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))}
          multiline
          minRows={2}
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
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete DNS record"
        description={
          deleteTarget
            ? `Delete ${deleteTarget.record_type} ${deleteTarget.name} → ${deleteTarget.value}?`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onClose={() => setDeleteTarget(null)}
      />

      <FormDialog
        open={applyOpen}
        title="Apply DNS configuration"
        description={
          applyDevice
            ? `Create, update and prune OFME-managed Unbound host overrides on ${applyDevice.name}.`
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

export default DnsPage;
