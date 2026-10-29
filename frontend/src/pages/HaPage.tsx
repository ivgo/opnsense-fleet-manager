import { useEffect, useMemo, useState } from "react";
import {
  Alert,
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
import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import RemoveCircleOutlineIcon from "@mui/icons-material/RemoveCircleOutline";
import SwapHorizOutlinedIcon from "@mui/icons-material/SwapHorizOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toApiError } from "@/api/client";
import { devicesApi, haApi, sitesApi } from "@/api/endpoints";
import { qk } from "@/api/queryKeys";
import type { HaCluster, HaClusterPayload, HaNodePayload, HaNodeRole } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { fromNow, titleCase } from "@/utils/format";

interface NodeFormState {
  device_id: string;
  role: HaNodeRole;
  advskew: number;
}

interface HaFormState {
  name: string;
  description: string;
  site_id: string;
  virtual_ip: string;
  interface: string;
  vhid: number;
  advbase: number;
  password: string;
  enabled: boolean;
  nodes: NodeFormState[];
}

const EMPTY_FORM: HaFormState = {
  name: "",
  description: "",
  site_id: "",
  virtual_ip: "",
  interface: "lan",
  vhid: 1,
  advbase: 1,
  password: "",
  enabled: true,
  nodes: [{ device_id: "", role: "primary", advskew: 0 }],
};

export function HaPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [search, setSearch] = useState("");

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<HaCluster | null>(null);
  const [form, setForm] = useState<HaFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<HaCluster | null>(null);
  const [failoverTarget, setFailoverTarget] = useState<HaCluster | null>(null);

  const listParams = useMemo(
    () => ({ page, size, sort: "name", order: "asc" as const, search: search.trim() || undefined }),
    [page, size, search],
  );

  const clustersQuery = useQuery({
    queryKey: qk.ha.list(listParams),
    queryFn: () => haApi.clusters(listParams),
    refetchInterval: 60_000,
  });

  const devicesQuery = useQuery({
    queryKey: qk.devices.list({ size: 200 }),
    queryFn: () => devicesApi.list({ size: 200 }),
    staleTime: 60_000,
  });

  const sitesQuery = useQuery({
    queryKey: qk.sites.list({ size: 200 }),
    queryFn: () => sitesApi.list({ size: 200 }),
    staleTime: 120_000,
  });

  useEffect(() => {
    setPage(1);
  }, [search]);

  const devices = devicesQuery.data?.items ?? [];
  const deviceName = (id: string) => devices.find((device) => device.id === id)?.name ?? id;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.ha.all });
    void queryClient.invalidateQueries({ queryKey: qk.devices.all });
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const nodes: HaNodePayload[] = form.nodes
        .filter((node) => node.device_id)
        .map((node) => ({ device_id: node.device_id, role: node.role, advskew: node.advskew }));
      if (editing) {
        return haApi.update(editing.id, {
          name: form.name.trim(),
          description: form.description.trim() || null,
          site_id: form.site_id || null,
          virtual_ip: form.virtual_ip.trim(),
          interface: form.interface.trim(),
          vhid: form.vhid,
          advbase: form.advbase,
          enabled: form.enabled,
          ...(form.password ? { password: form.password } : {}),
        });
      }
      const payload: HaClusterPayload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        site_id: form.site_id || null,
        virtual_ip: form.virtual_ip.trim(),
        interface: form.interface.trim(),
        vhid: form.vhid,
        advbase: form.advbase,
        password: form.password || null,
        enabled: form.enabled,
        nodes,
      };
      return haApi.create(payload);
    },
    onSuccess: (cluster) => {
      invalidate();
      setFormOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(showToast({ message: `CARP cluster ${cluster.name} saved`, severity: "success" }));
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => haApi.remove(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "CARP cluster deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const refreshMutation = useMutation({
    mutationFn: (id: string) => haApi.refresh(id),
    onSuccess: (cluster) => {
      invalidate();
      dispatch(
        showToast({
          message: `Cluster ${cluster.name}: ${titleCase(cluster.sync_status)}`,
          severity: cluster.sync_status === "in_sync" ? "success" : "info",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const failoverMutation = useMutation({
    mutationFn: (id: string) => haApi.failover(id),
    onSuccess: (result) => {
      invalidate();
      setFailoverTarget(null);
      dispatch(
        showToast({
          message: `${deviceName(result.promoted_device_id)} promoted to primary`,
          severity: result.applied ? "success" : "warning",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = (cluster: HaCluster) => {
    setEditing(cluster);
    setForm({
      name: cluster.name,
      description: cluster.description ?? "",
      site_id: cluster.site_id ?? "",
      virtual_ip: cluster.virtual_ip,
      interface: cluster.interface,
      vhid: cluster.vhid,
      advbase: cluster.advbase,
      password: "",
      enabled: cluster.enabled,
      nodes: cluster.nodes.map((node) => ({
        device_id: node.device_id,
        role: node.role,
        advskew: node.advskew,
      })),
    });
    setFormError(null);
    setFormOpen(true);
  };

  const updateNode = (index: number, patch: Partial<NodeFormState>) => {
    setForm((value) => ({
      ...value,
      nodes: value.nodes.map((node, position) =>
        position === index ? { ...node, ...patch } : node,
      ),
    }));
  };

  const columns: Array<DataTableColumn<HaCluster>> = [
    {
      key: "name",
      label: "Cluster",
      render: (row) => (
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" fontWeight={600} noWrap>
            {row.name}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap display="block">
            {row.description || `${row.nodes.length} node(s)`}
          </Typography>
        </Box>
      ),
    },
    {
      key: "virtual_ip",
      label: "Virtual IP",
      width: 210,
      render: (row) => (
        <Box>
          <Typography variant="body2" fontFamily="monospace">
            {row.virtual_ip}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {row.interface} · VHID {row.vhid} · advbase {row.advbase}
          </Typography>
        </Box>
      ),
    },
    {
      key: "nodes",
      label: "Nodes",
      hideBelow: "md",
      render: (row) =>
        row.nodes.length === 0 ? (
          <Typography variant="caption" color="text.disabled">No nodes</Typography>
        ) : (
          <Stack spacing={0.5}>
            {row.nodes.map((node) => (
              <Stack key={node.id} direction="row" spacing={0.75} alignItems="center">
                <Chip
                  size="small"
                  variant="outlined"
                  color={node.role === "primary" ? "primary" : "default"}
                  label={titleCase(node.role)}
                />
                <Typography variant="caption" noWrap>
                  {deviceName(node.device_id)}
                </Typography>
                <Typography variant="caption" color="text.disabled">
                  skew {node.advskew}
                </Typography>
              </Stack>
            ))}
          </Stack>
        ),
    },
    {
      key: "sync_status",
      label: "Sync",
      width: 150,
      render: (row) => (
        <Stack spacing={0.25}>
          <StatusChip
            status={row.sync_status}
            label={titleCase(row.sync_status)}
          />
          <Typography variant="caption" color="text.disabled">
            {row.last_sync_at ? fromNow(row.last_sync_at) : "Never polled"}
          </Typography>
        </Stack>
      ),
    },
    {
      key: "enabled",
      label: "State",
      width: 100,
      hideBelow: "lg",
      render: (row) => <StatusChip status={row.enabled ? "enabled" : "disabled"} />,
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 180,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <Tooltip title="Poll CARP state">
            <span>
              <IconButton
                size="small"
                disabled={refreshMutation.isPending}
                onClick={() => refreshMutation.mutate(row.id)}
              >
                <RefreshOutlinedIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
          <PermissionGate permission="ha:write">
            <Tooltip title="Fail over to secondary">
              <span>
                <IconButton size="small" onClick={() => setFailoverTarget(row)}>
                  <SwapHorizOutlinedIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEdit(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
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

  const clusters = clustersQuery.data?.items ?? [];
  const enabled = clusters.filter((cluster) => cluster.enabled).length;
  const drift = clusters.filter((cluster) => cluster.sync_status !== "in_sync").length;

  return (
    <>
      <PageHeader
        title="High availability"
        subtitle="CARP clusters on OPNsense pairs: virtual IPs, node roles, sync polling and controlled failover."
        actions={
          <PermissionGate permission="ha:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New cluster
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${clustersQuery.data?.meta.total ?? 0} clusters`} />
            <Chip size="small" variant="outlined" color="success" label={`${enabled} enabled`} />
            <Chip
              size="small"
              variant="outlined"
              color={drift > 0 ? "warning" : "default"}
              label={`${drift} not in sync`}
            />
          </Stack>
        }
      />

      <DataTable
        columns={columns}
        rows={clusters}
        getRowId={(row) => row.id}
        loading={clustersQuery.isLoading}
        error={clustersQuery.error ? toApiError(clustersQuery.error).message : null}
        onRetry={() => clustersQuery.refetch()}
        page={page}
        size={size}
        total={clustersQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        emptyTitle="No CARP clusters"
        emptyDescription="Pair two OPNsense devices into a CARP cluster to share a floating virtual IP."
        emptyAction={
          <PermissionGate permission="ha:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New cluster
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
            <TextField
              size="small"
              placeholder="Search clusters"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              sx={{ width: { xs: "100%", sm: 280 } }}
            />
            <Typography variant="caption" color="text.secondary">
              {clustersQuery.data?.meta.total ?? 0} clusters
            </Typography>
          </Stack>
        }
      />

      <FormDialog
        open={formOpen}
        title={editing ? `Edit ${editing.name}` : "New CARP cluster"}
        description={
          editing
            ? "Node membership is fixed after creation. Use failover to swap the primary and secondary roles."
            : "The first node becomes the primary unless another node is explicitly marked primary."
        }
        loading={saveMutation.isPending}
        error={formError}
        submitLabel={editing ? "Save changes" : "Create cluster"}
        submitDisabled={
          !form.name.trim() ||
          !form.virtual_ip.trim() ||
          (!editing && !form.nodes.some((node) => node.device_id))
        }
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
            label="Virtual IP"
            value={form.virtual_ip}
            onChange={(event) => setForm((value) => ({ ...value, virtual_ip: event.target.value }))}
            required
            placeholder="10.0.0.254"
            helperText="Floating CARP address shared by both nodes"
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
            label="Interface"
            value={form.interface}
            onChange={(event) => setForm((value) => ({ ...value, interface: event.target.value }))}
            required
            helperText="OPNsense interface name, e.g. lan"
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="VHID"
            type="number"
            value={form.vhid}
            onChange={(event) =>
              setForm((value) => ({
                ...value,
                vhid: Math.min(255, Math.max(1, Number(event.target.value) || 1)),
              }))
            }
            helperText="Virtual host ID (1–255), unique per interface"
            inputProps={{ min: 1, max: 255 }}
          />
          <TextField
            label="Advertisement base"
            type="number"
            value={form.advbase}
            onChange={(event) =>
              setForm((value) => ({
                ...value,
                advbase: Math.min(255, Math.max(1, Number(event.target.value) || 1)),
              }))
            }
            helperText="Seconds between advertisements"
            inputProps={{ min: 1, max: 255 }}
          />
          <TextField
            label={editing ? "New password (optional)" : "Password (optional)"}
            type="password"
            value={form.password}
            onChange={(event) => setForm((value) => ({ ...value, password: event.target.value }))}
            helperText="Stored encrypted; used for CARP authentication"
            autoComplete="new-password"
          />
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center">
          <TextField
            select
            label="Enabled"
            value={form.enabled ? "enabled" : "disabled"}
            onChange={(event) =>
              setForm((value) => ({ ...value, enabled: event.target.value === "enabled" }))
            }
            sx={{ minWidth: 160 }}
          >
            <MenuItem value="enabled">Enabled</MenuItem>
            <MenuItem value="disabled">Disabled</MenuItem>
          </TextField>
        </Stack>

        <Box>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle2">Nodes</Typography>
            {!editing && (
              <Button
                size="small"
                startIcon={<AddIcon />}
                onClick={() =>
                  setForm((value) => ({
                    ...value,
                    nodes: [
                      ...value.nodes,
                      {
                        device_id: "",
                        role: value.nodes.some((node) => node.role === "primary")
                          ? "secondary"
                          : "primary",
                        advskew: value.nodes.some((node) => node.role === "primary") ? 100 : 0,
                      },
                    ],
                  }))
                }
              >
                Add node
              </Button>
            )}
          </Stack>
          <Stack spacing={1.25}>
            {form.nodes.map((node, index) => (
              <Stack
                key={`${node.device_id}-${index}`}
                direction={{ xs: "column", sm: "row" }}
                spacing={1}
                alignItems={{ xs: "stretch", sm: "center" }}
              >
                <TextField
                  select
                  size="small"
                  label="Device"
                  value={node.device_id}
                  onChange={(event) => updateNode(index, { device_id: event.target.value })}
                  disabled={Boolean(editing)}
                  sx={{ flex: 1, minWidth: 200 }}
                >
                  {devices.map((device) => (
                    <MenuItem key={device.id} value={device.id}>
                      {device.name}
                      {device.ip_address ? ` · ${device.ip_address}` : ""}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  size="small"
                  label="Role"
                  value={node.role}
                  onChange={(event) =>
                    updateNode(index, { role: event.target.value as HaNodeRole })
                  }
                  disabled={Boolean(editing)}
                  sx={{ width: 150 }}
                >
                  <MenuItem value="primary">Primary</MenuItem>
                  <MenuItem value="secondary">Secondary</MenuItem>
                </TextField>
                <TextField
                  size="small"
                  label="Advskew"
                  type="number"
                  value={node.advskew}
                  onChange={(event) =>
                    updateNode(index, {
                      advskew: Math.min(254, Math.max(0, Number(event.target.value) || 0)),
                    })
                  }
                  disabled={Boolean(editing)}
                  inputProps={{ min: 0, max: 254 }}
                  sx={{ width: 120 }}
                />
                {!editing && (
                  <IconButton
                    size="small"
                    color="error"
                    disabled={form.nodes.length === 1}
                    onClick={() =>
                      setForm((value) => ({
                        ...value,
                        nodes: value.nodes.filter((_, position) => position !== index),
                      }))
                    }
                    aria-label="Remove node"
                  >
                    <RemoveCircleOutlineIcon fontSize="small" />
                  </IconButton>
                )}
              </Stack>
            ))}
          </Stack>
          {devices.length === 0 && (
            <Alert severity="warning" sx={{ mt: 1 }}>
              No devices are registered yet. Register devices before creating a CARP cluster.
            </Alert>
          )}
        </Box>
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete CARP cluster"
        description={
          deleteTarget
            ? `Delete ${deleteTarget.name}? The managed cluster definition is removed; device VIPs are not changed automatically.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onClose={() => setDeleteTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(failoverTarget)}
        title="Fail over CARP cluster"
        description={
          failoverTarget ? (
            <Stack spacing={1}>
              <Typography variant="body2">
                Promote the secondary node of {failoverTarget.name} to primary and demote the current
                primary? Both nodes are updated through the OPNsense VIP API.
              </Typography>
              <Alert severity="warning">
                Traffic on {failoverTarget.virtual_ip} may briefly drop while CARP re-converges.
              </Alert>
            </Stack>
          ) : undefined
        }
        confirmLabel="Fail over"
        confirmColor="warning"
        loading={failoverMutation.isPending}
        onConfirm={() => failoverTarget && failoverMutation.mutate(failoverTarget.id)}
        onClose={() => setFailoverTarget(null)}
      />
    </>
  );
}

export default HaPage;
