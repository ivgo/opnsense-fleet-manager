import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid,
  IconButton,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
  alpha,
  useTheme,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import LanIcon from "@mui/icons-material/Lan";
import PauseCircleOutlineIcon from "@mui/icons-material/PauseCircleOutline";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import RadarOutlinedIcon from "@mui/icons-material/RadarOutlined";
import RestartAltOutlinedIcon from "@mui/icons-material/RestartAltOutlined";
import SecurityIcon from "@mui/icons-material/Security";
import SystemUpdateAltOutlinedIcon from "@mui/icons-material/SystemUpdateAltOutlined";
import VpnKeyIcon from "@mui/icons-material/VpnKey";
import WorkspacePremiumOutlinedIcon from "@mui/icons-material/WorkspacePremiumOutlined";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { certificatesApi, deviceSdwanApi, devicesApi, metricsApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { Certificate, DeviceCommandAction, DeviceCommandStatus, DeviceUpdate } from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import DetailGrid, { SectionCard } from "@/components/DetailGrid";
import ErrorState from "@/components/ErrorState";
import FormDialog from "@/components/FormDialog";
import LoadingScreen from "@/components/LoadingScreen";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { formatBits, formatDateTime, formatDuration, formatNumber, fromNow, prettyJson } from "@/utils/format";

const METRICS = [
  { value: "cpu", label: "CPU utilisation" },
  { value: "memory", label: "Memory utilisation" },
  { value: "disk", label: "Disk utilisation" },
  { value: "load", label: "Load average" },
  { value: "sessions", label: "States / sessions" },
  { value: "vpn", label: "VPN peers" },
  { value: "gateway", label: "Gateway latency" },
  { value: "uptime", label: "Uptime" },
];

const HOUR_OPTIONS = [
  { value: 6, label: "6 hours" },
  { value: 24, label: "24 hours" },
  { value: 72, label: "3 days" },
  { value: 168, label: "7 days" },
];

const COMMAND_ACTIONS: Array<{ value: DeviceCommandAction; label: string; description: string }> = [
  { value: "ping", label: "Ping", description: "Verify the agent is alive and return its version" },
  { value: "sync_config", label: "Synchronise configuration", description: "Apply the desired aliases and firewall rules" },
  { value: "renew_certificate", label: "Renew certificate", description: "Request and install a renewed device certificate" },
  { value: "reload_firewall", label: "Reload firewall", description: "Ask OPNsense to reload the filter" },
  { value: "collect_diagnostics", label: "Collect diagnostics", description: "Create a diagnostics bundle on the device" },
  { value: "update_telemetry", label: "Force heartbeat", description: "Send a fresh telemetry sample on the next cycle" },
  { value: "restart_agent", label: "Restart agent", description: "Restart the agent after reporting the result" },
  { value: "noop", label: "No-op", description: "Round-trip test without side effects" },
];

export function DeviceDetailPage() {
  const { deviceId } = useParams<{ deviceId: string }>();
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const theme = useTheme();

  const [tab, setTab] = useState(0);
  const [metric, setMetric] = useState("cpu");
  const [hours, setHours] = useState(24);
  const [trafficInterface, setTrafficInterface] = useState("wan");
  const [trafficHours, setTrafficHours] = useState(24);
  const [probeResult, setProbeResult] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [certificateOpen, setCertificateOpen] = useState(false);
  const [certificateCn, setCertificateCn] = useState("");
  const [certificateDays, setCertificateDays] = useState("365");
  const [certificateError, setCertificateError] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<Certificate | null>(null);
  const [commandAction, setCommandAction] = useState<DeviceCommandAction>("ping");
  const [commandOpen, setCommandOpen] = useState(false);
  const [firmwareOpen, setFirmwareOpen] = useState(false);
  const [firmwarePackage, setFirmwarePackage] = useState("");
  const [firmwareError, setFirmwareError] = useState<string | null>(null);
  const [rebootOpen, setRebootOpen] = useState(false);
  const [wgServerName, setWgServerName] = useState("");
  const [wgServerEndpoint, setWgServerEndpoint] = useState("");
  const [wgServerPort, setWgServerPort] = useState("51820");
  const [wgServerNetwork, setWgServerNetwork] = useState("10.0.0.0/24");
  const [wgServerOpen, setWgServerOpen] = useState(false);
  const [wgServerError, setWgServerError] = useState<string | null>(null);
  const [wgDeleteTarget, setWgDeleteTarget] = useState<{ uuid: string; name?: string } | null>(null);
  const [openvpnName, setOpenvpnName] = useState("");
  const [openvpnNetwork, setOpenvpnNetwork] = useState("10.0.0.0/24");
  const [openvpnPort, setOpenvpnPort] = useState("1194");
  const [openvpnOpen, setOpenvpnOpen] = useState(false);
  const [openvpnError, setOpenvpnError] = useState<string | null>(null);
  const [openvpnDeleteTarget, setOpenvpnDeleteTarget] = useState<{ uuid: string; name?: string } | null>(null);
  const [vlanName, setVlanName] = useState("");
  const [vlanNumber, setVlanNumber] = useState("");
  const [vlanInterface, setVlanInterface] = useState("");
  const [vlanOpen, setVlanOpen] = useState(false);
  const [vlanError, setVlanError] = useState<string | null>(null);
  const [vlanDeleteTarget, setVlanDeleteTarget] = useState<{ uuid: string; name?: string } | null>(null);

  const deviceQuery = useQuery({
    queryKey: qk.devices.detail(deviceId ?? ""),
    queryFn: () => devicesApi.get(deviceId ?? ""),
    enabled: Boolean(deviceId),
  });

  const seriesQuery = useQuery({
    queryKey: qk.devices.series(deviceId ?? "", metric, hours),
    queryFn: () => metricsApi.deviceSeries(deviceId ?? "", metric, hours, 720),
    enabled: Boolean(deviceId) && tab === 0,
    refetchInterval: 60_000,
  });

  const trafficQuery = useQuery({
    queryKey: qk.devices.traffic(deviceId ?? "", trafficInterface, trafficHours),
    queryFn: () => metricsApi.deviceTraffic(deviceId ?? "", trafficInterface, trafficHours),
    enabled: Boolean(deviceId) && tab === 0,
    refetchInterval: 60_000,
  });

  const certificatesQuery = useQuery({
    queryKey: qk.devices.certificates(deviceId ?? ""),
    queryFn: () => devicesApi.certificates(deviceId ?? ""),
    enabled: Boolean(deviceId) && tab === 1,
  });

  const commandsQuery = useQuery({
    queryKey: qk.devices.commands(deviceId ?? ""),
    queryFn: () => devicesApi.commands(deviceId ?? ""),
    enabled: Boolean(deviceId) && tab === 2,
    refetchInterval: 15_000,
  });

  const firmwareQuery = useQuery({
    queryKey: qk.devices.firmware(deviceId ?? ""),
    queryFn: () => devicesApi.firmwareStatus(deviceId ?? ""),
    enabled: Boolean(deviceId) && tab === 3,
    retry: false,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.devices.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const maintenanceMutation = useMutation({
    mutationFn: (enabled: boolean) => devicesApi.maintenance(deviceId ?? "", enabled),
    onSuccess: (device) => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.detail(device.id) });
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

  const probeMutation = useMutation({
    mutationFn: () => devicesApi.probe(deviceId ?? ""),
    onSuccess: (result) => {
      setProbeResult(prettyJson(result));
      dispatch(showToast({ message: "Device probe completed", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const updateMutation = useMutation({
    mutationFn: (payload: DeviceUpdate) => devicesApi.update(deviceId ?? "", payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.detail(deviceId ?? "") });
      invalidate();
      setEditOpen(false);
      dispatch(showToast({ message: "Device updated", severity: "success" }));
    },
    onError: (error) => setEditError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: () => devicesApi.remove(deviceId ?? ""),
    onSuccess: () => {
      invalidate();
      dispatch(showToast({ message: "Device deleted", severity: "success" }));
      navigate("/devices", { replace: true });
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const issueCertificateMutation = useMutation({
    mutationFn: () =>
      devicesApi.issueCertificate(
        deviceId ?? "",
        certificateCn.trim() || undefined,
        Number(certificateDays) || undefined,
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.certificates(deviceId ?? "") });
      setCertificateOpen(false);
      setCertificateCn("");
      dispatch(showToast({ message: "Certificate issued", severity: "success" }));
    },
    onError: (error) => setCertificateError(toApiError(error).message),
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => certificatesApi.revoke(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.certificates(deviceId ?? "") });
      setRevokeTarget(null);
      dispatch(showToast({ message: "Certificate revoked", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const commandMutation = useMutation({
    mutationFn: () => devicesApi.sendCommand(deviceId ?? "", commandAction),
    onSuccess: (command) => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.commands(deviceId ?? "") });
      setCommandOpen(false);
      dispatch(
        showToast({
          message: `${command.action} queued (${command.pending_count} pending)`,
          severity: "success",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const firmwareUpgradeMutation = useMutation({
    mutationFn: () => devicesApi.upgradeFirmware(deviceId ?? "", firmwarePackage.trim() || undefined),
    onSuccess: (action) => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.firmware(deviceId ?? "") });
      void queryClient.invalidateQueries({ queryKey: qk.devices.detail(deviceId ?? "") });
      setFirmwareOpen(false);
      dispatch(
        showToast({
          message: `Firmware ${action.package ? `${action.package} ` : ""}upgrade initiated on ${action.device_name}`,
          severity: "success",
        }),
      );
    },
    onError: (error) => setFirmwareError(toApiError(error).message),
  });

  const rebootMutation = useMutation({
    mutationFn: () => devicesApi.rebootDevice(deviceId ?? ""),
    onSuccess: (action) => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.firmware(deviceId ?? "") });
      void queryClient.invalidateQueries({ queryKey: qk.devices.detail(deviceId ?? "") });
      setRebootOpen(false);
      dispatch(showToast({ message: `${action.device_name} reboot initiated`, severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const ipsecQuery = useQuery({
    queryKey: qk.devices.ipsec(deviceId ?? ""),
    queryFn: () => deviceSdwanApi.ipsecTunnels(deviceId ?? ""),
    enabled: Boolean(deviceId) && tab === 4,
    retry: false,
  });
  const wgQuery = useQuery({
    queryKey: qk.devices.wireguard(deviceId ?? ""),
    queryFn: () => deviceSdwanApi.wireguardServers(deviceId ?? ""),
    enabled: Boolean(deviceId) && tab === 5,
    retry: false,
  });
  const openvpnQuery = useQuery({
    queryKey: qk.devices.openvpn(deviceId ?? ""),
    queryFn: () => deviceSdwanApi.openvpnInstances(deviceId ?? ""),
    enabled: Boolean(deviceId) && tab === 6,
    retry: false,
  });
  const vlanQuery = useQuery({
    queryKey: qk.devices.vlan(deviceId ?? ""),
    queryFn: () => deviceSdwanApi.vlans(deviceId ?? ""),
    enabled: Boolean(deviceId) && tab === 7,
    retry: false,
  });
  const dhcpQuery = useQuery({
    queryKey: qk.devices.dhcp(deviceId ?? ""),
    queryFn: () => deviceSdwanApi.dhcpLeases(deviceId ?? ""),
    enabled: Boolean(deviceId) && tab === 8,
    retry: false,
  });
  const dnsQuery = useQuery({
    queryKey: qk.devices.dns(deviceId ?? ""),
    queryFn: () => deviceSdwanApi.dnsRecords(deviceId ?? ""),
    enabled: Boolean(deviceId) && tab === 9,
    retry: false,
  });

  const wgCreateMutation = useMutation({
    mutationFn: (payload: { name: string; endpoint: string | null; port: number; network: string }) =>
      deviceSdwanApi.createWireguardServer(deviceId ?? "", payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.wireguard(deviceId ?? "") });
      setWgServerOpen(false);
      setWgServerName("");
      setWgServerEndpoint("");
      setWgServerPort("51820");
      setWgServerNetwork("10.0.0.0/24");
      dispatch(showToast({ message: "WireGuard server created", severity: "success" }));
    },
    onError: (error) => setWgServerError(toApiError(error).message),
  });
  const wgDeleteMutation = useMutation({
    mutationFn: (uuid: string) => deviceSdwanApi.deleteWireguardServer(deviceId ?? "", uuid),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.wireguard(deviceId ?? "") });
      setWgDeleteTarget(null);
      dispatch(showToast({ message: "WireGuard server deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });
  const openvpnCreateMutation = useMutation({
    mutationFn: (payload: { name: string; network: string; port: number }) =>
      deviceSdwanApi.createOpenvpnInstance(deviceId ?? "", payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.openvpn(deviceId ?? "") });
      setOpenvpnOpen(false);
      setOpenvpnName("");
      setOpenvpnNetwork("10.0.0.0/24");
      setOpenvpnPort("1194");
      dispatch(showToast({ message: "OpenVPN instance created", severity: "success" }));
    },
    onError: (error) => setOpenvpnError(toApiError(error).message),
  });
  const openvpnDeleteMutation = useMutation({
    mutationFn: (uuid: string) => deviceSdwanApi.deleteOpenvpnInstance(deviceId ?? "", uuid),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.openvpn(deviceId ?? "") });
      setOpenvpnDeleteTarget(null);
      dispatch(showToast({ message: "OpenVPN instance deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });
  const vlanCreateMutation = useMutation({
    mutationFn: (payload: { name: string; vlan: number; interface: string }) =>
      deviceSdwanApi.createVlan(deviceId ?? "", payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.vlan(deviceId ?? "") });
      setVlanOpen(false);
      setVlanName("");
      setVlanNumber("");
      setVlanInterface("");
      dispatch(showToast({ message: "VLAN created", severity: "success" }));
    },
    onError: (error) => setVlanError(toApiError(error).message),
  });
  const vlanDeleteMutation = useMutation({
    mutationFn: (uuid: string) => deviceSdwanApi.deleteVlan(deviceId ?? "", uuid),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.devices.vlan(deviceId ?? "") });
      setVlanDeleteTarget(null);
      dispatch(showToast({ message: "VLAN deleted", severity: "success" }));
    },
onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const ipsecColumns: Array<DataTableColumn<Record<string, unknown>>> = [
    { key: "name", label: "Name", render: (row) => String(row.name ?? "—") },
    { key: "remote", label: "Remote", render: (row) => String(row.remote ?? "—") },
    { key: "local", label: "Local", render: (row) => String(row.local ?? "—") },
    { key: "tunnel_network", label: "Tunnel network", render: (row) => String(row.tunnel_network ?? "—") },
    {
      key: "enabled",
      label: "Enabled",
      width: 100,
      render: (row) => (row.enabled ? "Yes" : "No"),
    },
  ];

  const wgColumns: Array<DataTableColumn<Record<string, unknown>>> = [
    { key: "name", label: "Name", render: (row) => String(row.name ?? "—") },
    { key: "endpoint", label: "Endpoint", render: (row) => String(row.endpoint ?? "—") },
    { key: "port", label: "Port", width: 90, render: (row) => String(row.port ?? "—") },
    { key: "network", label: "Network", render: (row) => String(row.network ?? "—") },
    {
      key: "enabled",
      label: "Enabled",
      width: 100,
      render: (row) => (row.enabled ? "Yes" : "No"),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 90,
      render: (row) => (
        <PermissionGate permission="sdwan:write">
          <Tooltip title="Delete server">
            <IconButton
              size="small"
              color="error"
              onClick={() => setWgDeleteTarget({ uuid: String(row.uuid ?? row.id ?? ""), name: String(row.name ?? "") })}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </PermissionGate>
      ),
    },
  ];

  const openvpnColumns: Array<DataTableColumn<Record<string, unknown>>> = [
    { key: "name", label: "Name", render: (row) => String(row.name ?? "—") },
    { key: "mode", label: "Mode", width: 100, render: (row) => String(row.mode ?? "—") },
    { key: "protocol", label: "Protocol", width: 100, render: (row) => String(row.protocol ?? "—") },
    { key: "port", label: "Port", width: 90, render: (row) => String(row.port ?? "—") },
    { key: "network", label: "Network", render: (row) => String(row.network ?? "—") },
    {
      key: "enabled",
      label: "Enabled",
      width: 100,
      render: (row) => (row.enabled ? "Yes" : "No"),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 90,
      render: (row) => (
        <PermissionGate permission="sdwan:write">
          <Tooltip title="Delete instance">
            <IconButton
              size="small"
              color="error"
              onClick={() => setOpenvpnDeleteTarget({ uuid: String(row.uuid ?? row.id ?? ""), name: String(row.name ?? "") })}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </PermissionGate>
      ),
    },
  ];

  const vlanColumns: Array<DataTableColumn<Record<string, unknown>>> = [
    { key: "name", label: "Name", render: (row) => String(row.name ?? "—") },
    { key: "vlan", label: "VLAN", width: 90, render: (row) => String(row.vlan ?? "—") },
    { key: "interface", label: "Interface", render: (row) => String(row.ifname ?? row.interface ?? "—") },
    {
      key: "enabled",
      label: "Enabled",
      width: 100,
      render: (row) => (row.enabled ? "Yes" : "No"),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 90,
      render: (row) => (
        <PermissionGate permission="sdwan:write">
          <Tooltip title="Delete VLAN">
            <IconButton
              size="small"
              color="error"
              onClick={() => setVlanDeleteTarget({ uuid: String(row.uuid ?? row.id ?? ""), name: String(row.name ?? "") })}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </PermissionGate>
      ),
    },
  ];

  const dhcpColumns: Array<DataTableColumn<Record<string, unknown>>> = [
    { key: "mac", label: "MAC", render: (row) => String(row.mac ?? "—") },
    { key: "ip", label: "IP", render: (row) => String(row.ip ?? "—") },
    { key: "hostname", label: "Hostname", render: (row) => String(row.hostname ?? "—") },
    { key: "lease_start", label: "Lease start", width: 190, render: (row) => formatDateTime(row.lease_start as string | null) },
    { key: "lease_end", label: "Lease end", width: 190, render: (row) => formatDateTime(row.lease_end as string | null) },
  ];

  const dnsColumns: Array<DataTableColumn<Record<string, unknown>>> = [
    { key: "name", label: "Name", render: (row) => String(row.name ?? "—") },
    { key: "type", label: "Type", width: 100, render: (row) => String(row.type ?? "—") },
    { key: "data", label: "Data", render: (row) => String(row.data ?? "—") },
    {
      key: "enabled",
      label: "Enabled",
      width: 100,
      render: (row) => (row.enabled ? "Yes" : "No"),
    },
  ];

  const commandColumns: Array<DataTableColumn<DeviceCommandStatus["pending"][number]>> = [
    { key: "action", label: "Action", render: (row) => row.action },
    {
      key: "requested_at",
      label: "Queued",
      width: 190,
      render: (row) => formatDateTime(row.requested_at),
    },
    {
      key: "id",
      label: "Command ID",
      hideBelow: "lg",
      monospace: true,
      render: (row) => `${row.id.slice(0, 8)}…`,
    },
  ];

  const resultColumns: Array<DataTableColumn<DeviceCommandStatus["history"][number]>> = [
    { key: "action", label: "Action", width: 170 },
    {
      key: "status",
      label: "Result",
      width: 110,
      render: (row) => <StatusChip status={row.status} />,
    },
    {
      key: "message",
      label: "Message",
      render: (row) => row.message || "—",
    },
    {
      key: "received_at",
      label: "Received",
      width: 190,
      render: (row) => formatDateTime(row.received_at ?? row.finished_at ?? null),
    },
  ];

  const device = deviceQuery.data;
  const series = seriesQuery.data;
  const chartData = useMemo(
    () =>
      (series?.points ?? []).map((point) => ({
        timestamp: point.recorded_at,
        value: point.value,
      })),
    [series],
  );

  const traffic = trafficQuery.data;
  const trafficChart = useMemo(
    () =>
      (traffic?.points ?? []).map((point) => ({
        timestamp: point.recorded_at,
        in_bps: point.in_bps,
        out_bps: point.out_bps,
      })),
    [traffic],
  );

  const certificateColumns: Array<DataTableColumn<Certificate>> = [
    {
      key: "subject_cn",
      label: "Subject",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.subject_cn}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Issuer: {row.issuer_cn}
          </Typography>
        </Box>
      ),
    },
    { key: "status", label: "Status", width: 120, render: (row) => <StatusChip status={row.status} /> },
    {
      key: "validity",
      label: "Valid until",
      width: 190,
      render: (row) => (
        <Box>
          <Typography variant="body2">{formatDateTime(row.valid_to)}</Typography>
          <Typography variant="caption" color="text.secondary">
            from {formatDateTime(row.valid_from)}
          </Typography>
        </Box>
      ),
    },
    {
      key: "fingerprint",
      label: "SHA-256 fingerprint",
      hideBelow: "lg",
      monospace: true,
      render: (row) => `${row.fingerprint_sha256.slice(0, 24)}…`,
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 90,
      render: (row) =>
        row.status === "revoked" ? (
          <Typography variant="caption" color="text.disabled">
            —
          </Typography>
        ) : (
          <PermissionGate permission="certificate:write">
            <Tooltip title="Revoke certificate">
              <IconButton size="small" color="error" onClick={() => setRevokeTarget(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        ),
    },
  ];

  if (deviceQuery.isLoading) return <LoadingScreen label="Loading device…" />;
  if (deviceQuery.isError || !device) {
    return (
      <ErrorState
        title="Device unavailable"
        message={deviceQuery.error ? toApiError(deviceQuery.error).message : "The device does not exist."}
        onRetry={() => deviceQuery.refetch()}
      />
    );
  }

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Devices", to: "/devices" }, { label: device.name }]}
        title={device.name}
        subtitle={
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <StatusChip status={device.status} />
            <StatusChip status={device.connection_status} label={`Agent ${device.connection_status}`} />
            {device.is_ha && <Chip size="small" label={`HA ${device.ha_role ?? "pair"}`} variant="outlined" />}
            {device.tags.map((tag) => (
              <Chip key={tag} size="small" label={tag} variant="outlined" />
            ))}
          </Stack>
        }
        actions={
          <>
            <IconButton onClick={() => navigate("/devices")} aria-label="Back to devices">
              <ArrowBackIcon />
            </IconButton>
            <PermissionGate permission="device:exec">
              <Button
                variant="outlined"
                startIcon={<RadarOutlinedIcon />}
                onClick={() => probeMutation.mutate()}
                disabled={probeMutation.isPending}
              >
                Probe
              </Button>
            </PermissionGate>
            <PermissionGate permission="device:write">
              <Button
                variant="outlined"
                startIcon={
                  device.status === "maintenance" ? <PlayCircleOutlineIcon /> : <PauseCircleOutlineIcon />
                }
                onClick={() => maintenanceMutation.mutate(device.status !== "maintenance")}
                disabled={maintenanceMutation.isPending}
              >
                {device.status === "maintenance" ? "Leave maintenance" : "Maintenance"}
              </Button>
            </PermissionGate>
            <PermissionGate permission="device:write">
              <Button
                variant="outlined"
                startIcon={<EditOutlinedIcon />}
                onClick={() => {
                  setEditName(device.name);
                  setEditDescription(device.description ?? "");
                  setEditError(null);
                  setEditOpen(true);
                }}
              >
                Edit
              </Button>
            </PermissionGate>
            <PermissionGate permission="device:delete">
              <Button color="error" variant="outlined" onClick={() => setDeleteOpen(true)}>
                Delete
              </Button>
            </PermissionGate>
          </>
        }
        meta={
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
            Last seen {device.last_seen_at ? `${fromNow(device.last_seen_at)} · ${formatDateTime(device.last_seen_at)}` : "never"}
            {device.uptime_seconds ? ` · up ${formatDuration(device.uptime_seconds)}` : ""}
          </Typography>
        }
      />

      <Tabs value={tab} onChange={(_event, value: number) => setTab(value)} sx={{ mb: 2 }}>
        <Tab label="Overview" />
        <Tab label={`Certificates${certificatesQuery.data ? ` (${certificatesQuery.data.length})` : ""}`} />
        <Tab label={`Commands${commandsQuery.data ? ` (${commandsQuery.data.pending_count})` : ""}`} />
        <Tab label="Firmware" />
        <Tab label="IPsec" />
        <Tab label="WireGuard" />
        <Tab label="OpenVPN" />
        <Tab label="VLAN" />
        <Tab label="DHCP" />
        <Tab label="DNS" />
      </Tabs>

      {tab === 0 && (
        <Grid container spacing={2}>
          <Grid item xs={12} lg={7}>
            <SectionCard
              title="Inventory"
              subtitle="Static attributes reported by the agent and maintained in OFME"
            >
              <DetailGrid
                items={[
                  { label: "Hostname", value: device.hostname ?? "—" },
                  { label: "Management endpoint", value: `${device.ip_address ?? "—"}:${device.api_port}` },
                  { label: "Serial number", value: device.serial_number ?? "—" },
                  { label: "Model", value: device.model ?? "—" },
                  { label: "Firmware", value: device.firmware_version ?? "—" },
                  { label: "Agent version", value: device.agent_version ?? "—" },
                  { label: "Certificate serial", value: device.certificate_serial ?? "—" },
                  { label: "Enrolled", value: formatDateTime(device.enrolled_at) },
                  { label: "Provisioned", value: formatDateTime(device.provisioned_at) },
                  { label: "Created", value: formatDateTime(device.created_at) },
                  { label: "Description", value: device.description ?? "—", span: 2 },
                ]}
              />
            </SectionCard>
          </Grid>
          <Grid item xs={12} lg={5}>
            <Stack spacing={2}>
              {probeResult && (
                <SectionCard
                  title="Probe result"
                  subtitle="Live OPNsense API response"
                  actions={
                    <Button size="small" onClick={() => setProbeResult(null)}>
                      Clear
                    </Button>
                  }
                >
                  <CodeBlock code={probeResult} language="json" maxHeight={260} />
                </SectionCard>
              )}
              <Card>
                <CardContent>
                  <Typography variant="h5" sx={{ mb: 1 }}>
                    Agent connectivity
                  </Typography>
                  <Stack spacing={1.25}>
                    <DetailGrid
                      dense
                      items={[
                        { label: "Connection", value: <StatusChip status={device.connection_status} /> },
                        { label: "Last heartbeat", value: formatDateTime(device.last_heartbeat_at) },
                        { label: "Last seen", value: formatDateTime(device.last_seen_at) },
                        { label: "Uptime", value: formatDuration(device.uptime_seconds) },
                      ]}
                    />
                    <Divider />
                    <Typography variant="caption" color="text.secondary">
                      The agent polls the control plane on its heartbeat interval and receives queued commands
                      over the mTLS channel. Heartbeat timeouts move the device to offline automatically.
                    </Typography>
                  </Stack>
                </CardContent>
              </Card>
            </Stack>
          </Grid>
          <Grid item xs={12}>
            <SectionCard
              title="Telemetry"
              subtitle={`${series?.metric_type ?? metric}${series?.unit ? ` (${series.unit})` : ""} · last ${hours}h`}
              actions={
                <Stack direction="row" spacing={1}>
                  <TextField
                    select
                    value={metric}
                    onChange={(event) => setMetric(event.target.value)}
                    sx={{ width: 190 }}
                  >
                    {METRICS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    select
                    value={hours}
                    onChange={(event) => setHours(Number(event.target.value))}
                    sx={{ width: 130 }}
                  >
                    {HOUR_OPTIONS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </TextField>
                </Stack>
              }
            >
              {seriesQuery.isError ? (
                <ErrorState
                  compact
                  title="Telemetry unavailable"
                  message={toApiError(seriesQuery.error).message}
                  onRetry={() => seriesQuery.refetch()}
                />
              ) : chartData.length === 0 ? (
                <Box sx={{ py: 6, textAlign: "center" }}>
                  <Typography variant="body2" color="text.secondary">
                    {seriesQuery.isLoading
                      ? "Loading telemetry…"
                      : "No samples for this metric in the selected window."}
                  </Typography>
                </Box>
              ) : (
                <Box sx={{ height: 320 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} vertical={false} />
                      <XAxis
                        dataKey="timestamp"
                        tickFormatter={(value: string) =>
                          value
                            ? new Date(value).toLocaleString([], {
                                month: "short",
                                day: "2-digit",
                                hour: "2-digit",
                                minute: "2-digit",
                              })
                            : ""
                        }
                        tick={{ fontSize: 11, fill: theme.palette.text.secondary }}
                        stroke={theme.palette.divider}
                        minTickGap={36}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: theme.palette.text.secondary }}
                        stroke={theme.palette.divider}
                        width={54}
                      />
                      <RechartsTooltip
                        labelFormatter={(value) => new Date(String(value)).toLocaleString()}
                        formatter={(value) => [`${formatNumber(Number(value), 2)}`, metric]}
                        contentStyle={{
                          background: theme.palette.background.paper,
                          border: `1px solid ${theme.palette.divider}`,
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={theme.palette.primary.main}
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </Box>
              )}
              <Box
                sx={{
                  mt: 1,
                  p: 1.25,
                  borderRadius: 1.5,
                  bgcolor: alpha(theme.palette.info.main, 0.06),
                }}
              >
                <Typography variant="caption" color="text.secondary">
                  Samples are retained according to the monitoring retention policy. The series endpoint caps
                  the response at 720 points and downsamples automatically.
                </Typography>
              </Box>
            </SectionCard>
          </Grid>
          <Grid item xs={12}>
            <SectionCard
              title="Interface traffic"
              subtitle={`${traffic?.interface ?? trafficInterface} · last ${trafficHours}h${
                traffic ? ` · ${formatNumber(traffic.bucket_seconds)}s buckets` : ""
              }`}
              actions={
                <Stack direction="row" spacing={1}>
                  <TextField
                    select
                    value={trafficInterface}
                    onChange={(event) => setTrafficInterface(event.target.value)}
                    sx={{ width: 210 }}
                  >
                    {(traffic?.interfaces.length ?? 0) === 0 ? (
                      <MenuItem value={trafficInterface}>{trafficInterface}</MenuItem>
                    ) : (
                      traffic?.interfaces.map((option) => (
                        <MenuItem key={option.key} value={option.key}>
                          {option.name} ({option.key})
                        </MenuItem>
                      ))
                    )}
                  </TextField>
                  <TextField
                    select
                    value={trafficHours}
                    onChange={(event) => setTrafficHours(Number(event.target.value))}
                    sx={{ width: 130 }}
                  >
                    {HOUR_OPTIONS.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.label}
                      </MenuItem>
                    ))}
                  </TextField>
                </Stack>
              }
            >
              {trafficQuery.isError ? (
                <ErrorState
                  compact
                  title="Traffic counters unavailable"
                  message={toApiError(trafficQuery.error).message}
                  onRetry={() => trafficQuery.refetch()}
                />
              ) : trafficChart.length === 0 ? (
                <Box sx={{ py: 6, textAlign: "center" }}>
                  <Typography variant="body2" color="text.secondary">
                    {trafficQuery.isLoading
                      ? "Loading traffic counters…"
                      : "No traffic samples for this interface yet. A rate appears once two counter polls are available."}
                  </Typography>
                </Box>
              ) : (
                <Box sx={{ height: 320 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={trafficChart} margin={{ top: 8, right: 12, left: -4, bottom: 0 }}>
                      <defs>
                        <linearGradient id="deviceInGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={theme.palette.info.main} stopOpacity={0.35} />
                          <stop offset="95%" stopColor={theme.palette.info.main} stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="deviceOutGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={theme.palette.warning.main} stopOpacity={0.3} />
                          <stop offset="95%" stopColor={theme.palette.warning.main} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} vertical={false} />
                      <XAxis
                        dataKey="timestamp"
                        tickFormatter={(value: string) =>
                          value
                            ? new Date(value).toLocaleString([], {
                                month: "short",
                                day: "2-digit",
                                hour: "2-digit",
                                minute: "2-digit",
                              })
                            : ""
                        }
                        tick={{ fontSize: 11, fill: theme.palette.text.secondary }}
                        stroke={theme.palette.divider}
                        minTickGap={36}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: theme.palette.text.secondary }}
                        stroke={theme.palette.divider}
                        width={66}
                        tickFormatter={(value: number) => formatBits(value)}
                      />
                      <RechartsTooltip
                        labelFormatter={(value) => new Date(String(value)).toLocaleString()}
                        formatter={(value, name) => [formatBits(Number(value)), name]}
                        contentStyle={{
                          background: theme.palette.background.paper,
                          border: `1px solid ${theme.palette.divider}`,
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                      />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Area
                        type="monotone"
                        dataKey="in_bps"
                        name="Received"
                        stroke={theme.palette.info.main}
                        fill="url(#deviceInGradient)"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                      <Area
                        type="monotone"
                        dataKey="out_bps"
                        name="Transmitted"
                        stroke={theme.palette.warning.main}
                        fill="url(#deviceOutGradient)"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </Box>
              )}
              <Box
                sx={{
                  mt: 1,
                  p: 1.25,
                  borderRadius: 1.5,
                  bgcolor: alpha(theme.palette.info.main, 0.06),
                }}
              >
                <Typography variant="caption" color="text.secondary">
                  Rates are derived from two consecutive counter samples. Counter resets and sampling gaps
                  longer than two hours are skipped instead of producing a false spike.
                </Typography>
              </Box>
            </SectionCard>
          </Grid>
        </Grid>
      )}

      {tab === 1 && (
        <Stack spacing={2}>
          <SectionCard
            title="Device certificates"
            subtitle="mTLS client certificates issued by the OFME CA for this appliance"
            actions={
              <PermissionGate permission="certificate:write">
                <Button
                  variant="contained"
                  startIcon={<WorkspacePremiumOutlinedIcon />}
                  onClick={() => {
                    setCertificateCn(device.hostname ?? device.name);
                    setCertificateError(null);
                    setCertificateOpen(true);
                  }}
                >
                  Issue certificate
                </Button>
              </PermissionGate>
            }
            padded={false}
          >
            <DataTable
              columns={certificateColumns}
              rows={certificatesQuery.data ?? []}
              getRowId={(row) => row.id}
              loading={certificatesQuery.isLoading}
              error={certificatesQuery.error ? toApiError(certificatesQuery.error).message : null}
              onRetry={() => certificatesQuery.refetch()}
              emptyTitle="No certificates"
              emptyDescription="Issue a client certificate so the agent can authenticate with mTLS."
              dense
            />
          </SectionCard>
        </Stack>
      )}

      {tab === 2 && (
        <Stack spacing={2}>
          <SectionCard
            title="Operational commands"
            subtitle="Whitelisted commands are queued in the control plane and executed after the next agent poll"
            actions={
              <PermissionGate permission="device:exec">
                <Button
                  variant="contained"
                  startIcon={<RadarOutlinedIcon />}
                  onClick={() => setCommandOpen(true)}
                >
                  Queue command
                </Button>
              </PermissionGate>
            }
          >
            <TextField
              select
              label="Command"
              value={commandAction}
              onChange={(event) => setCommandAction(event.target.value as DeviceCommandAction)}
              sx={{ maxWidth: 420 }}
            >
              {COMMAND_ACTIONS.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </TextField>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
              {COMMAND_ACTIONS.find((option) => option.value === commandAction)?.description}
            </Typography>
          </SectionCard>

          <SectionCard title="Pending commands" padded={false}>
            <DataTable
              columns={commandColumns}
              rows={commandsQuery.data?.pending ?? []}
              getRowId={(row) => row.id}
              loading={commandsQuery.isLoading}
              error={commandsQuery.error ? toApiError(commandsQuery.error).message : null}
              onRetry={() => commandsQuery.refetch()}
              emptyTitle="No pending commands"
              emptyDescription="Commands queued here are delivered on the agent's next poll."
              dense
            />
          </SectionCard>

          <SectionCard
            title="Recent command results"
            subtitle={
              commandsQuery.data?.last_result_at
                ? `Last result ${fromNow(commandsQuery.data.last_result_at)}`
                : undefined
            }
            padded={false}
          >
            <DataTable
              columns={resultColumns}
              rows={commandsQuery.data?.history ?? []}
              getRowId={(row) => `${row.id}-${row.received_at ?? ""}`}
              loading={commandsQuery.isLoading}
              error={commandsQuery.error ? toApiError(commandsQuery.error).message : null}
              onRetry={() => commandsQuery.refetch()}
              emptyTitle="No command results"
              emptyDescription="Results are reported in the heartbeat following command execution."
              dense
            />
          </SectionCard>
        </Stack>
      )}

      {tab === 3 && (
        <Stack spacing={2}>
          <SectionCard
            title="Firmware lifecycle"
            subtitle="Live release information fetched through the device's own OPNsense API"
            actions={
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Button
                  size="small"
                  onClick={() => firmwareQuery.refetch()}
                  disabled={firmwareQuery.isFetching}
                >
                  Refresh
                </Button>
                <PermissionGate permission="firmware:upgrade">
                  <Button
                    size="small"
                    variant="contained"
                    startIcon={<SystemUpdateAltOutlinedIcon />}
                    onClick={() => {
                      setFirmwarePackage("");
                      setFirmwareError(null);
                      setFirmwareOpen(true);
                    }}
                  >
                    Upgrade
                  </Button>
                </PermissionGate>
                <PermissionGate permission="firmware:reboot">
                  <Button
                    size="small"
                    color="warning"
                    variant="outlined"
                    startIcon={<RestartAltOutlinedIcon />}
                    onClick={() => setRebootOpen(true)}
                  >
                    Reboot
                  </Button>
                </PermissionGate>
              </Stack>
            }
          >
            {firmwareQuery.isLoading ? (
              <Typography variant="body2" color="text.secondary">
                Reading firmware status from the device…
              </Typography>
            ) : firmwareQuery.isError ? (
              <Alert severity="error">
                {toApiError(firmwareQuery.error).message ||
                  "The device did not answer. Check its API credentials and reachability."}
              </Alert>
            ) : firmwareQuery.data ? (
              <Stack spacing={2}>
                {firmwareQuery.data.needs_upgrade && (
                  <Alert severity="warning">
                    Release {firmwareQuery.data.latest_release} is available; the host runs{" "}
                    {firmwareQuery.data.product_version ?? "an unknown version"}. Plan a maintenance window:
                    the appliance reboots during the upgrade.
                  </Alert>
                )}
                {!firmwareQuery.data.upgrade_available && firmwareQuery.data.reachable && (
                  <Alert severity="success">No newer release is reported by the device.</Alert>
                )}
                <DetailGrid
                  items={[
                    { label: "Product", value: firmwareQuery.data.product_name ?? "OPNsense" },
                    { label: "Series", value: firmwareQuery.data.product_series ?? "—" },
                    {
                      label: "Running release",
                      value: firmwareQuery.data.product_version ?? "—",
                    },
                    {
                      label: "Recorded version",
                      value: firmwareQuery.data.current_version ?? "—",
                    },
                    { label: "Latest release", value: firmwareQuery.data.latest_release ?? "—" },
                    {
                      label: "Upgrade required",
                      value: firmwareQuery.data.needs_upgrade ? "Yes" : "No",
                    },
                  ]}
                />
                <Typography variant="caption" color="text.secondary">
                  The upgrade calls OPNsense&apos;s own firmware endpoint; the control plane never shells out.
                  The recorded device version is cleared until the host reports again after the reboot.
                </Typography>
              </Stack>
            ) : null}
          </SectionCard>

          <SectionCard title="Raw device response" subtitle="Diagnostic payload returned by the host">
            <CodeBlock
              code={prettyJson({
                firmware: firmwareQuery.data?.raw_firmware ?? {},
                info: firmwareQuery.data?.raw_info ?? {},
              })}
              language="json"
              maxHeight={320}
            />
          </SectionCard>
        </Stack>
      )}

      <FormDialog
        open={editOpen}
        title="Edit device"
        loading={updateMutation.isPending}
        error={editError}
        submitDisabled={!editName.trim()}
        onSubmit={() => updateMutation.mutate({ name: editName.trim(), description: editDescription.trim() || null })}
        onClose={() => setEditOpen(false)}
      >
        <TextField
          label="Name"
          value={editName}
          onChange={(event) => setEditName(event.target.value)}
          required
          autoFocus
        />
        <TextField
          label="Description"
          value={editDescription}
          onChange={(event) => setEditDescription(event.target.value)}
          multiline
          minRows={2}
        />
      </FormDialog>

      <FormDialog
        open={certificateOpen}
        title="Issue device certificate"
        description={
          <Typography variant="body2" color="text.secondary">
            The private key is generated inside the OFME CA and returned once to the enrolling agent. Revoke
            the certificate immediately if an appliance is retired.
          </Typography>
        }
        submitLabel="Issue"
        loading={issueCertificateMutation.isPending}
        error={certificateError}
        submitDisabled={Number(certificateDays) <= 0}
        onSubmit={() => issueCertificateMutation.mutate()}
        onClose={() => setCertificateOpen(false)}
      >
        <TextField
          label="Common name"
          value={certificateCn}
          onChange={(event) => setCertificateCn(event.target.value)}
          helperText="Defaults to the device hostname when left blank"
        />
        <TextField
          label="Validity (days)"
          type="number"
          value={certificateDays}
          onChange={(event) => setCertificateDays(event.target.value)}
          inputProps={{ min: 1, max: 3650 }}
        />
      </FormDialog>

      <ConfirmDialog
        open={Boolean(revokeTarget)}
        title="Revoke certificate"
        description={
          revokeTarget
            ? `Revoke ${revokeTarget.subject_cn}? The serial ${revokeTarget.serial_number} is added to the CRL and the agent must re-enroll.`
            : undefined
        }
        confirmLabel="Revoke"
        confirmColor="error"
        loading={revokeMutation.isPending}
        onConfirm={() => revokeTarget && revokeMutation.mutate(revokeTarget.id)}
        onClose={() => setRevokeTarget(null)}
      />

      <ConfirmDialog
        open={commandOpen}
        title="Queue device command"
        description={`Queue "${COMMAND_ACTIONS.find((option) => option.value === commandAction)?.label ?? commandAction}" for ${device.name}? The agent executes it on its next poll and reports the result in the following heartbeat.`}
        confirmLabel="Queue"
        loading={commandMutation.isPending}
        onConfirm={() => commandMutation.mutate()}
        onClose={() => setCommandOpen(false)}
      />

      <FormDialog
        open={firmwareOpen}
        title="Upgrade firmware"
        description={
          <Typography variant="body2" color="text.secondary">
            OPNsense installs the requested package (or the latest available release when the field is
            blank) and reboots. The device is unreachable while it reboots.
          </Typography>
        }
        submitLabel="Upgrade"
        loading={firmwareUpgradeMutation.isPending}
        error={firmwareError}
        onSubmit={() => firmwareUpgradeMutation.mutate()}
        onClose={() => setFirmwareOpen(false)}
      >
        <TextField
          label="Package (optional)"
          value={firmwarePackage}
          onChange={(event) => setFirmwarePackage(event.target.value)}
          helperText="Exact package name such as OPNsense-25.7, or leave blank for the latest release"
          inputProps={{ maxLength: 128 }}
          autoFocus
        />
      </FormDialog>

      <ConfirmDialog
        open={rebootOpen}
        title="Reboot device"
        description={`Reboot ${device.name}? All traffic through the appliance is interrupted until it finishes booting.`}
        confirmLabel="Reboot"
        confirmColor="warning"
        loading={rebootMutation.isPending}
        onConfirm={() => rebootMutation.mutate()}
        onClose={() => setRebootOpen(false)}
      />

<FormDialog
        open={wgServerOpen}
        title="Add WireGuard server"
        description="OPNsense creates the server instance and applies the configuration immediately."
        submitLabel="Create"
        loading={wgCreateMutation.isPending}
        error={wgServerError}
        submitDisabled={!wgServerName.trim() || !wgServerNetwork.trim()}
        onSubmit={() =>
          wgCreateMutation.mutate({
            name: wgServerName.trim(),
            endpoint: wgServerEndpoint.trim() || null,
            port: Number(wgServerPort) || 51820,
            network: wgServerNetwork.trim(),
          })
        }
        onClose={() => {
          setWgServerOpen(false);
          setWgServerError(null);
        }}
      >
        <TextField
          label="Name"
          value={wgServerName}
          onChange={(event) => setWgServerName(event.target.value)}
          required
          autoFocus
        />
        <TextField
          label="Endpoint (optional)"
          value={wgServerEndpoint}
          onChange={(event) => setWgServerEndpoint(event.target.value)}
          helperText="Public IP or hostname the clients connect to"
        />
        <TextField
          label="Port"
          type="number"
          value={wgServerPort}
          onChange={(event) => setWgServerPort(event.target.value)}
          inputProps={{ min: 1, max: 65535 }}
        />
        <TextField
          label="Network (CIDR)"
          value={wgServerNetwork}
          onChange={(event) => setWgServerNetwork(event.target.value)}
          helperText="e.g. 10.0.0.0/24"
          required
        />
      </FormDialog>

      <ConfirmDialog
        open={Boolean(wgDeleteTarget)}
        title="Delete WireGuard server"
        description={`Delete ${wgDeleteTarget?.name ?? "this WireGuard server"}? Clients configured against it will lose connectivity.`}
        confirmLabel="Delete"
        confirmColor="error"
        loading={wgDeleteMutation.isPending}
        onConfirm={() => wgDeleteTarget && wgDeleteMutation.mutate(wgDeleteTarget.uuid)}
        onClose={() => setWgDeleteTarget(null)}
      />

      <FormDialog
        open={openvpnOpen}
        title="Add OpenVPN instance"
        description="OPNsense creates the instance and applies the configuration immediately."
        submitLabel="Create"
        loading={openvpnCreateMutation.isPending}
        error={openvpnError}
        submitDisabled={!openvpnName.trim() || !openvpnNetwork.trim()}
        onSubmit={() =>
          openvpnCreateMutation.mutate({
            name: openvpnName.trim(),
            network: openvpnNetwork.trim(),
            port: Number(openvpnPort) || 1194,
          })
        }
        onClose={() => {
          setOpenvpnOpen(false);
          setOpenvpnError(null);
        }}
      >
        <TextField
          label="Name"
          value={openvpnName}
          onChange={(event) => setOpenvpnName(event.target.value)}
          required
          autoFocus
        />
        <TextField
          label="Network (CIDR)"
          value={openvpnNetwork}
          onChange={(event) => setOpenvpnNetwork(event.target.value)}
          helperText="e.g. 10.0.0.0/24"
          required
        />
        <TextField
          label="Port"
          type="number"
          value={openvpnPort}
          onChange={(event) => setOpenvpnPort(event.target.value)}
          inputProps={{ min: 1, max: 65535 }}
        />
      </FormDialog>

      <ConfirmDialog
        open={Boolean(openvpnDeleteTarget)}
        title="Delete OpenVPN instance"
        description={`Delete ${openvpnDeleteTarget?.name ?? "this OpenVPN instance"}? Clients configured against it will lose connectivity.`}
        confirmLabel="Delete"
        confirmColor="error"
        loading={openvpnDeleteMutation.isPending}
        onConfirm={() => openvpnDeleteTarget && openvpnDeleteMutation.mutate(openvpnDeleteTarget.uuid)}
        onClose={() => setOpenvpnDeleteTarget(null)}
      />

      <FormDialog
        open={vlanOpen}
        title="Add VLAN"
        description="OPNsense creates the VLAN interface and applies the configuration immediately."
        submitLabel="Create"
        loading={vlanCreateMutation.isPending}
        error={vlanError}
        submitDisabled={!vlanName.trim() || !vlanNumber || !vlanInterface.trim()}
        onSubmit={() =>
          vlanCreateMutation.mutate({
            name: vlanName.trim(),
            vlan: Number(vlanNumber),
            interface: vlanInterface.trim(),
          })
        }
        onClose={() => {
          setVlanOpen(false);
          setVlanError(null);
        }}
      >
        <TextField
          label="Name"
          value={vlanName}
          onChange={(event) => setVlanName(event.target.value)}
          required
          autoFocus
        />
        <TextField
          label="VLAN ID"
          type="number"
          value={vlanNumber}
          onChange={(event) => setVlanNumber(event.target.value)}
          inputProps={{ min: 1, max: 4094 }}
          required
        />
        <TextField
          label="Interface"
          value={vlanInterface}
          onChange={(event) => setVlanInterface(event.target.value)}
          helperText="Physical interface, e.g. igb0 or em0"
          required
        />
      </FormDialog>

      <ConfirmDialog
        open={Boolean(vlanDeleteTarget)}
        title="Delete VLAN"
        description={`Delete ${vlanDeleteTarget?.name ?? "this VLAN"}? The interface is removed from the OPNsense host.`}
        confirmLabel="Delete"
        confirmColor="error"
        loading={vlanDeleteMutation.isPending}
        onConfirm={() => vlanDeleteTarget && vlanDeleteMutation.mutate(vlanDeleteTarget.uuid)}
        onClose={() => setVlanDeleteTarget(null)}
      />

      <ConfirmDialog
        open={deleteOpen}
        title="Delete device"
        description={`Delete ${device.name} from inventory? Existing backups and audit records are retained.`}
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteMutation.mutate()}
        onClose={() => setDeleteOpen(false)}
      />

      {tab === 4 && (
        <Stack spacing={2}>
          <SectionCard
            title="IPsec tunnels"
            subtitle="Phase 1 + phase 2 tunnels configured on the OPNsense host"
            actions={
              <PermissionGate permission="sdwan:write">
                <Button variant="contained" startIcon={<VpnKeyIcon />} onClick={() => navigate(`/sdwan/devices/${deviceId}/ipsec`)}>
                  Manage
                </Button>
              </PermissionGate>
            }
            padded={false}
          >
            <DataTable
              columns={ipsecColumns}
              rows={(ipsecQuery.data as Array<Record<string, unknown>>) ?? []}
              getRowId={(row) => String(row.uuid ?? row.id ?? JSON.stringify(row))}
              loading={ipsecQuery.isLoading}
              error={ipsecQuery.error ? toApiError(ipsecQuery.error).message : null}
              onRetry={() => ipsecQuery.refetch()}
              emptyTitle="No IPsec tunnels"
              emptyDescription="Create a phase 1 + phase 2 pair from the SD-WAN device view."
              dense
            />
          </SectionCard>
        </Stack>
      )}

      {tab === 5 && (
        <Stack spacing={2}>
          <SectionCard
            title="WireGuard servers"
            subtitle="WireGuard server instances configured on the OPNsense host"
            actions={
              <PermissionGate permission="sdwan:write">
                <Button variant="contained" startIcon={<SecurityIcon />} onClick={() => setWgServerOpen(true)}>
                  Add server
                </Button>
              </PermissionGate>
            }
            padded={false}
          >
            <DataTable
              columns={wgColumns}
              rows={(wgQuery.data as Array<Record<string, unknown>>) ?? []}
              getRowId={(row) => (row as { uuid?: string }).uuid ?? (row as { id?: string }).id ?? ""}
              loading={wgQuery.isLoading}
              error={wgQuery.error ? toApiError(wgQuery.error).message : null}
              onRetry={() => wgQuery.refetch()}
              emptyTitle="No WireGuard servers"
              emptyDescription="Add a server to start accepting WireGuard peers."
              dense
            />
          </SectionCard>
        </Stack>
      )}

      {tab === 6 && (
        <Stack spacing={2}>
          <SectionCard
            title="OpenVPN instances"
            subtitle="OpenVPN server/client instances configured on the OPNsense host"
            actions={
              <PermissionGate permission="sdwan:write">
                <Button variant="contained" startIcon={<SecurityIcon />} onClick={() => setOpenvpnOpen(true)}>
                  Add instance
                </Button>
              </PermissionGate>
            }
            padded={false}
          >
            <DataTable
              columns={openvpnColumns}
              rows={(openvpnQuery.data as Array<Record<string, unknown>>) ?? []}
              getRowId={(row) => (row as { uuid?: string }).uuid ?? (row as { id?: string }).id ?? ""}
              loading={openvpnQuery.isLoading}
              error={openvpnQuery.error ? toApiError(openvpnQuery.error).message : null}
              onRetry={() => openvpnQuery.refetch()}
              emptyTitle="No OpenVPN instances"
              emptyDescription="Add an instance to start accepting OpenVPN peers."
              dense
            />
          </SectionCard>
        </Stack>
      )}

      {tab === 7 && (
        <Stack spacing={2}>
          <SectionCard
            title="VLANs"
            subtitle="VLAN interfaces configured on the OPNsense host"
            actions={
              <PermissionGate permission="sdwan:write">
                <Button variant="contained" startIcon={<LanIcon />} onClick={() => setVlanOpen(true)}>
                  Add VLAN
                </Button>
              </PermissionGate>
            }
            padded={false}
          >
            <DataTable
              columns={vlanColumns}
              rows={(vlanQuery.data as Array<Record<string, unknown>>) ?? []}
              getRowId={(row) => (row as { uuid?: string }).uuid ?? (row as { id?: string }).id ?? ""}
              loading={vlanQuery.isLoading}
              error={vlanQuery.error ? toApiError(vlanQuery.error).message : null}
              onRetry={() => vlanQuery.refetch()}
              emptyTitle="No VLANs"
              emptyDescription="Add a VLAN interface to segment traffic."
              dense
            />
          </SectionCard>
        </Stack>
      )}

      {tab === 8 && (
        <Stack spacing={2}>
          <SectionCard
            title="DHCP leases"
            subtitle="Active DHCP leases reported by the OPNsense host"
            padded={false}
          >
            <DataTable
              columns={dhcpColumns}
              rows={(dhcpQuery.data as Array<Record<string, unknown>>) ?? []}
              getRowId={(row) => String(row.uuid ?? row.id ?? row.address ?? row.hw_address ?? JSON.stringify(row))}
              loading={dhcpQuery.isLoading}
              error={dhcpQuery.error ? toApiError(dhcpQuery.error).message : null}
              onRetry={() => dhcpQuery.refetch()}
              emptyTitle="No DHCP leases"
              emptyDescription="Leases appear here once the DHCP server hands out addresses."
              dense
            />
          </SectionCard>
        </Stack>
      )}

      {tab === 9 && (
        <Stack spacing={2}>
          <SectionCard
            title="DNS records"
            subtitle="Host records configured on the OPNsense host"
            padded={false}
          >
            <DataTable
              columns={dnsColumns}
              rows={(dnsQuery.data as Array<Record<string, unknown>>) ?? []}
              getRowId={(row) => String(row.uuid ?? row.id ?? row.hostname ?? row.name ?? JSON.stringify(row))}
              loading={dnsQuery.isLoading}
              error={dnsQuery.error ? toApiError(dnsQuery.error).message : null}
              onRetry={() => dnsQuery.refetch()}
              emptyTitle="No DNS records"
              emptyDescription="Host records appear here once they are configured on the device."
              dense
            />
          </SectionCard>
        </Stack>
      )}
    </>
  );
}

export default DeviceDetailPage;

