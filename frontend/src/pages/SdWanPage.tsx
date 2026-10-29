import { useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Divider,
  FormControlLabel,
  IconButton,
  ListItemText,
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
import HubOutlinedIcon from "@mui/icons-material/HubOutlined";
import RocketLaunchOutlinedIcon from "@mui/icons-material/RocketLaunchOutlined";
import SchemaOutlinedIcon from "@mui/icons-material/SchemaOutlined";
import SpeedOutlinedIcon from "@mui/icons-material/SpeedOutlined";
import SwapHorizOutlinedIcon from "@mui/icons-material/SwapHorizOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { devicesApi, sdwanApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type {
  SdwanLink,
  SteeringStrategy,
  Topology,
  TopologyGraph,
  TopologyPayload,
  TopologyType,
  TrafficPolicy,
  TrafficPolicyPayload,
  Tunnel,
  TunnelPayload,
  VpnProtocol,
} from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import {
  STEERING_STRATEGIES,
  TOPOLOGY_TYPES,
  TUNNEL_PROTOCOLS,
} from "@/utils/constants";
import { formatDateTime, fromNow, parseLines, prettyJson } from "@/utils/format";

interface TopologyFormState {
  name: string;
  description: string;
  topology_type: TopologyType;
  hub_device_ids: string[];
  spoke_device_ids: string[];
  routing_config: string;
}

const EMPTY_TOPOLOGY: TopologyFormState = {
  name: "",
  description: "",
  topology_type: "hub_spoke",
  hub_device_ids: [],
  spoke_device_ids: [],
  routing_config: '{\n  "protocol": "ospf",\n  "area": "0.0.0.0"\n}',
};

interface TunnelFormState {
  name: string;
  protocol: VpnProtocol;
  local_device_id: string;
  remote_device_id: string;
  interface_name: string;
  endpoint_local: string;
  endpoint_remote: string;
  allowed_ips: string;
  keepalive: string;
  mtu: string;
  wan_interface: string;
}

const EMPTY_TUNNEL: TunnelFormState = {
  name: "",
  protocol: "wireguard",
  local_device_id: "",
  remote_device_id: "",
  interface_name: "wg0",
  endpoint_local: "",
  endpoint_remote: "",
  allowed_ips: "10.255.0.0/24",
  keepalive: "25",
  mtu: "1420",
  wan_interface: "wan",
};

interface TrafficFormState {
  name: string;
  description: string;
  strategy: SteeringStrategy;
  match: string;
  priority: string;
  enabled: boolean;
}

const EMPTY_TRAFFIC: TrafficFormState = {
  name: "",
  description: "",
  strategy: "lowest_latency",
  match: '{\n  "applications": []\n}',
  priority: "100",
  enabled: true,
};

interface MeasurementFormState {
  latency_ms: string;
  jitter_ms: string;
  loss_pct: string;
  bandwidth_mbps: string;
  status: string;
}

const EMPTY_MEASUREMENT: MeasurementFormState = {
  latency_ms: "",
  jitter_ms: "",
  loss_pct: "",
  bandwidth_mbps: "",
  status: "active",
};

export function SdWanPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState(0);
  const [selectedTopologyId, setSelectedTopologyId] = useState("");
  const [graphTarget, setGraphTarget] = useState<Topology | null>(null);
  const [deployTarget, setDeployTarget] = useState<Topology | null>(null);
  const [deployDryRun, setDeployDryRun] = useState(true);
  const [regenerateKeys, setRegenerateKeys] = useState(false);

  const [topologyFormOpen, setTopologyFormOpen] = useState(false);
  const [editingTopology, setEditingTopology] = useState<Topology | null>(null);
  const [topologyForm, setTopologyForm] = useState<TopologyFormState>(EMPTY_TOPOLOGY);
  const [topologyError, setTopologyError] = useState<string | null>(null);
  const [deleteTopologyTarget, setDeleteTopologyTarget] = useState<Topology | null>(null);

  const [tunnelFormOpen, setTunnelFormOpen] = useState(false);
  const [tunnelForm, setTunnelForm] = useState<TunnelFormState>(EMPTY_TUNNEL);
  const [tunnelError, setTunnelError] = useState<string | null>(null);
  const [deleteTunnelTarget, setDeleteTunnelTarget] = useState<Tunnel | null>(null);

  const [trafficFormOpen, setTrafficFormOpen] = useState(false);
  const [trafficForm, setTrafficForm] = useState<TrafficFormState>(EMPTY_TRAFFIC);
  const [trafficError, setTrafficError] = useState<string | null>(null);
  const [deleteTrafficTarget, setDeleteTrafficTarget] = useState<TrafficPolicy | null>(null);

  const [measureTarget, setMeasureTarget] = useState<SdwanLink | null>(null);
  const [measureForm, setMeasureForm] = useState<MeasurementFormState>(EMPTY_MEASUREMENT);
  const [measureError, setMeasureError] = useState<string | null>(null);
  const [failoverResult, setFailoverResult] = useState<unknown>(null);

  const topologiesQuery = useQuery({
    queryKey: qk.sdwan.topologies({ size: 100 }),
    queryFn: () => sdwanApi.topologies({ size: 100 }),
    refetchInterval: 60_000,
  });

  const devicesQuery = useQuery({
    queryKey: qk.devices.list({ size: 500 }),
    queryFn: () => devicesApi.list({ size: 500 }),
    staleTime: 120_000,
  });

  const activeTopologyId = selectedTopologyId || topologiesQuery.data?.items[0]?.id || "";
  const activeTopology = useMemo(
    () => topologiesQuery.data?.items.find((topology) => topology.id === activeTopologyId) ?? null,
    [topologiesQuery.data, activeTopologyId],
  );

  const tunnelsQuery = useQuery({
    queryKey: qk.sdwan.tunnels(activeTopologyId),
    queryFn: () => sdwanApi.tunnels(activeTopologyId),
    enabled: Boolean(activeTopologyId) && tab === 1,
    refetchInterval: 45_000,
  });

  const linksQuery = useQuery({
    queryKey: qk.sdwan.links({ topology_id: activeTopologyId, size: 100 }),
    queryFn: () => sdwanApi.links({ topology_id: activeTopologyId, size: 100 }),
    enabled: Boolean(activeTopologyId) && tab === 2,
    refetchInterval: 45_000,
  });

  const trafficQuery = useQuery({
    queryKey: qk.sdwan.trafficPolicies({ topology_id: activeTopologyId, size: 100 }),
    queryFn: () => sdwanApi.trafficPolicies({ topology_id: activeTopologyId, size: 100 }),
    enabled: Boolean(activeTopologyId) && tab === 3,
  });

  const graphQuery = useQuery({
    queryKey: qk.sdwan.graph(graphTarget?.id ?? ""),
    queryFn: () => sdwanApi.graph(graphTarget?.id ?? ""),
    enabled: Boolean(graphTarget),
  });

  const deviceName = (id: string | null) =>
    id ? devicesQuery.data?.items.find((device) => device.id === id)?.name ?? id.slice(0, 8) : "—";

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.sdwan.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const saveTopologyMutation = useMutation({
    mutationFn: (payload: TopologyPayload) =>
      editingTopology ? sdwanApi.updateTopology(editingTopology.id, payload) : sdwanApi.createTopology(payload),
    onSuccess: (topology) => {
      invalidate();
      setTopologyFormOpen(false);
      setEditingTopology(null);
      setTopologyForm(EMPTY_TOPOLOGY);
      setTopologyError(null);
      setSelectedTopologyId(topology.id);
      dispatch(showToast({ message: `Topology ${topology.name} saved`, severity: "success" }));
    },
    onError: (error) => setTopologyError(toApiError(error).message),
  });

  const deleteTopologyMutation = useMutation({
    mutationFn: (id: string) => sdwanApi.removeTopology(id),
    onSuccess: () => {
      invalidate();
      setDeleteTopologyTarget(null);
      setSelectedTopologyId("");
      dispatch(showToast({ message: "Topology deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const deployMutation = useMutation({
    mutationFn: (topology: Topology) =>
      sdwanApi.deploy(topology.id, { dry_run: deployDryRun, regenerate_keys: regenerateKeys }),
    onSuccess: (result) => {
      invalidate();
      setDeployTarget(null);
      dispatch(
        showToast({
          message: `Deployment finished: ${result.tunnels_created} created, ${result.tunnels_updated} updated, ${result.routes_installed} routes, ${result.errors.length} error(s)`,
          severity: result.errors.length ? "warning" : "success",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const createTunnelMutation = useMutation({
    mutationFn: (payload: TunnelPayload) => sdwanApi.createTunnel(payload),
    onSuccess: () => {
      invalidate();
      setTunnelFormOpen(false);
      setTunnelForm(EMPTY_TUNNEL);
      setTunnelError(null);
      dispatch(showToast({ message: "Tunnel created", severity: "success" }));
    },
    onError: (error) => setTunnelError(toApiError(error).message),
  });

  const deleteTunnelMutation = useMutation({
    mutationFn: (id: string) => sdwanApi.removeTunnel(id),
    onSuccess: () => {
      invalidate();
      setDeleteTunnelTarget(null);
      dispatch(showToast({ message: "Tunnel deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const createTrafficMutation = useMutation({
    mutationFn: (payload: TrafficPolicyPayload) => sdwanApi.createTrafficPolicy(payload),
    onSuccess: () => {
      invalidate();
      setTrafficFormOpen(false);
      setTrafficForm(EMPTY_TRAFFIC);
      setTrafficError(null);
      dispatch(showToast({ message: "Steering policy created", severity: "success" }));
    },
    onError: (error) => setTrafficError(toApiError(error).message),
  });

  const deleteTrafficMutation = useMutation({
    mutationFn: (id: string) => sdwanApi.removeTrafficPolicy(id),
    onSuccess: () => {
      invalidate();
      setDeleteTrafficTarget(null);
      dispatch(showToast({ message: "Steering policy deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const measureMutation = useMutation({
    mutationFn: (link: SdwanLink) =>
      sdwanApi.measureLink(link.id, {
        latency_ms: measureForm.latency_ms ? Number(measureForm.latency_ms) : null,
        jitter_ms: measureForm.jitter_ms ? Number(measureForm.jitter_ms) : null,
        loss_pct: measureForm.loss_pct ? Number(measureForm.loss_pct) : null,
        bandwidth_mbps: measureForm.bandwidth_mbps ? Number(measureForm.bandwidth_mbps) : null,
        status: measureForm.status || null,
      }),
    onSuccess: () => {
      invalidate();
      setMeasureTarget(null);
      setMeasureForm(EMPTY_MEASUREMENT);
      setMeasureError(null);
      dispatch(showToast({ message: "Link measurement recorded", severity: "success" }));
    },
    onError: (error) => setMeasureError(toApiError(error).message),
  });

  const bestLinkMutation = useMutation({
    mutationFn: (topologyId: string) => sdwanApi.bestLink(topologyId),
    onSuccess: (link) => {
      setFailoverResult(
        link
          ? { selected_link: link.id, wan_interface: link.wan_interface, latency_ms: link.latency_ms, loss_pct: link.loss_pct }
          : { selected_link: null, reason: "No eligible link" },
      );
      dispatch(showToast({ message: link ? `Best link: ${link.wan_interface}` : "No eligible link", severity: "info" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const failoverMutation = useMutation({
    mutationFn: (topologyId: string) => sdwanApi.failover(topologyId),
    onSuccess: (result) => {
      setFailoverResult(result);
      invalidate();
      dispatch(
        showToast({ message: `Failover evaluation produced ${result.length} action(s)`, severity: "success" }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openTopologyCreate = () => {
    setEditingTopology(null);
    setTopologyForm(EMPTY_TOPOLOGY);
    setTopologyError(null);
    setTopologyFormOpen(true);
  };

  const openTopologyEdit = (topology: Topology) => {
    setEditingTopology(topology);
    setTopologyForm({
      name: topology.name,
      description: topology.description ?? "",
      topology_type: topology.topology_type,
      hub_device_ids: topology.hub_device_ids,
      spoke_device_ids: topology.spoke_device_ids,
      routing_config: prettyJson(topology.routing_config ?? {}),
    });
    setTopologyError(null);
    setTopologyFormOpen(true);
  };

  const submitTopology = () => {
    let routing: Record<string, unknown>;
    try {
      routing = topologyForm.routing_config.trim()
        ? (JSON.parse(topologyForm.routing_config) as Record<string, unknown>)
        : {};
    } catch {
      setTopologyError("Routing configuration must be valid JSON.");
      return;
    }
    saveTopologyMutation.mutate({
      name: topologyForm.name.trim(),
      description: topologyForm.description.trim() || null,
      topology_type: topologyForm.topology_type,
      hub_device_ids: topologyForm.hub_device_ids,
      spoke_device_ids: topologyForm.spoke_device_ids,
      routing_config: routing,
    });
  };

  const submitTunnel = () => {
    createTunnelMutation.mutate({
      topology_id: activeTopologyId,
      name: tunnelForm.name.trim(),
      protocol: tunnelForm.protocol,
      local_device_id: tunnelForm.local_device_id,
      remote_device_id: tunnelForm.remote_device_id || null,
      interface_name: tunnelForm.interface_name.trim() || null,
      endpoint_local: tunnelForm.endpoint_local.trim() || null,
      endpoint_remote: tunnelForm.endpoint_remote.trim() || null,
      allowed_ips: parseLines(tunnelForm.allowed_ips),
      keepalive: Number(tunnelForm.keepalive) || 25,
      mtu: tunnelForm.mtu ? Number(tunnelForm.mtu) : null,
      wan_interface: tunnelForm.wan_interface.trim() || null,
    });
  };

  const submitTraffic = () => {
    let match: Record<string, unknown>;
    try {
      match = trafficForm.match.trim() ? (JSON.parse(trafficForm.match) as Record<string, unknown>) : {};
    } catch {
      setTrafficError("Match criteria must be valid JSON.");
      return;
    }
    createTrafficMutation.mutate({
      topology_id: activeTopologyId,
      name: trafficForm.name.trim(),
      description: trafficForm.description.trim() || null,
      strategy: trafficForm.strategy,
      match,
      priority: Number(trafficForm.priority) || 100,
      enabled: trafficForm.enabled,
    });
  };

  const topologyColumns: Array<DataTableColumn<Topology>> = [
    {
      key: "name",
      label: "Topology",
      render: (row) => (
        <Box>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" fontWeight={600}>
              {row.name}
            </Typography>
            {row.id === activeTopologyId && <Chip size="small" color="primary" label="selected" />}
          </Stack>
          <Typography variant="caption" color="text.secondary" display="block">
            {row.description ?? "No description"}
          </Typography>
        </Box>
      ),
    },
    { key: "type", label: "Type", width: 130, render: (row) => <Chip size="small" variant="outlined" label={row.topology_type} /> },
    { key: "status", label: "Status", width: 120, render: (row) => <StatusChip status={row.status} /> },
    {
      key: "nodes",
      label: "Hubs / spokes",
      width: 130,
      align: "center",
      render: (row) => `${row.hub_device_ids.length} / ${row.spoke_device_ids.length}`,
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 200,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <Tooltip title="View graph">
            <IconButton size="small" onClick={() => setGraphTarget(row)}>
              <SchemaOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <PermissionGate permission="sdwan:deploy">
            <Tooltip title="Deploy topology">
              <IconButton
                size="small"
                onClick={() => {
                  setDeployTarget(row);
                  setDeployDryRun(true);
                  setRegenerateKeys(false);
                }}
              >
                <RocketLaunchOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="sdwan:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openTopologyEdit(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="sdwan:write">
            <Tooltip title="Delete">
              <IconButton size="small" color="error" onClick={() => setDeleteTopologyTarget(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        </Stack>
      ),
    },
  ];

  const tunnelColumns: Array<DataTableColumn<Tunnel>> = [
    {
      key: "name",
      label: "Tunnel",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.name}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {row.interface_name ?? "auto"} · {row.protocol}
          </Typography>
        </Box>
      ),
    },
    {
      key: "path",
      label: "Path",
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <Chip size="small" variant="outlined" label={deviceName(row.local_device_id)} />
          <SwapHorizOutlinedIcon fontSize="small" color="action" />
          <Chip size="small" variant="outlined" label={deviceName(row.remote_device_id)} />
        </Stack>
      ),
    },
    { key: "status", label: "Status", width: 110, render: (row) => <StatusChip status={row.status} /> },
    {
      key: "health",
      label: "Health",
      width: 110,
      render: (row) => <StatusChip status={row.health_status} />,
    },
    {
      key: "handshake",
      label: "Last handshake",
      width: 160,
      hideBelow: "md",
      render: (row) => (row.last_handshake_at ? fromNow(row.last_handshake_at) : "—"),
    },
    {
      key: "endpoints",
      label: "Endpoints",
      hideBelow: "lg",
      monospace: true,
      render: (row) => `${row.endpoint_local ?? "?"} ↔ ${row.endpoint_remote ?? "?"}`,
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 70,
      render: (row) => (
        <PermissionGate permission="sdwan:write">
          <Tooltip title="Delete tunnel">
            <IconButton size="small" color="error" onClick={() => setDeleteTunnelTarget(row)}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </PermissionGate>
      ),
    },
  ];

  const linkColumns: Array<DataTableColumn<SdwanLink>> = [
    {
      key: "wan_interface",
      label: "WAN link",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.wan_interface}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {deviceName(row.local_device_id)} → {deviceName(row.remote_device_id)}
          </Typography>
        </Box>
      ),
    },
    { key: "status", label: "Status", width: 110, render: (row) => <StatusChip status={row.status} /> },
    {
      key: "latency",
      label: "Latency",
      width: 110,
      align: "right",
      render: (row) => (row.latency_ms !== null ? `${row.latency_ms.toFixed(1)} ms` : "—"),
    },
    {
      key: "loss",
      label: "Loss",
      width: 100,
      align: "right",
      render: (row) => (row.loss_pct !== null ? `${row.loss_pct.toFixed(2)}%` : "—"),
    },
    {
      key: "bandwidth",
      label: "Bandwidth",
      width: 120,
      align: "right",
      hideBelow: "md",
      render: (row) => (row.bandwidth_mbps !== null ? `${row.bandwidth_mbps.toFixed(0)} Mbps` : "—"),
    },
    {
      key: "sla",
      label: "SLA",
      width: 160,
      hideBelow: "lg",
      render: (row) => `${row.sla_latency_ms} ms / ${row.sla_loss_pct}%`,
    },
    {
      key: "priority",
      label: "Priority / cost",
      width: 130,
      hideBelow: "lg",
      align: "center",
      render: (row) => `${row.priority} / ${row.cost}`,
    },
    {
      key: "measured",
      label: "Measured",
      width: 140,
      hideBelow: "lg",
      render: (row) => (row.measured_at ? fromNow(row.measured_at) : "—"),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 80,
      render: (row) => (
        <PermissionGate permission="sdwan:write">
          <Tooltip title="Record measurement">
            <IconButton
              size="small"
              onClick={() => {
                setMeasureTarget(row);
                setMeasureForm({
                  latency_ms: row.latency_ms !== null ? String(row.latency_ms) : "",
                  jitter_ms: row.jitter_ms !== null ? String(row.jitter_ms) : "",
                  loss_pct: row.loss_pct !== null ? String(row.loss_pct) : "",
                  bandwidth_mbps: row.bandwidth_mbps !== null ? String(row.bandwidth_mbps) : "",
                  status: row.status,
                });
                setMeasureError(null);
              }}
            >
              <SpeedOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </PermissionGate>
      ),
    },
  ];

  const trafficColumns: Array<DataTableColumn<TrafficPolicy>> = [
    {
      key: "name",
      label: "Steering policy",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.name}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {row.description ?? "No description"}
          </Typography>
        </Box>
      ),
    },
    { key: "strategy", label: "Strategy", width: 170, render: (row) => <Chip size="small" label={row.strategy} /> },
    {
      key: "match",
      label: "Match",
      hideBelow: "md",
      monospace: true,
      render: (row) => prettyJson(row.match).replace(/\s+/g, " ").slice(0, 90),
    },
    { key: "priority", label: "Priority", width: 100, align: "center", render: (row) => row.priority },
    {
      key: "enabled",
      label: "Enabled",
      width: 100,
      render: (row) => <StatusChip status={row.enabled ? "enabled" : "disabled"} />,
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 70,
      render: (row) => (
        <PermissionGate permission="sdwan:write">
          <Tooltip title="Delete policy">
            <IconButton size="small" color="error" onClick={() => setDeleteTrafficTarget(row)}>
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </PermissionGate>
      ),
    },
  ];

  const topologies = topologiesQuery.data?.items ?? [];
  const devices = devicesQuery.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="SD-WAN"
        subtitle="Hub-and-spoke and mesh overlays over WireGuard, IPsec and OpenVPN with SLA-driven steering."
        actions={
          <PermissionGate permission="sdwan:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openTopologyCreate}>
              New topology
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" icon={<HubOutlinedIcon />} label={`${topologies.length} topologies`} />
            <Chip size="small" variant="outlined" label={`${tunnelsQuery.data?.length ?? 0} tunnels`} />
            <Chip size="small" variant="outlined" label={`${linksQuery.data?.meta.total ?? 0} links`} />
            <Chip size="small" variant="outlined" label={`${trafficQuery.data?.meta.total ?? 0} steering policies`} />
          </Stack>
        }
      />

      <Stack
        direction={{ xs: "column", md: "row" }}
        spacing={1.5}
        alignItems={{ xs: "stretch", md: "center" }}
        sx={{ mb: 2 }}
      >
        <TextField
          select
          label="Active topology"
          value={activeTopologyId}
          onChange={(event) => setSelectedTopologyId(event.target.value)}
          sx={{ minWidth: 280 }}
          disabled={topologies.length === 0}
        >
          {topologies.map((topology) => (
            <MenuItem key={topology.id} value={topology.id}>
              {topology.name} · {topology.topology_type}
            </MenuItem>
          ))}
        </TextField>
        {activeTopology && (
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <StatusChip status={activeTopology.status} />
            <Chip
              size="small"
              variant="outlined"
              label={`${activeTopology.hub_device_ids.length} hubs · ${activeTopology.spoke_device_ids.length} spokes`}
            />
            <Button size="small" startIcon={<SchemaOutlinedIcon />} onClick={() => setGraphTarget(activeTopology)}>
              Graph
            </Button>
            <PermissionGate permission="sdwan:deploy">
              <Button
                size="small"
                startIcon={<RocketLaunchOutlinedIcon />}
                onClick={() => {
                  setDeployTarget(activeTopology);
                  setDeployDryRun(true);
                  setRegenerateKeys(false);
                }}
              >
                Deploy
              </Button>
            </PermissionGate>
          </Stack>
        )}
      </Stack>

      <Tabs value={tab} onChange={(_event, value: number) => setTab(value)} sx={{ mb: 2 }}>
        <Tab label="Topologies" />
        <Tab label="Tunnels" />
        <Tab label="WAN links" />
        <Tab label="Steering" />
      </Tabs>

      {tab === 0 && (
        <DataTable
          columns={topologyColumns}
          rows={topologies}
          getRowId={(row) => row.id}
          loading={topologiesQuery.isLoading}
          error={topologiesQuery.error ? toApiError(topologiesQuery.error).message : null}
          onRetry={() => topologiesQuery.refetch()}
          onRowClick={(row) => setSelectedTopologyId(row.id)}
          emptyTitle="No SD-WAN topologies"
          emptyDescription="Create a topology to define hubs, spokes and automatic tunnel provisioning."
          emptyAction={
            <PermissionGate permission="sdwan:write">
              <Button variant="contained" startIcon={<AddIcon />} onClick={openTopologyCreate}>
                New topology
              </Button>
            </PermissionGate>
          }
          toolbar={
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Box>
                <Typography variant="h5">Overlay topologies</Typography>
                <Typography variant="caption" color="text.secondary">
                  Select a topology to manage its tunnels, links and steering rules
                </Typography>
              </Box>
              <Typography variant="caption" color="text.secondary">
                {topologies.length} topologies
              </Typography>
            </Stack>
          }
        />
      )}

      {tab === 1 && (
        <Stack spacing={2}>
          {!activeTopology ? (
            <Alert severity="info">Create or select a topology before adding tunnels.</Alert>
          ) : (
            <DataTable
              columns={tunnelColumns}
              rows={tunnelsQuery.data ?? []}
              getRowId={(row) => row.id}
              loading={tunnelsQuery.isLoading}
              error={tunnelsQuery.error ? toApiError(tunnelsQuery.error).message : null}
              onRetry={() => tunnelsQuery.refetch()}
              emptyTitle="No tunnels"
              emptyDescription={`${activeTopology.name} has no tunnels yet. Deploy the topology or add a tunnel manually.`}
              toolbar={
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Box>
                    <Typography variant="h5">Tunnels · {activeTopology.name}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Overlay endpoints, handshake health and interface assignment
                    </Typography>
                  </Box>
                  <PermissionGate permission="sdwan:write">
                    <Button
                      size="small"
                      startIcon={<AddIcon />}
                      onClick={() => {
                        setTunnelForm({
                          ...EMPTY_TUNNEL,
                          local_device_id: activeTopology.hub_device_ids[0] ?? "",
                        });
                        setTunnelError(null);
                        setTunnelFormOpen(true);
                      }}
                    >
                      Add tunnel
                    </Button>
                  </PermissionGate>
                </Stack>
              }
            />
          )}
        </Stack>
      )}

      {tab === 2 && (
        <Stack spacing={2}>
          {!activeTopology ? (
            <Alert severity="info">Create or select a topology to inspect WAN links.</Alert>
          ) : (
            <>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <PermissionGate permission="sdwan:deploy">
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<SwapHorizOutlinedIcon />}
                    onClick={() => failoverMutation.mutate(activeTopology.id)}
                    disabled={failoverMutation.isPending}
                  >
                    Evaluate failover
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<SpeedOutlinedIcon />}
                    onClick={() => bestLinkMutation.mutate(activeTopology.id)}
                    disabled={bestLinkMutation.isPending}
                  >
                    Select best link
                  </Button>
                </PermissionGate>
                <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
                  SLA thresholds are evaluated against the latest measurements.
                </Typography>
              </Stack>
              {failoverResult !== null && (
                <Box>
                  <CodeBlock code={prettyJson(failoverResult)} language="json" maxHeight={220} />
                </Box>
              )}
              <DataTable
                columns={linkColumns}
                rows={linksQuery.data?.items ?? []}
                getRowId={(row) => row.id}
                loading={linksQuery.isLoading}
                error={linksQuery.error ? toApiError(linksQuery.error).message : null}
                onRetry={() => linksQuery.refetch()}
                emptyTitle="No measured links"
                emptyDescription="Links appear after topology deployment and agent measurement reports."
              />
            </>
          )}
        </Stack>
      )}

      {tab === 3 && (
        <Stack spacing={2}>
          {!activeTopology ? (
            <Alert severity="info">Create or select a topology before adding steering policies.</Alert>
          ) : (
            <DataTable
              columns={trafficColumns}
              rows={trafficQuery.data?.items ?? []}
              getRowId={(row) => row.id}
              loading={trafficQuery.isLoading}
              error={trafficQuery.error ? toApiError(trafficQuery.error).message : null}
              onRetry={() => trafficQuery.refetch()}
              emptyTitle="No steering policies"
              emptyDescription="Define application-aware steering, latency preferences or failover behaviour."
              toolbar={
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Box>
                    <Typography variant="h5">Steering · {activeTopology.name}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Policies are evaluated in priority order
                    </Typography>
                  </Box>
                  <PermissionGate permission="sdwan:write">
                    <Button
                      size="small"
                      startIcon={<AddIcon />}
                      onClick={() => {
                        setTrafficForm(EMPTY_TRAFFIC);
                        setTrafficError(null);
                        setTrafficFormOpen(true);
                      }}
                    >
                      Add policy
                    </Button>
                  </PermissionGate>
                </Stack>
              }
            />
          )}
        </Stack>
      )}

      <FormDialog
        open={topologyFormOpen}
        title={editingTopology ? `Edit ${editingTopology.name}` : "New topology"}
        description={
          <Typography variant="body2" color="text.secondary">
            Hubs terminate tunnels; spokes connect to the nearest hub. Keys and addresses are generated by the
            controller at deployment time.
          </Typography>
        }
        submitLabel={editingTopology ? "Save changes" : "Create topology"}
        loading={saveTopologyMutation.isPending}
        error={topologyError}
        submitDisabled={!topologyForm.name.trim() || !topologyForm.topology_type}
        onSubmit={submitTopology}
        onClose={() => {
          setTopologyFormOpen(false);
          setEditingTopology(null);
        }}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Name"
            value={topologyForm.name}
            onChange={(event) => setTopologyForm((value) => ({ ...value, name: event.target.value }))}
            required
            autoFocus
          />
          <TextField
            select
            label="Type"
            value={topologyForm.topology_type}
            onChange={(event) =>
              setTopologyForm((value) => ({ ...value, topology_type: event.target.value as TopologyType }))
            }
          >
            {TOPOLOGY_TYPES.map((type) => (
              <MenuItem key={type.value} value={type.value}>
                {type.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <TextField
          label="Description"
          value={topologyForm.description}
          onChange={(event) => setTopologyForm((value) => ({ ...value, description: event.target.value }))}
        />
        <TextField
          select
          label="Hub devices"
          value={topologyForm.hub_device_ids}
          onChange={(event) => {
            const value = event.target.value;
            setTopologyForm((formValue) => ({
              ...formValue,
              hub_device_ids: typeof value === "string" ? value.split(",") : value,
            }));
          }}
          SelectProps={{ multiple: true, renderValue: (selected) => (
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
              {(selected as string[]).map((id) => (
                <Chip key={id} size="small" label={deviceName(id)} />
              ))}
            </Stack>
          ) }}
          helperText="Devices that terminate the overlay and advertise routes"
        >
          {devices.map((device) => (
            <MenuItem key={device.id} value={device.id}>
              <Checkbox checked={topologyForm.hub_device_ids.includes(device.id)} />
              <ListItemText primary={device.name} secondary={device.ip_address ?? undefined} />
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Spoke devices"
          value={topologyForm.spoke_device_ids}
          onChange={(event) => {
            const value = event.target.value;
            setTopologyForm((formValue) => ({
              ...formValue,
              spoke_device_ids: typeof value === "string" ? value.split(",") : value,
            }));
          }}
          SelectProps={{ multiple: true, renderValue: (selected) => (
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
              {(selected as string[]).map((id) => (
                <Chip key={id} size="small" label={deviceName(id)} />
              ))}
            </Stack>
          ) }}
          helperText="Branch appliances that connect to the hubs"
        >
          {devices.map((device) => (
            <MenuItem key={device.id} value={device.id}>
              <Checkbox checked={topologyForm.spoke_device_ids.includes(device.id)} />
              <ListItemText primary={device.name} secondary={device.ip_address ?? undefined} />
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Routing configuration (JSON)"
          value={topologyForm.routing_config}
          onChange={(event) =>
            setTopologyForm((value) => ({ ...value, routing_config: event.target.value }))
          }
          multiline
          minRows={5}
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 12.5 },
          }}
        />
      </FormDialog>

      <FormDialog
        open={tunnelFormOpen}
        title="Add tunnel"
        submitLabel="Create tunnel"
        loading={createTunnelMutation.isPending}
        error={tunnelError}
        submitDisabled={
          !tunnelForm.name.trim() || !tunnelForm.local_device_id || !tunnelForm.remote_device_id
        }
        onSubmit={submitTunnel}
        onClose={() => setTunnelFormOpen(false)}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Name"
            value={tunnelForm.name}
            onChange={(event) => setTunnelForm((value) => ({ ...value, name: event.target.value }))}
            required
            autoFocus
          />
          <TextField
            select
            label="Protocol"
            value={tunnelForm.protocol}
            onChange={(event) =>
              setTunnelForm((value) => ({ ...value, protocol: event.target.value as VpnProtocol }))
            }
          >
            {TUNNEL_PROTOCOLS.map((protocol) => (
              <MenuItem key={protocol.value} value={protocol.value}>
                {protocol.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Local device"
            value={tunnelForm.local_device_id}
            onChange={(event) =>
              setTunnelForm((value) => ({ ...value, local_device_id: event.target.value }))
            }
            required
          >
            {devices.map((device) => (
              <MenuItem key={device.id} value={device.id}>
                {device.name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Remote device"
            value={tunnelForm.remote_device_id}
            onChange={(event) =>
              setTunnelForm((value) => ({ ...value, remote_device_id: event.target.value }))
            }
            required
          >
            {devices.map((device) => (
              <MenuItem key={device.id} value={device.id}>
                {device.name}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Local endpoint"
            value={tunnelForm.endpoint_local}
            onChange={(event) =>
              setTunnelForm((value) => ({ ...value, endpoint_local: event.target.value }))
            }
            placeholder="203.0.113.10:51820"
          />
          <TextField
            label="Remote endpoint"
            value={tunnelForm.endpoint_remote}
            onChange={(event) =>
              setTunnelForm((value) => ({ ...value, endpoint_remote: event.target.value }))
            }
            placeholder="198.51.100.20:51820"
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Interface"
            value={tunnelForm.interface_name}
            onChange={(event) =>
              setTunnelForm((value) => ({ ...value, interface_name: event.target.value }))
            }
          />
          <TextField
            label="WAN interface"
            value={tunnelForm.wan_interface}
            onChange={(event) =>
              setTunnelForm((value) => ({ ...value, wan_interface: event.target.value }))
            }
          />
          <TextField
            label="Keepalive (s)"
            value={tunnelForm.keepalive}
            onChange={(event) => setTunnelForm((value) => ({ ...value, keepalive: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
          />
          <TextField
            label="MTU"
            value={tunnelForm.mtu}
            onChange={(event) => setTunnelForm((value) => ({ ...value, mtu: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
          />
        </Stack>
        <TextField
          label="Allowed IPs"
          value={tunnelForm.allowed_ips}
          onChange={(event) => setTunnelForm((value) => ({ ...value, allowed_ips: event.target.value }))}
          helperText="Comma-separated CIDR blocks routed through this tunnel"
        />
      </FormDialog>

      <FormDialog
        open={trafficFormOpen}
        title="Add steering policy"
        submitLabel="Create policy"
        loading={createTrafficMutation.isPending}
        error={trafficError}
        submitDisabled={!trafficForm.name.trim()}
        onSubmit={submitTraffic}
        onClose={() => setTrafficFormOpen(false)}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Name"
            value={trafficForm.name}
            onChange={(event) => setTrafficForm((value) => ({ ...value, name: event.target.value }))}
            required
            autoFocus
          />
          <TextField
            select
            label="Strategy"
            value={trafficForm.strategy}
            onChange={(event) =>
              setTrafficForm((value) => ({ ...value, strategy: event.target.value as SteeringStrategy }))
            }
          >
            {STEERING_STRATEGIES.map((strategy) => (
              <MenuItem key={strategy.value} value={strategy.value}>
                {strategy.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Priority"
            value={trafficForm.priority}
            onChange={(event) => setTrafficForm((value) => ({ ...value, priority: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
          />
        </Stack>
        <TextField
          label="Description"
          value={trafficForm.description}
          onChange={(event) => setTrafficForm((value) => ({ ...value, description: event.target.value }))}
        />
        <TextField
          label="Match criteria (JSON)"
          value={trafficForm.match}
          onChange={(event) => setTrafficForm((value) => ({ ...value, match: event.target.value }))}
          multiline
          minRows={6}
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 12.5 },
          }}
          helperText='Examples: {"applications": ["teams"]}, {"destinations": ["10.10.0.0/16"]}'
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={trafficForm.enabled}
              onChange={(event) => setTrafficForm((value) => ({ ...value, enabled: event.target.checked }))}
            />
          }
          label="Enabled"
        />
      </FormDialog>

      <FormDialog
        open={Boolean(measureTarget)}
        title={`Measure ${measureTarget?.wan_interface ?? "link"}`}
        description={
          <Typography variant="body2" color="text.secondary">
            Measurements feed SLA evaluation and steering decisions. Leave a field blank to keep its current
            value.
          </Typography>
        }
        submitLabel="Record"
        loading={measureMutation.isPending}
        error={measureError}
        onSubmit={() => measureTarget && measureMutation.mutate(measureTarget)}
        onClose={() => setMeasureTarget(null)}
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Latency (ms)"
            value={measureForm.latency_ms}
            onChange={(event) => setMeasureForm((value) => ({ ...value, latency_ms: event.target.value }))}
            inputProps={{ inputMode: "decimal" }}
          />
          <TextField
            label="Jitter (ms)"
            value={measureForm.jitter_ms}
            onChange={(event) => setMeasureForm((value) => ({ ...value, jitter_ms: event.target.value }))}
            inputProps={{ inputMode: "decimal" }}
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Loss (%)"
            value={measureForm.loss_pct}
            onChange={(event) => setMeasureForm((value) => ({ ...value, loss_pct: event.target.value }))}
            inputProps={{ inputMode: "decimal" }}
          />
          <TextField
            label="Bandwidth (Mbps)"
            value={measureForm.bandwidth_mbps}
            onChange={(event) =>
              setMeasureForm((value) => ({ ...value, bandwidth_mbps: event.target.value }))
            }
            inputProps={{ inputMode: "decimal" }}
          />
        </Stack>
        <TextField
          select
          label="Status"
          value={measureForm.status}
          onChange={(event) => setMeasureForm((value) => ({ ...value, status: event.target.value }))}
        >
          <MenuItem value="active">Active</MenuItem>
          <MenuItem value="down">Down</MenuItem>
          <MenuItem value="degraded">Degraded</MenuItem>
          <MenuItem value="pending">Pending</MenuItem>
        </TextField>
      </FormDialog>

      <FormDialog
        open={Boolean(graphTarget)}
        title={`Topology graph · ${graphTarget?.name ?? ""}`}
        submitLabel="Close"
        onSubmit={() => setGraphTarget(null)}
        onClose={() => setGraphTarget(null)}
        maxWidth="md"
      >
        {graphQuery.isLoading && <Typography variant="body2">Building graph…</Typography>}
        {graphQuery.isError && <Alert severity="error">{toApiError(graphQuery.error).message}</Alert>}
        {graphQuery.data && <GraphView graph={graphQuery.data} />}
      </FormDialog>

      <FormDialog
        open={Boolean(deployTarget)}
        title={`Deploy ${deployTarget?.name ?? ""}`}
        description={
          <Typography variant="body2" color="text.secondary">
            Deployment provisions tunnels, exchanges keys, installs routes and applies steering rules on
            every member device. Dry run produces the plan without changes.
          </Typography>
        }
        submitLabel={deployDryRun ? "Run dry run" : "Deploy"}
        loading={deployMutation.isPending}
        onSubmit={() => deployTarget && deployMutation.mutate(deployTarget)}
        onClose={() => setDeployTarget(null)}
      >
        <FormControlLabel
          control={
            <Checkbox checked={deployDryRun} onChange={(event) => setDeployDryRun(event.target.checked)} />
          }
          label="Dry run"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={regenerateKeys}
              onChange={(event) => setRegenerateKeys(event.target.checked)}
            />
          }
          label="Regenerate tunnel keys (rotates WireGuard keypairs)"
        />
        {deployTarget && (
          <Box sx={{ p: 1.5, border: 1, borderColor: "divider", borderRadius: 1.5 }}>
            <Typography variant="caption" color="text.secondary">
              {deployTarget.hub_device_ids.length} hub(s) · {deployTarget.spoke_device_ids.length} spoke(s) ·{" "}
              {prettyJson(deployTarget.routing_config).replace(/\s+/g, " ")}
            </Typography>
          </Box>
        )}
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTopologyTarget)}
        title="Delete topology"
        description={
          deleteTopologyTarget
            ? `Delete ${deleteTopologyTarget.name}? Tunnels, links and steering policies are removed from OFME. Device configuration is not reverted automatically.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteTopologyMutation.isPending}
        onConfirm={() => deleteTopologyTarget && deleteTopologyMutation.mutate(deleteTopologyTarget.id)}
        onClose={() => setDeleteTopologyTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(deleteTunnelTarget)}
        title="Delete tunnel"
        description={
          deleteTunnelTarget
            ? `Delete ${deleteTunnelTarget.name}? The tunnel is removed on the next topology deployment.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteTunnelMutation.isPending}
        onConfirm={() => deleteTunnelTarget && deleteTunnelMutation.mutate(deleteTunnelTarget.id)}
        onClose={() => setDeleteTunnelTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(deleteTrafficTarget)}
        title="Delete steering policy"
        description={
          deleteTrafficTarget
            ? `Delete ${deleteTrafficTarget.name}? Traffic falls back to the next matching policy or default routing.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteTrafficMutation.isPending}
        onConfirm={() => deleteTrafficTarget && deleteTrafficMutation.mutate(deleteTrafficTarget.id)}
        onClose={() => setDeleteTrafficTarget(null)}
      />

      {activeTopology && (
        <Box sx={{ mt: 2 }}>
          <Alert severity="info" variant="outlined">
            <Typography variant="body2">
              Topology <strong>{activeTopology.name}</strong> was updated{" "}
              {formatDateTime(activeTopology.updated_at)}. SD-WAN health sweeps run every minute and move
              links outside their SLA to degraded state automatically.
            </Typography>
          </Alert>
        </Box>
      )}
    </>
  );
}

function GraphView({ graph }: { graph: TopologyGraph }) {
  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Chip size="small" label={graph.name} />
        <Chip size="small" variant="outlined" label={graph.type} />
        <Chip size="small" variant="outlined" label={`${graph.nodes.length} nodes`} />
        <Chip size="small" variant="outlined" label={`${graph.edges.length} edges`} />
      </Stack>
      <Divider />
      <Box sx={{ display: "grid", gap: 1.5, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" } }}>
        <Box>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Nodes
          </Typography>
          <Stack spacing={1}>
            {graph.nodes.map((node) => (
              <Stack
                key={node.id}
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                sx={{ p: 1.25, border: 1, borderColor: "divider", borderRadius: 1.5 }}
              >
                <Box>
                  <Typography variant="body2" fontWeight={600}>
                    {node.name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {node.role} · {node.site ?? "no site"}
                  </Typography>
                </Box>
                <StatusChip status={node.status} />
              </Stack>
            ))}
          </Stack>
        </Box>
        <Box>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Edges
          </Typography>
          <Stack spacing={1}>
            {graph.edges.map((edge) => (
              <Stack
                key={edge.id}
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                sx={{ p: 1.25, border: 1, borderColor: "divider", borderRadius: 1.5 }}
              >
                <Box>
                  <Typography variant="body2" fontFamily="monospace">
                    {edge.source.slice(0, 8)} → {edge.target.slice(0, 8)}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {edge.latency_ms !== null ? `${edge.latency_ms.toFixed(1)} ms` : "latency n/a"}
                    {edge.loss_pct !== null ? ` · ${edge.loss_pct.toFixed(2)}% loss` : ""}
                  </Typography>
                </Box>
                <StatusChip status={edge.health || edge.status} />
              </Stack>
            ))}
          </Stack>
        </Box>
      </Box>
    </Stack>
  );
}

export default SdWanPage;
