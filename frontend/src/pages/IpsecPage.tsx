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
import SecurityOutlinedIcon from "@mui/icons-material/SecurityOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { devicesApi, ipsecApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type {
  IpsecPhase1,
  IpsecPhase1Payload,
  IpsecPhase2,
  IpsecPhase2Payload,
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
import { EMPTY, formatNumber } from "@/utils/format";

interface Phase1FormState {
  device_id: string;
  name: string;
  description: string;
  enabled: boolean;
  iketype: "ikev1" | "ikev2";
  interface: string;
  remote_gateway: string;
  local_gateway: string;
  authentication_method: string;
  pre_shared_key: string;
  my_identifier: string;
  peer_identifier: string;
  encryption: string;
  hash: string;
  dh_group: string;
  lifetime: string;
  dpd_delay: string;
  dpd_maxfail: string;
  nat_traversal: string;
}

interface Phase2FormState {
  device_id: string;
  phase1_id: string;
  name: string;
  description: string;
  enabled: boolean;
  mode: string;
  protocol: string;
  local_net: string;
  remote_net: string;
  encryption: string;
  hash: string;
  pfs_group: string;
  lifetime: string;
}

const EMPTY_PHASE1: Phase1FormState = {
  device_id: "",
  name: "",
  description: "",
  enabled: true,
  iketype: "ikev2",
  interface: "wan",
  remote_gateway: "",
  local_gateway: "",
  authentication_method: "pre_shared_key",
  pre_shared_key: "",
  my_identifier: "",
  peer_identifier: "",
  encryption: "aes256gcm16",
  hash: "sha256",
  dh_group: "14",
  lifetime: "28800",
  dpd_delay: "10",
  dpd_maxfail: "5",
  nat_traversal: "force",
};

const EMPTY_PHASE2: Phase2FormState = {
  device_id: "",
  phase1_id: "",
  name: "",
  description: "",
  enabled: true,
  mode: "tunnel",
  protocol: "esp",
  local_net: "",
  remote_net: "",
  encryption: "aes256gcm16",
  hash: "sha256",
  pfs_group: "14",
  lifetime: "3600",
};

const IKE_TYPES = [
  { value: "ikev1", label: "IKEv1" },
  { value: "ikev2", label: "IKEv2" },
];

const AUTH_METHODS = [
  { value: "pre_shared_key", label: "Pre-shared Key" },
  { value: "rsa", label: "RSA" },
  { value: "ecdsa", label: "ECDSA" },
  { value: "x509", label: "X.509" },
];

const ENCRYPTION_ALGOS = [
  { value: "aes256gcm16", label: "AES-256-GCM" },
  { value: "aes256cbc", label: "AES-256-CBC" },
  { value: "aes128gcm16", label: "AES-128-GCM" },
  { value: "3des", label: "3DES" },
];

const HASH_ALGOS = [
  { value: "sha256", label: "SHA-256" },
  { value: "sha384", label: "SHA-384" },
  { value: "sha512", label: "SHA-512" },
  { value: "sha1", label: "SHA-1" },
];

const DH_GROUPS = [
  { value: "14", label: "14 (2048-bit)" },
  { value: "15", label: "15 (3072-bit)" },
  { value: "16", label: "16 (4096-bit)" },
  { value: "19", label: "19 (256-bit ECP)" },
  { value: "20", label: "20 (384-bit ECP)" },
  { value: "21", label: "21 (521-bit ECP)" },
];

const NAT_TRAVERSAL_OPTIONS = [
  { value: "force", label: "Force" },
  { value: "auto", label: "Auto" },
  { value: "disable", label: "Disable" },
];

const MODE_OPTIONS = [
  { value: "tunnel", label: "Tunnel" },
  { value: "transport", label: "Transport" },
];

const PROTOCOL_OPTIONS = [
  { value: "esp", label: "ESP" },
  { value: "ah", label: "AH" },
  { value: "esp-ah", label: "ESP+AH" },
];

export function IpsecPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState(0);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);
  const [deviceFilter, setDeviceFilter] = useState("");
  const [phase1Filter, setPhase1Filter] = useState("");

  const [phase1DialogOpen, setPhase1DialogOpen] = useState(false);
  const [editingPhase1, setEditingPhase1] = useState<IpsecPhase1 | null>(null);
  const [phase1Form, setPhase1Form] = useState<Phase1FormState>(EMPTY_PHASE1);
  const [phase1Error, setPhase1Error] = useState<string | null>(null);
  const [deletePhase1, setDeletePhase1] = useState<IpsecPhase1 | null>(null);

  const [phase2DialogOpen, setPhase2DialogOpen] = useState(false);
  const [editingPhase2, setEditingPhase2] = useState<IpsecPhase2 | null>(null);
  const [phase2Form, setPhase2Form] = useState<Phase2FormState>(EMPTY_PHASE2);
  const [phase2Error, setPhase2Error] = useState<string | null>(null);
  const [deletePhase2, setDeletePhase2] = useState<IpsecPhase2 | null>(null);

  const [applyOpen, setApplyOpen] = useState(false);
  const [dryRun, setDryRun] = useState(false);

  const devicesQuery = useQuery({
    queryKey: qk.devices.list({ size: 200, sort: "name", order: "asc" }),
    queryFn: () => devicesApi.list({ size: 200, sort: "name", order: "asc" }),
    staleTime: 60_000,
  });

  const phase1Query = useQuery({
    queryKey: qk.ipsec.phase1({
      page,
      size,
      search: debouncedSearch || undefined,
      device_id: deviceFilter || undefined,
    }),
    queryFn: () =>
      ipsecApi.phase1({
        page,
        size,
        search: debouncedSearch || undefined,
        device_id: deviceFilter || undefined,
      }),
  });

  const phase2Query = useQuery({
    queryKey: qk.ipsec.phase2({
      page,
      size,
      search: debouncedSearch || undefined,
      device_id: deviceFilter || undefined,
    }),
    queryFn: () =>
      ipsecApi.phase2({
        page,
        size,
        search: debouncedSearch || undefined,
        device_id: deviceFilter || undefined,
      }),
  });

  const phase1OptionsQuery = useQuery({
    queryKey: qk.ipsec.phase1({ size: 500, sort: "name", order: "asc" }),
    queryFn: () => ipsecApi.phase1({ size: 500, sort: "name", order: "asc" }),
    staleTime: 30_000,
  });

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, deviceFilter, tab]);

  useEffect(() => {
    setSearch("");
    setPage(1);
  }, [tab]);

  const devices = useMemo(() => devicesQuery.data?.items ?? [], [devicesQuery.data]);
  const phase1Options = useMemo(
    () => phase1OptionsQuery.data?.items ?? [],
    [phase1OptionsQuery.data],
  );
  const deviceName = useMemo(() => {
    const map = new Map(devices.map((device) => [device.id, device.name]));
    return (id: string) => map.get(id) ?? id;
  }, [devices]);
  const phase1Name = useMemo(() => {
    const map = new Map(phase1Options.map((p1) => [p1.id, `${p1.name} (${p1.remote_gateway})`]));
    return (id: string) => map.get(id) ?? id;
  }, [phase1Options]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.ipsec.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const savePhase1 = useMutation({
    mutationFn: () => {
      const payload: IpsecPhase1Payload = {
        device_id: phase1Form.device_id,
        name: phase1Form.name.trim(),
        description: phase1Form.description.trim() || null,
        enabled: phase1Form.enabled,
        iketype: phase1Form.iketype,
        interface: phase1Form.interface.trim() || "wan",
        remote_gateway: phase1Form.remote_gateway.trim(),
        local_gateway: phase1Form.local_gateway.trim() || null,
        authentication_method: phase1Form.authentication_method,
        pre_shared_key: phase1Form.pre_shared_key.trim() || null,
        my_identifier: phase1Form.my_identifier.trim() || null,
        peer_identifier: phase1Form.peer_identifier.trim() || null,
        encryption: [phase1Form.encryption],
        hash: [phase1Form.hash],
        dh_group: phase1Form.dh_group,
        lifetime: Number(phase1Form.lifetime) || 28800,
        dpd_delay: Number(phase1Form.dpd_delay) || 10,
        dpd_maxfail: Number(phase1Form.dpd_maxfail) || 5,
        nat_traversal: phase1Form.nat_traversal as "force" | "auto" | "disable",
      };
      if (editingPhase1) {
        return ipsecApi.updatePhase1(editingPhase1.id, {
          description: payload.description,
          enabled: payload.enabled,
          iketype: payload.iketype,
          interface: payload.interface,
          remote_gateway: payload.remote_gateway,
          local_gateway: payload.local_gateway,
          authentication_method: payload.authentication_method,
          pre_shared_key: payload.pre_shared_key,
          my_identifier: payload.my_identifier,
          peer_identifier: payload.peer_identifier,
          encryption: payload.encryption,
          hash: payload.hash,
          dh_group: payload.dh_group,
          lifetime: payload.lifetime,
          dpd_delay: payload.dpd_delay,
          dpd_maxfail: payload.dpd_maxfail,
          nat_traversal: payload.nat_traversal,
        });
      }
      return ipsecApi.createPhase1(payload);
    },
    onSuccess: (phase1) => {
      invalidate();
      setPhase1DialogOpen(false);
      setEditingPhase1(null);
      setPhase1Form(EMPTY_PHASE1);
      setPhase1Error(null);
      dispatch(showToast({ message: `IPsec Phase 1 ${phase1.name} saved`, severity: "success" }));
    },
    onError: (error) => setPhase1Error(toApiError(error).message),
  });

  const deletePhase1Mutation = useMutation({
    mutationFn: (id: string) => ipsecApi.removePhase1(id),
    onSuccess: () => {
      invalidate();
      setDeletePhase1(null);
      dispatch(showToast({ message: "IPsec Phase 1 deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const savePhase2 = useMutation({
    mutationFn: () => {
      const payload: IpsecPhase2Payload = {
        device_id: phase2Form.device_id,
        phase1_id: phase2Form.phase1_id,
        name: phase2Form.name.trim(),
        description: phase2Form.description.trim() || null,
        enabled: phase2Form.enabled,
        mode: phase2Form.mode,
        protocol: phase2Form.protocol,
        local_net: phase2Form.local_net.trim(),
        remote_net: phase2Form.remote_net.trim(),
        encryption: [phase2Form.encryption],
        hash: [phase2Form.hash],
        pfs_group: phase2Form.pfs_group,
        lifetime: Number(phase2Form.lifetime) || 3600,
      };
      if (editingPhase2) {
        return ipsecApi.updatePhase2(editingPhase2.id, {
          description: payload.description,
          enabled: payload.enabled,
          mode: payload.mode,
          protocol: payload.protocol,
          local_net: payload.local_net,
          remote_net: payload.remote_net,
          encryption: payload.encryption,
          hash: payload.hash,
          pfs_group: payload.pfs_group,
          lifetime: payload.lifetime,
        });
      }
      return ipsecApi.createPhase2(payload);
    },
    onSuccess: (phase2) => {
      invalidate();
      setPhase2DialogOpen(false);
      setEditingPhase2(null);
      setPhase2Form(EMPTY_PHASE2);
      setPhase2Error(null);
      dispatch(showToast({ message: `IPsec Phase 2 ${phase2.name} saved`, severity: "success" }));
    },
    onError: (error) => setPhase2Error(toApiError(error).message),
  });

  const deletePhase2Mutation = useMutation({
    mutationFn: (id: string) => ipsecApi.removePhase2(id),
    onSuccess: () => {
      invalidate();
      setDeletePhase2(null);
      dispatch(showToast({ message: "IPsec Phase 2 deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const applyMutation = useMutation({
    mutationFn: () => ipsecApi.apply({ device_id: deviceFilter, dry_run: dryRun, apply: !dryRun }),
    onSuccess: () => {
      setApplyOpen(false);
      dispatch(
        showToast({
          message: dryRun ? "Dry run completed — review the API response" : "IPsec configuration applied",
          severity: "success",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreatePhase1 = () => {
    setEditingPhase1(null);
    setPhase1Form({ ...EMPTY_PHASE1, device_id: deviceFilter || devices[0]?.id || "" });
    setPhase1Error(null);
    setPhase1DialogOpen(true);
  };

  const openEditPhase1 = (phase1: IpsecPhase1) => {
    setEditingPhase1(phase1);
    setPhase1Form({
      device_id: phase1.device_id,
      name: phase1.name,
      description: phase1.description ?? "",
      enabled: phase1.enabled,
      iketype: phase1.iketype,
      interface: phase1.interface,
      remote_gateway: phase1.remote_gateway,
      local_gateway: phase1.local_gateway ?? "",
      authentication_method: phase1.authentication_method,
      pre_shared_key: "",
      my_identifier: phase1.my_identifier ?? "",
      peer_identifier: phase1.peer_identifier ?? "",
      encryption: phase1.encryption[0] ?? "aes256gcm16",
      hash: phase1.hash[0] ?? "sha256",
      dh_group: phase1.dh_group,
      lifetime: String(phase1.lifetime),
      dpd_delay: String(phase1.dpd_delay),
      dpd_maxfail: String(phase1.dpd_maxfail),
      nat_traversal: phase1.nat_traversal,
    });
    setPhase1Error(null);
    setPhase1DialogOpen(true);
  };

  const openCreatePhase2 = () => {
    setEditingPhase2(null);
    setPhase2Form({
      ...EMPTY_PHASE2,
      device_id: deviceFilter || devices[0]?.id || "",
      phase1_id: phase1Filter || phase1Options[0]?.id || "",
    });
    setPhase2Error(null);
    setPhase2DialogOpen(true);
  };

  const openEditPhase2 = (phase2: IpsecPhase2) => {
    setEditingPhase2(phase2);
    setPhase2Form({
      device_id: phase2.device_id,
      phase1_id: phase2.phase1_id,
      name: phase2.name,
      description: phase2.description ?? "",
      enabled: phase2.enabled,
      mode: phase2.mode,
      protocol: phase2.protocol,
      local_net: phase2.local_net,
      remote_net: phase2.remote_net,
      encryption: phase2.encryption[0] ?? "aes256gcm16",
      hash: phase2.hash[0] ?? "sha256",
      pfs_group: phase2.pfs_group,
      lifetime: String(phase2.lifetime),
    });
    setPhase2Error(null);
    setPhase2DialogOpen(true);
  };

  const phase1Columns: Array<DataTableColumn<IpsecPhase1>> = [
    {
      key: "name",
      label: "Phase 1 Configuration",
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <SecurityOutlinedIcon fontSize="small" color="action" />
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
    {
      key: "iketype",
      label: "IKE Type",
      width: 100,
      render: (row) => <Chip size="small" variant="outlined" label={row.iketype} />,
    },
    {
      key: "remote_gateway",
      label: "Remote Gateway",
      width: 160,
      monospace: true,
      hideBelow: "md",
    },
    {
      key: "authentication_method",
      label: "Auth Method",
      width: 140,
      hideBelow: "lg",
      render: (row) => row.authentication_method.replace(/_/g, " "),
    },
    {
      key: "encryption",
      label: "Encryption",
      width: 130,
      hideBelow: "lg",
      render: (row) => row.encryption[0] ?? EMPTY,
    },
    {
      key: "dh_group",
      label: "DH Group",
      width: 100,
      hideBelow: "lg",
    },
    {
      key: "lifetime",
      label: "Lifetime",
      width: 100,
      hideBelow: "sm",
      render: (row) => `${Math.floor(row.lifetime / 3600)}h`,
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
          <PermissionGate permission="policy:deploy">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEditPhase1(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="policy:deploy">
            <Tooltip title="Delete">
              <IconButton size="small" color="error" onClick={() => setDeletePhase1(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        </Stack>
      ),
    },
  ];

  const phase2Columns: Array<DataTableColumn<IpsecPhase2>> = [
    {
      key: "name",
      label: "Phase 2 Configuration",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.name}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {phase1Name(row.phase1_id)}
          </Typography>
        </Box>
      ),
    },
    {
      key: "mode",
      label: "Mode",
      width: 100,
      render: (row) => <Chip size="small" variant="outlined" label={row.mode} />,
    },
    {
      key: "protocol",
      label: "Protocol",
      width: 90,
      render: (row) => <Chip size="small" variant="outlined" label={row.protocol} />,
    },
    {
      key: "networks",
      label: "Local → Remote",
      hideBelow: "md",
      monospace: true,
      render: (row) => `${row.local_net} → ${row.remote_net}`,
    },
    {
      key: "encryption",
      label: "Encryption",
      width: 130,
      hideBelow: "lg",
      render: (row) => row.encryption[0] ?? EMPTY,
    },
    {
      key: "pfs_group",
      label: "PFS Group",
      width: 100,
      hideBelow: "lg",
    },
    {
      key: "lifetime",
      label: "Lifetime",
      width: 100,
      hideBelow: "sm",
      render: (row) => `${Math.floor(row.lifetime / 60)}m`,
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
          <PermissionGate permission="policy:deploy">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEditPhase2(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="policy:deploy">
            <Tooltip title="Delete">
              <IconButton size="small" color="error" onClick={() => setDeletePhase2(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        </Stack>
      ),
    },
  ];

  const activeQuery = tab === 0 ? phase1Query : phase2Query;
  const total = activeQuery.data?.meta.total ?? 0;
  const applyDevice = devices.find((device) => device.id === deviceFilter);

  return (
    <>
      <PageHeader
        title="IPsec VPN"
        subtitle="Site-to-site IPsec tunnel configurations with Phase 1 (IKE) and Phase 2 (IPsec) settings."
        actions={
          <Stack direction="row" spacing={1}>
            <PermissionGate permission="policy:deploy">
              <Tooltip
                title={
                  applyDevice
                    ? `Apply the stored IPsec configurations of ${applyDevice.name}`
                    : "Filter by a device to enable applying"
                }
              >
                <span>
                  <Button
                    variant="outlined"
                    onClick={() => setApplyOpen(true)}
                    disabled={!applyDevice}
                  >
                    Apply IPsec
                  </Button>
                </span>
              </Tooltip>
            </PermissionGate>
            <PermissionGate permission="policy:deploy">
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={tab === 0 ? openCreatePhase1 : openCreatePhase2}
                disabled={devices.length === 0 || (tab === 1 && phase1Options.length === 0)}
              >
                {tab === 0 ? "New Phase 1" : "New Phase 2"}
              </Button>
            </PermissionGate>
          </Stack>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${formatNumber(phase1Query.data?.meta.total ?? 0)} Phase 1 configs`} />
            <Chip
              size="small"
              variant="outlined"
              label={`${formatNumber(phase2Query.data?.meta.total ?? 0)} Phase 2 configs`}
            />
          </Stack>
        }
      />

      <Box sx={{ borderBottom: 1, borderColor: "divider", mb: 2 }}>
        <Tabs value={tab} onChange={(_, value: number) => setTab(value)}>
          <Tab label="Phase 1 (IKE)" />
          <Tab label="Phase 2 (IPsec)" />
        </Tabs>
      </Box>

      {tab === 0 ? (
        <DataTable
          columns={phase1Columns}
          rows={phase1Query.data?.items ?? []}
          getRowId={(row) => row.id}
          loading={phase1Query.isLoading}
          error={phase1Query.error ? toApiError(phase1Query.error).message : null}
          onRetry={() => phase1Query.refetch()}
          page={page}
          size={size}
          total={total}
          onPageChange={setPage}
          onSizeChange={setSize}
          emptyTitle="No IPsec Phase 1 configurations"
          emptyDescription="Create a Phase 1 configuration to define IKE negotiation parameters for site-to-site tunnels."
          emptyAction={
            <PermissionGate permission="policy:deploy">
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={openCreatePhase1}
                disabled={devices.length === 0}
              >
                New Phase 1
              </Button>
            </PermissionGate>
          }
          toolbar={
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
              <TextField
                placeholder="Search Phase 1 configs"
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
                {formatNumber(total)} configurations
              </Typography>
            </Stack>
          }
        />
      ) : (
        <DataTable
          columns={phase2Columns}
          rows={phase2Query.data?.items ?? []}
          getRowId={(row) => row.id}
          loading={phase2Query.isLoading}
          error={phase2Query.error ? toApiError(phase2Query.error).message : null}
          onRetry={() => phase2Query.refetch()}
          page={page}
          size={size}
          total={total}
          onPageChange={setPage}
          onSizeChange={setSize}
          emptyTitle="No IPsec Phase 2 configurations"
          emptyDescription="Create a Phase 2 configuration to define IPsec tunnel parameters for specific network pairs."
          emptyAction={
            <PermissionGate permission="policy:deploy">
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                onClick={openCreatePhase2}
                disabled={phase1Options.length === 0}
              >
                New Phase 2
              </Button>
            </PermissionGate>
          }
          toolbar={
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
              <TextField
                placeholder="Search Phase 2 configs"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                sx={{ width: { xs: "100%", sm: 260 } }}
              />
              <TextField
                select
                label="Phase 1"
                value={phase1Filter}
                onChange={(event) => setPhase1Filter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 240 } }}
              >
                <MenuItem value="">All Phase 1 configs</MenuItem>
                {phase1Options.map((p1) => (
                  <MenuItem key={p1.id} value={p1.id}>
                    {p1.name} · {p1.remote_gateway}
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
        open={phase1DialogOpen}
        title={editingPhase1 ? `Edit ${editingPhase1.name}` : "New IPsec Phase 1"}
        description={
          <Typography variant="body2" color="text.secondary">
            Phase 1 defines IKE negotiation parameters for establishing the secure control channel.
          </Typography>
        }
        loading={savePhase1.isPending}
        error={phase1Error}
        submitLabel={editingPhase1 ? "Save changes" : "Create Phase 1"}
        submitDisabled={
          !phase1Form.device_id ||
          !phase1Form.name.trim() ||
          !phase1Form.remote_gateway.trim()
        }
        onSubmit={() => savePhase1.mutate()}
        onClose={() => {
          setPhase1DialogOpen(false);
          setEditingPhase1(null);
        }}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Device"
            value={phase1Form.device_id}
            onChange={(event) => setPhase1Form((value) => ({ ...value, device_id: event.target.value }))}
            disabled={Boolean(editingPhase1)}
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
            value={phase1Form.name}
            onChange={(event) => setPhase1Form((value) => ({ ...value, name: event.target.value }))}
            disabled={Boolean(editingPhase1)}
            required
            autoFocus
            fullWidth
          />
        </Stack>
        <TextField
          label="Description"
          value={phase1Form.description}
          onChange={(event) => setPhase1Form((value) => ({ ...value, description: event.target.value }))}
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="IKE Type"
            value={phase1Form.iketype}
            onChange={(event) => setPhase1Form((value) => ({ ...value, iketype: event.target.value as "ikev1" | "ikev2" }))}
            fullWidth
          >
            {IKE_TYPES.map((type) => (
              <MenuItem key={type.value} value={type.value}>
                {type.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Interface"
            value={phase1Form.interface}
            onChange={(event) => setPhase1Form((value) => ({ ...value, interface: event.target.value }))}
            fullWidth
          >
            <MenuItem value="wan">WAN</MenuItem>
            <MenuItem value="lan">LAN</MenuItem>
            <MenuItem value="opt1">OPT1</MenuItem>
            <MenuItem value="opt2">OPT2</MenuItem>
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Remote Gateway"
            value={phase1Form.remote_gateway}
            onChange={(event) => setPhase1Form((value) => ({ ...value, remote_gateway: event.target.value }))}
            placeholder="203.0.113.10"
            required
            fullWidth
          />
          <TextField
            label="Local Gateway (optional)"
            value={phase1Form.local_gateway}
            onChange={(event) => setPhase1Form((value) => ({ ...value, local_gateway: event.target.value }))}
            placeholder="192.0.2.1"
            fullWidth
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Auth Method"
            value={phase1Form.authentication_method}
            onChange={(event) => setPhase1Form((value) => ({ ...value, authentication_method: event.target.value }))}
            fullWidth
          >
            {AUTH_METHODS.map((method) => (
              <MenuItem key={method.value} value={method.value}>
                {method.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Encryption"
            value={phase1Form.encryption}
            onChange={(event) => setPhase1Form((value) => ({ ...value, encryption: event.target.value }))}
            fullWidth
          >
            {ENCRYPTION_ALGOS.map((algo) => (
              <MenuItem key={algo.value} value={algo.value}>
                {algo.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Hash Algorithm"
            value={phase1Form.hash}
            onChange={(event) => setPhase1Form((value) => ({ ...value, hash: event.target.value }))}
            fullWidth
          >
            {HASH_ALGOS.map((algo) => (
              <MenuItem key={algo.value} value={algo.value}>
                {algo.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="DH Group"
            value={phase1Form.dh_group}
            onChange={(event) => setPhase1Form((value) => ({ ...value, dh_group: event.target.value }))}
            fullWidth
          >
            {DH_GROUPS.map((group) => (
              <MenuItem key={group.value} value={group.value}>
                {group.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Lifetime (seconds)"
            value={phase1Form.lifetime}
            onChange={(event) => setPhase1Form((value) => ({ ...value, lifetime: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
            helperText="28800 = 8 hours"
            fullWidth
          />
          <TextField
            select
            label="NAT Traversal"
            value={phase1Form.nat_traversal}
            onChange={(event) => setPhase1Form((value) => ({ ...value, nat_traversal: event.target.value }))}
            fullWidth
          >
            {NAT_TRAVERSAL_OPTIONS.map((opt) => (
              <MenuItem key={opt.value} value={opt.value}>
                {opt.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="DPD Delay (seconds)"
            value={phase1Form.dpd_delay}
            onChange={(event) => setPhase1Form((value) => ({ ...value, dpd_delay: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
            fullWidth
          />
          <TextField
            label="DPD Max Fail"
            value={phase1Form.dpd_maxfail}
            onChange={(event) => setPhase1Form((value) => ({ ...value, dpd_maxfail: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
            fullWidth
          />
        </Stack>
        <TextField
          label="Pre-shared Key"
          value={phase1Form.pre_shared_key}
          onChange={(event) => setPhase1Form((value) => ({ ...value, pre_shared_key: event.target.value }))}
          type="password"
          helperText="Required for pre-shared key authentication"
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="My Identifier (optional)"
            value={phase1Form.my_identifier}
            onChange={(event) => setPhase1Form((value) => ({ ...value, my_identifier: event.target.value }))}
            placeholder="FQDN or IP"
            fullWidth
          />
          <TextField
            label="Peer Identifier (optional)"
            value={phase1Form.peer_identifier}
            onChange={(event) => setPhase1Form((value) => ({ ...value, peer_identifier: event.target.value }))}
            placeholder="FQDN or IP"
            fullWidth
          />
        </Stack>
        <TextField
          select
          label="State"
          value={phase1Form.enabled ? "enabled" : "disabled"}
          onChange={(event) =>
            setPhase1Form((value) => ({ ...value, enabled: event.target.value === "enabled" }))
          }
          fullWidth
        >
          <MenuItem value="enabled">Enabled</MenuItem>
          <MenuItem value="disabled">Disabled</MenuItem>
        </TextField>
      </FormDialog>

      <FormDialog
        open={phase2DialogOpen}
        title={editingPhase2 ? `Edit ${editingPhase2.name}` : "New IPsec Phase 2"}
        description={
          <Typography variant="body2" color="text.secondary">
            Phase 2 defines the IPsec tunnel parameters for specific network pairs.
          </Typography>
        }
        loading={savePhase2.isPending}
        error={phase2Error}
        submitLabel={editingPhase2 ? "Save changes" : "Create Phase 2"}
        submitDisabled={
          !phase2Form.device_id ||
          !phase2Form.phase1_id ||
          !phase2Form.name.trim() ||
          !phase2Form.local_net.trim() ||
          !phase2Form.remote_net.trim()
        }
        onSubmit={() => savePhase2.mutate()}
        onClose={() => {
          setPhase2DialogOpen(false);
          setEditingPhase2(null);
        }}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Device"
            value={phase2Form.device_id}
            onChange={(event) => setPhase2Form((value) => ({ ...value, device_id: event.target.value }))}
            disabled={Boolean(editingPhase2)}
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
            label="Phase 1 Configuration"
            value={phase2Form.phase1_id}
            onChange={(event) => setPhase2Form((value) => ({ ...value, phase1_id: event.target.value }))}
            disabled={Boolean(editingPhase2)}
            required
            fullWidth
          >
            {phase1Options.map((p1) => (
              <MenuItem key={p1.id} value={p1.id}>
                {p1.name} · {p1.remote_gateway} · {deviceName(p1.device_id)}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Name"
            value={phase2Form.name}
            onChange={(event) => setPhase2Form((value) => ({ ...value, name: event.target.value }))}
            disabled={Boolean(editingPhase2)}
            required
            autoFocus
            fullWidth
          />
          <TextField
            select
            label="Mode"
            value={phase2Form.mode}
            onChange={(event) => setPhase2Form((value) => ({ ...value, mode: event.target.value }))}
            fullWidth
          >
            {MODE_OPTIONS.map((opt) => (
              <MenuItem key={opt.value} value={opt.value}>
                {opt.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Protocol"
            value={phase2Form.protocol}
            onChange={(event) => setPhase2Form((value) => ({ ...value, protocol: event.target.value }))}
            fullWidth
          >
            {PROTOCOL_OPTIONS.map((opt) => (
              <MenuItem key={opt.value} value={opt.value}>
                {opt.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Encryption"
            value={phase2Form.encryption}
            onChange={(event) => setPhase2Form((value) => ({ ...value, encryption: event.target.value }))}
            fullWidth
          >
            {ENCRYPTION_ALGOS.map((algo) => (
              <MenuItem key={algo.value} value={algo.value}>
                {algo.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Local Network"
            value={phase2Form.local_net}
            onChange={(event) => setPhase2Form((value) => ({ ...value, local_net: event.target.value }))}
            placeholder="192.168.1.0/24"
            required
            fullWidth
          />
          <TextField
            label="Remote Network"
            value={phase2Form.remote_net}
            onChange={(event) => setPhase2Form((value) => ({ ...value, remote_net: event.target.value }))}
            placeholder="10.0.0.0/24"
            required
            fullWidth
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="PFS Group"
            value={phase2Form.pfs_group}
            onChange={(event) => setPhase2Form((value) => ({ ...value, pfs_group: event.target.value }))}
            fullWidth
          >
            {DH_GROUPS.map((group) => (
              <MenuItem key={group.value} value={group.value}>
                {group.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Lifetime (seconds)"
            value={phase2Form.lifetime}
            onChange={(event) => setPhase2Form((value) => ({ ...value, lifetime: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
            helperText="3600 = 1 hour"
            fullWidth
          />
        </Stack>
        <TextField
          select
          label="State"
          value={phase2Form.enabled ? "enabled" : "disabled"}
          onChange={(event) =>
            setPhase2Form((value) => ({ ...value, enabled: event.target.value === "enabled" }))
          }
          fullWidth
        >
          <MenuItem value="enabled">Enabled</MenuItem>
          <MenuItem value="disabled">Disabled</MenuItem>
        </TextField>
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deletePhase1)}
        title="Delete IPsec Phase 1"
        description={
          deletePhase1
            ? `Delete ${deletePhase1.name}? Associated Phase 2 configurations will also be removed.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deletePhase1Mutation.isPending}
        onConfirm={() => deletePhase1 && deletePhase1Mutation.mutate(deletePhase1.id)}
        onClose={() => setDeletePhase1(null)}
      />

      <ConfirmDialog
        open={Boolean(deletePhase2)}
        title="Delete IPsec Phase 2"
        description={
          deletePhase2
            ? `Delete ${deletePhase2.name}? The IPsec tunnel for this network pair will be removed.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deletePhase2Mutation.isPending}
        onConfirm={() => deletePhase2 && deletePhase2Mutation.mutate(deletePhase2.id)}
        onClose={() => setDeletePhase2(null)}
      />

      <FormDialog
        open={applyOpen}
        title="Apply IPsec configuration"
        description={
          applyDevice
            ? `Create, update and prune OFME-managed IPsec tunnels on ${applyDevice.name}.`
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

export default IpsecPage;
