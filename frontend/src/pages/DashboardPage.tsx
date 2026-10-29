import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Alert as MuiAlert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid,
  IconButton,
  LinearProgress,
  Stack,
  TextField,
  MenuItem,
  Tooltip,
  Typography,
  alpha,
  useTheme,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import DnsOutlinedIcon from "@mui/icons-material/DnsOutlined";
import WarningAmberOutlinedIcon from "@mui/icons-material/WarningAmberOutlined";
import ErrorOutlineOutlinedIcon from "@mui/icons-material/ErrorOutlineOutlined";
import VerifiedOutlinedIcon from "@mui/icons-material/VerifiedOutlined";
import PolicyOutlinedIcon from "@mui/icons-material/PolicyOutlined";
import AddIcon from "@mui/icons-material/Add";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import BackupOutlinedIcon from "@mui/icons-material/BackupOutlined";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { alertsApi, backupsApi, complianceApi, metricsApi } from "@/api/endpoints";
import { qk } from "@/api/queryKeys";
import type { Alert, DeviceHealth } from "@/api/types";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import PageHeader from "@/components/PageHeader";
import SeverityChip from "@/components/SeverityChip";
import StatCard from "@/components/StatCard";
import StatusChip from "@/components/StatusChip";
import { PermissionGate } from "@/components/RequireAuth";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { formatBits, formatDateTime, formatDuration, formatNumber, formatPercent, fromNow } from "@/utils/format";

const SEVERITY_COLORS: Record<string, string> = {
  info: "#0891b2",
  warning: "#d97706",
  critical: "#dc2626",
};

function HealthBar({ value, label }: { value: number | null; label: string }) {
  const theme = useTheme();
  if (value === null || value === undefined) {
    return (
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="caption" color="text.disabled" sx={{ minWidth: 36 }}>
          {label}
        </Typography>
        <Typography variant="caption" color="text.disabled">
          n/a
        </Typography>
      </Stack>
    );
  }
  const color =
    value >= 90 ? theme.palette.error.main : value >= 75 ? theme.palette.warning.main : theme.palette.success.main;
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <Typography variant="caption" color="text.secondary" sx={{ minWidth: 36 }}>
        {label}
      </Typography>
      <LinearProgress
        variant="determinate"
        value={Math.min(100, Math.max(0, value))}
        sx={{ flex: 1, height: 6, borderRadius: 3, bgcolor: alpha(color, 0.14), "& .MuiLinearProgress-bar": { bgcolor: color } }}
      />
      <Typography variant="caption" sx={{ minWidth: 38, textAlign: "right" }}>
        {value.toFixed(0)}%
      </Typography>
    </Stack>
  );
}

export function DashboardPage() {
  const theme = useTheme();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const dispatch = useAppDispatch();
  const [params] = useSearchParams();

  const dashboard = useQuery({
    queryKey: qk.dashboard,
    queryFn: () => metricsApi.dashboard(),
    refetchInterval: 60_000,
  });

  const [trafficInterface, setTrafficInterface] = useState("wan");
  const [trafficHours, setTrafficHours] = useState(24);

  const traffic = useQuery({
    queryKey: qk.fleetTraffic(trafficInterface, trafficHours),
    queryFn: () => metricsApi.fleetTraffic(trafficInterface, trafficHours),
    refetchInterval: 60_000,
  });

  const acknowledge = useMutation({
    mutationFn: (alertId: string) => alertsApi.acknowledge(alertId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["alerts"] });
      void queryClient.invalidateQueries({ queryKey: qk.dashboard });
      dispatch(showToast({ message: "Alert acknowledged", severity: "success" }));
    },
    onError: (error: Error) => dispatch(showToast({ message: error.message, severity: "error" })),
  });

  const runCompliance = useMutation({
    mutationFn: () => complianceApi.run({ framework: "cis" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["compliance"] });
      dispatch(showToast({ message: "CIS compliance evaluation started", severity: "success" }));
    },
    onError: (error: Error) => dispatch(showToast({ message: error.message, severity: "error" })),
  });

  const runBackups = useMutation({
    mutationFn: () => backupsApi.sweep("scheduled"),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["backups"] });
      dispatch(
        showToast({
          message: `Backup sweep finished: ${formatNumber(Number(result.ok ?? 0))} succeeded`,
          severity: "success",
        }),
      );
    },
    onError: (error: Error) => dispatch(showToast({ message: error.message, severity: "error" })),
  });

  useEffect(() => {
    if (params.get("focus") === "alerts") {
      document.getElementById("alerts")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [params]);

  const data = dashboard.data;
  const summary = data?.summary;

  const healthColumns: Array<DataTableColumn<DeviceHealth>> = [
    {
      key: "name",
      label: "Device",
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <DnsOutlinedIcon fontSize="small" color="action" />
          <Typography variant="body2" fontWeight={600}>
            {row.name}
          </Typography>
        </Stack>
      ),
    },
    { key: "status", label: "Status", render: (row) => <StatusChip status={row.status} /> },
    {
      key: "cpu",
      label: "CPU",
      width: 150,
      render: (row) => <HealthBar value={row.cpu_pct} label="CPU" />,
    },
    {
      key: "memory",
      label: "Memory",
      width: 150,
      render: (row) => <HealthBar value={row.memory_pct} label="MEM" />,
    },
    {
      key: "disk",
      label: "Disk",
      width: 150,
      render: (row) => <HealthBar value={row.disk_pct} label="DSK" />,
    },
    {
      key: "traffic_in",
      label: "RX",
      width: 130,
      hideBelow: "md",
      render: (row) => (row.in_bps != null ? formatBits(row.in_bps) : <Typography variant="body2" color="text.disabled">—</Typography>),
    },
    {
      key: "traffic_out",
      label: "TX",
      width: 130,
      hideBelow: "md",
      render: (row) => (row.out_bps != null ? formatBits(row.out_bps) : <Typography variant="body2" color="text.disabled">—</Typography>),
    },
    {
      key: "vpn",
      label: "VPN",
      align: "center",
      hideBelow: "md",
      render: (row) =>
        row.vpn_total ? (
          <Typography variant="body2">
            {row.vpn_up}/{row.vpn_total}
          </Typography>
        ) : (
          <Typography variant="body2" color="text.disabled">
            —
          </Typography>
        ),
    },
    {
      key: "uptime",
      label: "Uptime",
      hideBelow: "lg",
      render: (row) => formatDuration(row.uptime_seconds),
    },
    {
      key: "recorded",
      label: "Last sample",
      hideBelow: "lg",
      render: (row) => (row.recorded_at ? fromNow(row.recorded_at) : "—"),
    },
  ];

  const alertColumns: Array<DataTableColumn<Alert>> = [
    { key: "severity", label: "Severity", width: 100, render: (row) => <SeverityChip severity={row.severity} /> },
    {
      key: "title",
      label: "Alert",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.title}
          </Typography>
          {row.message && (
            <Typography variant="caption" color="text.secondary" display="block" noWrap sx={{ maxWidth: 520 }}>
              {row.message}
            </Typography>
          )}
        </Box>
      ),
    },
    { key: "status", label: "Status", width: 130, render: (row) => <StatusChip status={row.status} /> },
    { key: "started", label: "Started", width: 140, hideBelow: "md", render: (row) => fromNow(row.starts_at) },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 120,
      render: (row) =>
        row.status === "firing" ? (
          <Button
            size="small"
            onClick={(event) => {
              event.stopPropagation();
              acknowledge.mutate(row.id);
            }}
            disabled={acknowledge.isPending}
          >
            Acknowledge
          </Button>
        ) : (
          <Typography variant="caption" color="text.disabled">
            {row.acknowledged_at ? formatDateTime(row.acknowledged_at) : "—"}
          </Typography>
        ),
    },
  ];

  const trends = data?.trends ?? [];
  const severityEntries = Object.entries(data?.top_alerts_by_severity ?? {}).filter(([, value]) => value > 0);
  const trafficData = traffic.data;
  const trafficPoints = useMemo(
    () =>
      (trafficData?.points ?? []).map((point) => ({
        timestamp: point.recorded_at,
        in_bps: point.in_bps,
        out_bps: point.out_bps,
      })),
    [trafficData],
  );

  return (
    <>
      <PageHeader
        title="Fleet overview"
        subtitle="Live posture across every managed firewall, policy and tunnel."
        actions={
          <>
            <Tooltip title="Refresh now">
              <span>
                <IconButton onClick={() => dashboard.refetch()} disabled={dashboard.isFetching}>
                  <RefreshIcon />
                </IconButton>
              </span>
            </Tooltip>
            <PermissionGate permission="device:write">
              <Button variant="outlined" startIcon={<AddIcon />} onClick={() => navigate("/devices?new=1")}>
                Add device
              </Button>
            </PermissionGate>
            <PermissionGate permission="compliance:run">
              <Button
                variant="outlined"
                startIcon={<PlayArrowIcon />}
                onClick={() => runCompliance.mutate()}
                disabled={runCompliance.isPending}
              >
                Run CIS scan
              </Button>
            </PermissionGate>
            <PermissionGate permission="backup:create">
              <Button
                variant="contained"
                startIcon={<BackupOutlinedIcon />}
                onClick={() => runBackups.mutate()}
                disabled={runBackups.isPending}
              >
                Backup all
              </Button>
            </PermissionGate>
          </>
        }
        meta={
          data && (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
              <Chip size="small" variant="outlined" label={`Updated ${formatDateTime(data.generated_at)}`} />
              {dashboard.isFetching && <Chip size="small" color="info" label="Refreshing" />}
            </Stack>
          )
        }
      />

      {dashboard.error && (
        <MuiAlert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" size="small" onClick={() => dashboard.refetch()}>
              Retry
            </Button>
          }
        >
          {(dashboard.error as Error).message}
        </MuiAlert>
      )}

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} lg={2.4}>
          <StatCard
            label="Devices online"
            value={summary ? `${formatNumber(summary.devices_online)} / ${formatNumber(summary.devices_total)}` : "—"}
            icon={DnsOutlinedIcon}
            tone="success"
            hint={summary ? `${formatNumber(summary.devices_offline)} offline · ${formatNumber(summary.devices_error)} error` : undefined}
            onClick={() => navigate("/devices")}
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={2.4}>
          <StatCard
            label="Open alerts"
            value={formatNumber(summary?.open_alerts)}
            icon={WarningAmberOutlinedIcon}
            tone={(summary?.critical_alerts ?? 0) > 0 ? "error" : "warning"}
            hint={summary ? `${formatNumber(summary.critical_alerts)} critical` : undefined}
            onClick={() => document.getElementById("alerts")?.scrollIntoView({ behavior: "smooth" })}
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={2.4}>
          <StatCard
            label="Compliance score"
            value={summary ? formatPercent(summary.compliance_score, 1) : "—"}
            icon={VerifiedOutlinedIcon}
            tone={
              !summary || summary.compliance_score === null
                ? "neutral"
                : summary.compliance_score >= 90
                  ? "success"
                  : summary.compliance_score >= 70
                    ? "warning"
                    : "error"
            }
            hint="Latest framework evaluation"
            onClick={() => navigate("/compliance")}
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={2.4}>
          <StatCard
            label="Policy drift"
            value={formatNumber(summary?.policies_drifted)}
            icon={PolicyOutlinedIcon}
            tone={(summary?.policies_drifted ?? 0) > 0 ? "warning" : "success"}
            hint={summary ? `${formatNumber(summary.policies_total)} policies tracked` : undefined}
            onClick={() => navigate("/policies?tab=drift")}
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={2.4}>
          <StatCard
            label="SD-WAN tunnels"
            value={summary ? `${formatNumber(summary.tunnels_up)} / ${formatNumber(summary.tunnels_total)}` : "—"}
            icon={ErrorOutlineOutlinedIcon}
            tone={summary && summary.tunnels_up < summary.tunnels_total ? "warning" : "info"}
            hint="Active over configured"
            onClick={() => navigate("/sdwan")}
          />
        </Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} lg={8}>
          <Card sx={{ height: 360 }}>
            <CardContent sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Box>
                  <Typography variant="h5">Availability trend</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Online and offline devices over the reporting window
                  </Typography>
                </Box>
                <Chip size="small" variant="outlined" label={`${trends.length} points`} />
              </Stack>
              <Box sx={{ flex: 1, minHeight: 0 }}>
                {trends.length === 0 ? (
                  <Stack alignItems="center" justifyContent="center" sx={{ height: "100%" }}>
                    <Typography variant="body2" color="text.secondary">
                      Telemetry is still being collected for this window.
                    </Typography>
                  </Stack>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={trends} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                      <defs>
                        <linearGradient id="onlineGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={theme.palette.success.main} stopOpacity={0.35} />
                          <stop offset="95%" stopColor={theme.palette.success.main} stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="offlineGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={theme.palette.error.main} stopOpacity={0.3} />
                          <stop offset="95%" stopColor={theme.palette.error.main} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} vertical={false} />
                      <XAxis
                        dataKey="timestamp"
                        tickFormatter={(value: string) => (value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "")}
                        tick={{ fontSize: 11, fill: theme.palette.text.secondary }}
                        stroke={theme.palette.divider}
                        minTickGap={24}
                      />
                      <YAxis tick={{ fontSize: 11, fill: theme.palette.text.secondary }} stroke={theme.palette.divider} allowDecimals={false} />
                      <RechartsTooltip
                        labelFormatter={(value) => new Date(String(value)).toLocaleString()}
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
                        dataKey="online"
                        name="Online"
                        stroke={theme.palette.success.main}
                        fill="url(#onlineGradient)"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                      <Area
                        type="monotone"
                        dataKey="offline"
                        name="Offline"
                        stroke={theme.palette.error.main}
                        fill="url(#offlineGradient)"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </Box>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Card sx={{ height: 360 }}>
            <CardContent sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
              <Typography variant="h5">Open alerts by severity</Typography>
              <Typography variant="caption" color="text.secondary">
                Current firing alerts
              </Typography>
              <Box sx={{ flex: 1, minHeight: 0 }}>
                {severityEntries.length === 0 ? (
                  <Stack alignItems="center" justifyContent="center" spacing={1} sx={{ height: "100%" }}>
                    <CheckCircleOutlineIcon color="success" fontSize="large" />
                    <Typography variant="body2" color="text.secondary">
                      No open alerts. The fleet is quiet.
                    </Typography>
                  </Stack>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={severityEntries.map(([name, value]) => ({ name, value }))}
                        dataKey="value"
                        nameKey="name"
                        innerRadius="52%"
                        outerRadius="78%"
                        paddingAngle={3}
                        isAnimationActive={false}
                      >
                        {severityEntries.map(([name]) => (
                          <Cell key={name} fill={SEVERITY_COLORS[name] ?? theme.palette.text.disabled} />
                        ))}
                      </Pie>
                      <RechartsTooltip
                        contentStyle={{
                          background: theme.palette.background.paper,
                          border: `1px solid ${theme.palette.divider}`,
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                      />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} lg={8}>
          <Card sx={{ height: 340 }}>
            <CardContent sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Box>
                  <Typography variant="h5">Interface throughput</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Aggregate received and transmitted traffic across the fleet
                  </Typography>
                </Box>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
                  <TextField
                    select
                    value={trafficInterface}
                    onChange={(e) => setTrafficInterface(e.target.value)}
                    sx={{ width: 180, minWidth: 150 }}
                    size="small"
                  >
                    <MenuItem value="wan">WAN</MenuItem>
                    <MenuItem value="lan">LAN</MenuItem>
                    <MenuItem value="opt1">OPT1</MenuItem>
                    <MenuItem value="opt2">OPT2</MenuItem>
                    <MenuItem value="opt3">OPT3</MenuItem>
                    <MenuItem value="opt4">OPT4</MenuItem>
                  </TextField>
                  <TextField
                    select
                    value={trafficHours}
                    onChange={(e) => setTrafficHours(Number(e.target.value))}
                    sx={{ width: 120, minWidth: 100 }}
                    size="small"
                  >
                    <MenuItem value={6}>6 hours</MenuItem>
                    <MenuItem value={24}>24 hours</MenuItem>
                    <MenuItem value={72}>3 days</MenuItem>
                    <MenuItem value={168}>7 days</MenuItem>
                  </TextField>
                  {traffic.isFetching && <Chip size="small" color="info" label="Refreshing" />}
                  <Chip
                    size="small"
                    variant="outlined"
                    label={trafficData ? `${formatNumber(trafficData.bucket_seconds)}s buckets` : `${trafficHours}h`}
                  />
                </Stack>
              </Stack>
              <Box sx={{ flex: 1, minHeight: 0 }}>
                {traffic.isError ? (
                  <Stack alignItems="center" justifyContent="center" spacing={1} sx={{ height: "100%" }}>
                    <Typography variant="body2" color="text.secondary">
                      Interface counters are unavailable.
                    </Typography>
                    <Button size="small" onClick={() => traffic.refetch()}>
                      Retry
                    </Button>
                  </Stack>
                ) : trafficPoints.length === 0 ? (
                  <Stack alignItems="center" justifyContent="center" sx={{ height: "100%" }}>
                    <Typography variant="body2" color="text.secondary">
                      {traffic.isLoading
                        ? "Loading traffic counters…"
                        : "No traffic samples for this interface in this window. The first rate appears after two counter polls."}
                    </Typography>
                  </Stack>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={trafficPoints} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                      <defs>
                        <linearGradient id="inGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={theme.palette.info.main} stopOpacity={0.35} />
                          <stop offset="95%" stopColor={theme.palette.info.main} stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="outGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={theme.palette.warning.main} stopOpacity={0.3} />
                          <stop offset="95%" stopColor={theme.palette.warning.main} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} vertical={false} />
                      <XAxis
                        dataKey="timestamp"
                        tickFormatter={(value: string) =>
                          value
                            ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                            : ""
                        }
                        tick={{ fontSize: 11, fill: theme.palette.text.secondary }}
                        stroke={theme.palette.divider}
                        minTickGap={24}
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
                        fill="url(#inGradient)"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                      <Area
                        type="monotone"
                        dataKey="out_bps"
                        name="Transmitted"
                        stroke={theme.palette.warning.main}
                        fill="url(#outGradient)"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </Box>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Card sx={{ height: 340 }}>
            <CardContent sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
              <Typography variant="h5">Latest rates</Typography>
              <Typography variant="caption" color="text.secondary">
                Per device, sampled in the last 30 minutes
              </Typography>
              <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto", mt: 1 }}>
                {(trafficData?.devices.length ?? 0) === 0 ? (
                  <Stack alignItems="center" justifyContent="center" sx={{ height: "100%" }}>
                    <Typography variant="body2" color="text.secondary" textAlign="center">
                      No device reported counters for this interface in the last 30 minutes.
                    </Typography>
                  </Stack>
                ) : (
                  <Stack divider={<Divider flexItem />} spacing={1}>
                    {trafficData?.devices.map((device) => (
                      <Stack
                        key={device.device_id}
                        direction="row"
                        justifyContent="space-between"
                        alignItems="center"
                        spacing={1}
                        sx={{ cursor: "pointer" }}
                        onClick={() => navigate(`/devices/${device.device_id}`)}
                      >
                        <Box sx={{ minWidth: 0 }}>
                          <Typography variant="body2" fontWeight={600} noWrap>
                            {device.name}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {device.interface_name} · {fromNow(device.recorded_at)}
                          </Typography>
                        </Box>
                        <Box sx={{ textAlign: "right" }}>
                          <Typography variant="body2" color="info.main">
                            ↓ {formatBits(device.in_bps)}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            ↑ {formatBits(device.out_bps)}
                          </Typography>
                        </Box>
                      </Stack>
                    ))}
                  </Stack>
                )}
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid item xs={12} xl={7}>
          <Box id="alerts">
            <DataTable
              columns={alertColumns}
              rows={data?.alerts ?? []}
              getRowId={(row) => row.id}
              loading={dashboard.isLoading}
              error={dashboard.error ? (dashboard.error as Error).message : null}
              onRetry={() => dashboard.refetch()}
              emptyTitle="No open alerts"
              emptyDescription="Alerts raised by the monitoring engine appear here in real time."
              onRowClick={() => navigate("/dashboard?focus=alerts")}
              toolbar={
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Box>
                    <Typography variant="h5">Recent alerts</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Acknowledge to stop escalation
                    </Typography>
                  </Box>
                  <Chip size="small" label={`${data?.alerts?.length ?? 0} shown`} variant="outlined" />
                </Stack>
              }
            />
          </Box>
        </Grid>
        <Grid item xs={12} xl={5}>
          <Card sx={{ height: "100%" }}>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Box>
                  <Typography variant="h5">Fleet health</Typography>
                  <Typography variant="caption" color="text.secondary">
                    Latest heartbeat sample per device
                  </Typography>
                </Box>
                <Button size="small" onClick={() => navigate("/devices")}>
                  All devices
                </Button>
              </Stack>
              <Divider sx={{ mb: 1 }} />
              {(data?.health ?? []).length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
                  No heartbeat telemetry yet.
                </Typography>
              ) : (
                <Stack spacing={1.5}>
                  {(data?.health ?? []).slice(0, 6).map((row) => (
                    <Box key={row.device_id}>
                      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <DnsOutlinedIcon fontSize="small" color="action" />
                          <Typography variant="body2" fontWeight={600}>
                            {row.name}
                          </Typography>
                          <StatusChip status={row.status} />
                        </Stack>
                        <Typography variant="caption" color="text.secondary">
                          {row.gateways_total
                            ? `${row.gateways_up}/${row.gateways_total} gateways`
                            : row.carp_status ?? ""}
                        </Typography>
                      </Stack>
                      <Stack direction="row" spacing={2}>
                        <HealthBar value={row.cpu_pct} label="CPU" />
                        <HealthBar value={row.memory_pct} label="MEM" />
                      </Stack>
                    </Box>
                  ))}
                  {(data?.health ?? []).length > 6 && (
                    <Button size="small" onClick={() => navigate("/devices")}>
                      View all {data?.health.length} reporting devices
                    </Button>
                  )}
                </Stack>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Box sx={{ mt: 2 }}>
        <DataTable
          columns={healthColumns}
          rows={data?.health ?? []}
          getRowId={(row) => row.device_id}
          loading={dashboard.isLoading}
          error={dashboard.error ? (dashboard.error as Error).message : null}
          onRetry={() => dashboard.refetch()}
          emptyTitle="No device telemetry"
          emptyDescription="Devices with the os-fleet-agent installed report health automatically."
          onRowClick={(row) => navigate(`/devices/${row.device_id}`)}
          toolbar={
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Box>
                <Typography variant="h5">Device health</Typography>
                <Typography variant="caption" color="text.secondary">
                  CPU, memory, disk and tunnel status
                </Typography>
              </Box>
              <Chip size="small" label={`${data?.health?.length ?? 0} devices`} variant="outlined" />
            </Stack>
          }
        />
      </Box>
    </>
  );
}

export default DashboardPage;
