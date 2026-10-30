import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Button,
  Chip,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import BlockIcon from "@mui/icons-material/Block";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { inventoryApi } from "@/api/endpoints";
import { qk } from "@/api/queryKeys";
import type { ClientDevice } from "@/api/types";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useDebounce } from "@/hooks/useDebounce";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { formatDateTime, fromNow } from "@/utils/format";

const SOURCE_LABELS: Record<string, string> = {
  arp: "ARP",
  dhcp: "DHCP",
  lldp: "LLDP",
};

const STATUS_LABELS: Record<string, string> = {
  active: "Active",
  blocked: "Blocked",
  paused: "Paused",
};

export function InventoryPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();

  const [search, setSearch] = useState(params.get("search") || "");
  const [statusFilter, setStatusFilter] = useState(params.get("status") || "");
  const [sourceFilter, setSourceFilter] = useState(params.get("source") || "");
  const debouncedSearch = useDebounce(search.trim(), 350);

  useEffect(() => {
    const newParams = new URLSearchParams();
    if (search) newParams.set("search", search);
    if (statusFilter) newParams.set("status", statusFilter);
    if (sourceFilter) newParams.set("source", sourceFilter);
    setParams(newParams);
  }, [search, statusFilter, sourceFilter, setParams]);

  const [pauseTarget, setPauseTarget] = useState<{ mac: string; minutes: number } | null>(null);

  const queryParams = { status: statusFilter || undefined, source: sourceFilter || undefined, search: debouncedSearch || undefined };

  const { data: clients = [], isLoading } = useQuery({
    queryKey: qk.inventory.list(queryParams),
    queryFn: () => inventoryApi.list(queryParams),
    refetchInterval: 30_000,
  });

  const blockMutation = useMutation({
    mutationFn: (mac: string) => inventoryApi.block(mac),
    onSuccess: (_, mac) => {
      void queryClient.invalidateQueries({ queryKey: qk.inventory.list(queryParams) });
      dispatch(showToast({ message: `Client ${mac} blocked`, severity: "success" }));
    },
    onError: (error: Error) => dispatch(showToast({ message: error.message, severity: "error" })),
  });

  const pauseMutation = useMutation({
    mutationFn: ({ mac, minutes }: { mac: string; minutes: number }) => inventoryApi.pause(mac, minutes),
    onSuccess: (_, { mac }) => {
      void queryClient.invalidateQueries({ queryKey: qk.inventory.list(queryParams) });
      dispatch(showToast({ message: `Client ${mac} paused for ${pauseTarget?.minutes} minutes`, severity: "success" }));
      setPauseTarget(null);
    },
    onError: (error: Error) => dispatch(showToast({ message: error.message, severity: "error" })),
  });

  const unblockMutation = useMutation({
    mutationFn: (mac: string) => inventoryApi.unblock(mac),
    onSuccess: (_, mac) => {
      void queryClient.invalidateQueries({ queryKey: qk.inventory.list(queryParams) });
      dispatch(showToast({ message: `Client ${mac} unblocked`, severity: "success" }));
    },
    onError: (error: Error) => dispatch(showToast({ message: error.message, severity: "error" })),
  });

  const columns: Array<DataTableColumn<ClientDevice>> = [
    {
      key: "mac_address",
      label: "MAC Address",
      monospace: true,
      render: (row) => (
        <Typography variant="body2" fontFamily="monospace">
          {row.mac_address}
        </Typography>
      ),
    },
    {
      key: "ip_address",
      label: "IP Address",
      render: (row) => (row.ip_address ? row.ip_address : "—"),
    },
    {
      key: "hostname",
      label: "Hostname",
      render: (row) => (row.hostname ? row.hostname : "—"),
    },
    {
      key: "source",
      label: "Source",
      width: 100,
      render: (row) => (
        <Chip size="small" label={SOURCE_LABELS[row.source]} variant="outlined" />
      ),
    },
    {
      key: "status",
      label: "Status",
      width: 100,
      render: (row) => <StatusChip status={row.status} />,
    },
    {
      key: "vendor",
      label: "Vendor",
      hideBelow: "md",
      render: (row) => (row.vendor ? row.vendor : "—"),
    },
    {
      key: "last_seen",
      label: "Last seen",
      width: 140,
      hideBelow: "lg",
      render: (row) => (
        <Tooltip title={row.last_seen ? formatDateTime(row.last_seen) : "Never"}>
          <Typography variant="body2">{fromNow(row.last_seen)}</Typography>
        </Tooltip>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 200,
      render: (row) => (
        <Stack direction="row" spacing={0.5} justifyContent="flex-end">
          {row.status === "active" && (
            <>
              <PermissionGate permission="inventory:write">
                <Tooltip title="Block">
                  <IconButton
                    size="small"
                    color="error"
                    onClick={() => blockMutation.mutate(row.mac_address)}
                    disabled={blockMutation.isPending}
                  >
                    <BlockIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </PermissionGate>
              <PermissionGate permission="inventory:write">
                <Tooltip title="Pause (5 min)">
                  <IconButton
                    size="small"
                    color="warning"
                    onClick={() => setPauseTarget({ mac: row.mac_address, minutes: 5 })}
                    disabled={pauseMutation.isPending}
                  >
                    <PlayArrowIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </PermissionGate>
            </>
          )}
          {row.status !== "active" && (
            <PermissionGate permission="inventory:write">
              <Tooltip title="Unblock">
                <IconButton
                  size="small"
                  color="success"
                  onClick={() => unblockMutation.mutate(row.mac_address)}
                  disabled={unblockMutation.isPending}
                >
                  <CheckCircleIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </PermissionGate>
          )}
        </Stack>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Client Inventory"
        subtitle={`Discovering clients via ARP, DHCP, and LLDP`}
        actions={
          <PermissionGate permission="inventory:write">
            <Button variant="contained" startIcon={<BlockIcon />} disabled>
              Block Selected
            </Button>
          </PermissionGate>
        }
      />

      <Stack direction="row" spacing={2} sx={{ mb: 3 }}>
        <TextField
          size="small"
          placeholder="Search MAC, IP, hostname..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          sx={{ minWidth: 280 }}
        />
        <TextField
          select
          size="small"
          placeholder="Status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          sx={{ minWidth: 140 }}
        >
          <MenuItem value="">All Status</MenuItem>
          {Object.entries(STATUS_LABELS).map(([value, label]) => (
            <MenuItem key={value} value={value}>
              {label}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          size="small"
          placeholder="Source"
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          sx={{ minWidth: 120 }}
        >
          <MenuItem value="">All Sources</MenuItem>
          {Object.entries(SOURCE_LABELS).map(([value, label]) => (
            <MenuItem key={value} value={value}>
              {label}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      <DataTable
        columns={columns}
        rows={clients}
        getRowId={(row) => row.mac_address}
        loading={isLoading}
        emptyTitle="No clients discovered"
        emptyDescription="Clients will appear here once discovered via ARP, DHCP, or LLDP."
      />
    </>
  );
}
