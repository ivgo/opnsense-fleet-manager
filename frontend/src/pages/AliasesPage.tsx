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
import LabelOutlinedIcon from "@mui/icons-material/LabelOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { aliasesApi, devicesApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { Alias, AliasPayload, AliasType, AliasUpdatePayload } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import { useDebounce } from "@/hooks/useDebounce";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { EMPTY, formatNumber, parseLines, titleCase, truncate } from "@/utils/format";

const ALIAS_TYPES: Array<{ value: AliasType; label: string }> = [
  { value: "host", label: "Host" },
  { value: "network", label: "Network" },
  { value: "port", label: "Port" },
  { value: "url", label: "URL table" },
  { value: "mac", label: "MAC" },
  { value: "nested", label: "Nested" },
];

const CONTENT_PLACEHOLDERS: Record<AliasType, string> = {
  host: "192.0.2.10\n192.0.2.11",
  network: "10.0.0.0/8\n172.16.0.0/12",
  port: "443\n8000:8100",
  url: "https://example.com/blocklist.txt",
  mac: "aa:bb:cc:dd:ee:ff",
  nested: "other_alias_name",
};

interface AliasFormState {
  device_id: string;
  name: string;
  description: string;
  type: AliasType;
  content: string;
  enabled: boolean;
}

const EMPTY_FORM: AliasFormState = {
  device_id: "",
  name: "",
  description: "",
  type: "host",
  content: "",
  enabled: true,
};

export function AliasesPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);
  const [typeFilter, setTypeFilter] = useState("");
  const [deviceFilter, setDeviceFilter] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Alias | null>(null);
  const [form, setForm] = useState<AliasFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Alias | null>(null);

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

  const aliasesQuery = useQuery({
    queryKey: qk.aliases.list(listParams),
    queryFn: () => aliasesApi.list(listParams),
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
    void queryClient.invalidateQueries({ queryKey: qk.aliases.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      if (editing) {
        const payload: AliasUpdatePayload = {
          description: form.description.trim() || null,
          content: parseLines(form.content),
          enabled: form.enabled,
        };
        return aliasesApi.update(editing.id, payload);
      }
      const payload: AliasPayload = {
        device_id: form.device_id || null,
        name: form.name.trim(),
        description: form.description.trim() || null,
        type: form.type,
        content: parseLines(form.content),
        enabled: form.enabled,
      };
      return aliasesApi.create(payload);
    },
    onSuccess: (alias) => {
      invalidate();
      setDialogOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(showToast({ message: `Alias ${alias.name} saved`, severity: "success" }));
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => aliasesApi.remove(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Alias deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreate = () => {
    setEditing(null);
    setForm({ ...EMPTY_FORM, device_id: deviceFilter || devices[0]?.id || "" });
    setFormError(null);
    setDialogOpen(true);
  };

  const openEdit = (alias: Alias) => {
    setEditing(alias);
    setForm({
      device_id: alias.device_id ?? "",
      name: alias.name,
      description: alias.description ?? "",
      type: alias.type as AliasType,
      content: alias.content.join("\n"),
      enabled: alias.enabled,
    });
    setFormError(null);
    setDialogOpen(true);
  };

  const columns: Array<DataTableColumn<Alias>> = [
    {
      key: "name",
      label: "Alias",
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <LabelOutlinedIcon fontSize="small" color="action" />
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
      key: "type",
      label: "Type",
      width: 130,
      render: (row) => <Chip size="small" variant="outlined" label={titleCase(row.type)} />,
    },
    {
      key: "content",
      label: "Content",
      render: (row) => (
        <Tooltip title={row.content.join(", ")}>
          <Box sx={{ maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            <Typography variant="body2" fontFamily="monospace" fontSize={12.5}>
              {row.content.length > 0 ? truncate(row.content.join(", "), 80) : EMPTY}
            </Typography>
          </Box>
        </Tooltip>
      ),
    },
    {
      key: "entries",
      label: "Entries",
      width: 90,
      align: "right",
      hideBelow: "md",
      render: (row) => formatNumber(row.content.length),
    },
    {
      key: "description",
      label: "Description",
      hideBelow: "lg",
      render: (row) => row.description ?? EMPTY,
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
          <PermissionGate permission="alias:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEdit(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="alias:write">
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

  return (
    <>
      <PageHeader
        title="Aliases"
        subtitle="Named host, network, port, URL and nested tables reused across firewall and NAT rules."
        actions={
          <PermissionGate permission="alias:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New alias
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${formatNumber(aliasesQuery.data?.meta.total ?? 0)} aliases`} />
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
        rows={aliasesQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={aliasesQuery.isLoading}
        error={aliasesQuery.error ? toApiError(aliasesQuery.error).message : null}
        onRetry={() => aliasesQuery.refetch()}
        page={page}
        size={size}
        total={aliasesQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        emptyTitle="No aliases"
        emptyDescription="Create reusable object groups and reference them from rules and NAT entries."
        emptyAction={
          <PermissionGate permission="alias:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New alias
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <TextField
              placeholder="Search name or description"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              sx={{ width: { xs: "100%", sm: 260 } }}
            />
            <TextField
              select
              label="Type"
              value={typeFilter}
              onChange={(event) => setTypeFilter(event.target.value)}
              sx={{ width: { xs: "100%", sm: 150 } }}
            >
              <MenuItem value="">All types</MenuItem>
              {ALIAS_TYPES.map((type) => (
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
        title={editing ? `Edit ${editing.name}` : "New alias"}
        loading={saveMutation.isPending}
        error={formError}
        submitLabel={editing ? "Save changes" : "Create alias"}
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
            helperText="Letters, digits and underscores"
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
            helperText="Leave empty for a tenant-wide alias"
            fullWidth
          >
            <MenuItem value="">Tenant-wide</MenuItem>
            {devices.map((device) => (
              <MenuItem key={device.id} value={device.id}>
                {device.name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Type"
            value={form.type}
            onChange={(event) => setForm((value) => ({ ...value, type: event.target.value as AliasType }))}
            disabled={Boolean(editing)}
            fullWidth
          >
            {ALIAS_TYPES.map((type) => (
              <MenuItem key={type.value} value={type.value}>
                {type.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <TextField
          label="Content"
          value={form.content}
          onChange={(event) => setForm((value) => ({ ...value, content: event.target.value }))}
          placeholder={CONTENT_PLACEHOLDERS[form.type]}
          helperText="One entry per line (or comma-separated)"
          multiline
          minRows={5}
          fullWidth
          inputProps={{ style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 13 } }}
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
        title="Delete alias"
        description={deleteTarget ? `Delete alias ${deleteTarget.name}?` : undefined}
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onClose={() => setDeleteTarget(null)}
      />
    </>
  );
}

export default AliasesPage;
