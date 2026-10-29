import { useMemo, useState } from "react";
import {
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import BlockOutlinedIcon from "@mui/icons-material/BlockOutlined";
import RocketLaunchOutlinedIcon from "@mui/icons-material/RocketLaunchOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { sitesApi, ztpApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { Enrollment, EnrollmentTokenResponse } from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { EMPTY, formatDateTime, formatNumber, fromNow, titleCase } from "@/utils/format";

const DISCOVERY_METHODS = ["token", "dhcp", "dns", "https", "certificate"] as const;

const STATUS_COLORS: Record<
  string,
  "default" | "info" | "warning" | "success" | "error" | "primary"
> = {
  pending: "default",
  token_issued: "info",
  discovered: "info",
  enrolled: "primary",
  provisioned: "success",
  completed: "success",
  failed: "error",
  revoked: "error",
};

interface EnrollmentFormState {
  site_id: string;
  hostname: string;
  device_serial: string;
  device_mac: string;
  ttl_minutes: string;
  discovery_method: string;
}

const EMPTY_FORM: EnrollmentFormState = {
  site_id: "",
  hostname: "",
  device_serial: "",
  device_mac: "",
  ttl_minutes: "60",
  discovery_method: "token",
};

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function ZtpPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [statusFilter, setStatusFilter] = useState("");

  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<EnrollmentFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [issued, setIssued] = useState<EnrollmentTokenResponse | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<Enrollment | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Enrollment | null>(null);

  const listParams = useMemo(
    () => ({
      page,
      size,
      status: statusFilter || undefined,
    }),
    [page, size, statusFilter],
  );

  const enrollmentsQuery = useQuery({
    queryKey: qk.ztp.enrollments(listParams),
    queryFn: () => ztpApi.enrollments(listParams),
  });

  const sitesQuery = useQuery({
    queryKey: qk.sites.list({ size: 200, sort: "name", order: "asc" }),
    queryFn: () => sitesApi.list({ size: 200, sort: "name", order: "asc" }),
    staleTime: 60_000,
  });

  const sites = useMemo(() => sitesQuery.data?.items ?? [], [sitesQuery.data]);
  const siteName = useMemo(() => {
    const map = new Map(sites.map((site) => [site.id, site.name]));
    return (id: string | null) => (id ? map.get(id) ?? id : EMPTY);
  }, [sites]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.ztp.all });
    void queryClient.invalidateQueries({ queryKey: qk.devices.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const createMutation = useMutation({
    mutationFn: () =>
      ztpApi.createEnrollment({
        site_id: form.site_id || null,
        hostname: optionalText(form.hostname),
        device_serial: optionalText(form.device_serial),
        device_mac: optionalText(form.device_mac),
        ttl_minutes: Number(form.ttl_minutes) || 60,
        discovery_method: form.discovery_method,
      }),
    onSuccess: (response) => {
      invalidate();
      setDialogOpen(false);
      setForm(EMPTY_FORM);
      setFormError(null);
      setIssued(response);
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => ztpApi.revokeEnrollment(id),
    onSuccess: () => {
      invalidate();
      setRevokeTarget(null);
      dispatch(showToast({ message: "Enrollment revoked", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => ztpApi.removeEnrollment(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Enrollment deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreate = () => {
    setForm({ ...EMPTY_FORM, site_id: sites[0]?.id || "" });
    setFormError(null);
    setDialogOpen(true);
  };

  const columns: Array<DataTableColumn<Enrollment>> = [
    {
      key: "hostname",
      label: "Device",
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <RocketLaunchOutlinedIcon fontSize="small" color="action" />
          <Stack>
            <Typography variant="body2" fontWeight={600} fontFamily="monospace">
              {row.hostname || row.device_serial || row.token_hint}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {[row.device_serial, row.device_mac].filter(Boolean).join(" · ") || "No hardware hint"}
            </Typography>
          </Stack>
        </Stack>
      ),
    },
    {
      key: "status",
      label: "Status",
      width: 140,
      render: (row) => (
        <Chip
          size="small"
          color={STATUS_COLORS[row.status] ?? "default"}
          variant={row.status === "pending" ? "outlined" : "filled"}
          label={titleCase(row.status)}
        />
      ),
    },
    {
      key: "site_id",
      label: "Site",
      width: 160,
      hideBelow: "sm",
      render: (row) => siteName(row.site_id),
    },
    {
      key: "discovery_method",
      label: "Discovery",
      width: 130,
      hideBelow: "md",
      render: (row) => <Chip size="small" variant="outlined" label={titleCase(row.discovery_method)} />,
    },
    {
      key: "token_hint",
      label: "Token hint",
      width: 150,
      hideBelow: "lg",
      monospace: true,
      render: (row) => row.token_hint,
    },
    {
      key: "expires_at",
      label: "Expires",
      width: 150,
      hideBelow: "md",
      render: (row) => (
        <Tooltip title={formatDateTime(row.expires_at)}>
          <span>{fromNow(row.expires_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: "device_id",
      label: "Device ID",
      hideBelow: "lg",
      monospace: true,
      render: (row) => (row.device_id ? row.device_id.slice(0, 8) : EMPTY),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 100,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="ztp:write">
            <Tooltip title="Revoke token">
              <span>
                <IconButton
                  size="small"
                  color="warning"
                  disabled={row.status === "revoked" || row.status === "completed"}
                  onClick={() => setRevokeTarget(row)}
                >
                  <BlockOutlinedIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="ztp:write">
            <Tooltip title="Delete record">
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
        title="Zero-touch provisioning"
        subtitle="Mint one-time enrollment tokens, bind hardware hints and follow each device through bootstrap."
        actions={
          <PermissionGate permission="ztp:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New enrollment
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip
              size="small"
              label={`${formatNumber(enrollmentsQuery.data?.meta.total ?? 0)} enrollments`}
            />
            <Chip
              size="small"
              variant="outlined"
              label={`${formatNumber(sitesQuery.isPending ? undefined : sites.length)} sites`}
            />
          </Stack>
        }
      />

      <DataTable
        columns={columns}
        rows={enrollmentsQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={enrollmentsQuery.isLoading}
        error={enrollmentsQuery.error ? toApiError(enrollmentsQuery.error).message : null}
        onRetry={() => enrollmentsQuery.refetch()}
        page={page}
        size={size}
        total={enrollmentsQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        emptyTitle="No enrollment tokens"
        emptyDescription="Mint a token, boot the appliance with it, and watch the enrollment progress here."
        emptyAction={
          <PermissionGate permission="ztp:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New enrollment
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
            <TextField
              select
              label="Status"
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setPage(1);
              }}
              sx={{ width: { xs: "100%", sm: 180 } }}
            >
              <MenuItem value="">All statuses</MenuItem>
              {Object.keys(STATUS_COLORS).map((status) => (
                <MenuItem key={status} value={status}>
                  {titleCase(status)}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
        }
      />

      <FormDialog
        open={dialogOpen}
        title="New enrollment token"
        loading={createMutation.isPending}
        error={formError}
        submitLabel="Mint token"
        submitDisabled={!form.ttl_minutes.trim()}
        onSubmit={() => createMutation.mutate()}
        onClose={() => setDialogOpen(false)}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Site"
            value={form.site_id}
            onChange={(event) => setForm((value) => ({ ...value, site_id: event.target.value }))}
            helperText="Optional — the device inherits the site on enrollment"
            fullWidth
          >
            <MenuItem value="">Unassigned</MenuItem>
            {sites.map((site) => (
              <MenuItem key={site.id} value={site.id}>
                {site.name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Discovery method"
            value={form.discovery_method}
            onChange={(event) =>
              setForm((value) => ({ ...value, discovery_method: event.target.value }))
            }
            fullWidth
          >
            {DISCOVERY_METHODS.map((method) => (
              <MenuItem key={method} value={method}>
                {titleCase(method)}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Hostname"
            value={form.hostname}
            onChange={(event) => setForm((value) => ({ ...value, hostname: event.target.value }))}
            placeholder="branch-fw-01"
            fullWidth
          />
          <TextField
            label="Serial number"
            value={form.device_serial}
            onChange={(event) =>
              setForm((value) => ({ ...value, device_serial: event.target.value }))
            }
            placeholder="optional"
            fullWidth
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="MAC address"
            value={form.device_mac}
            onChange={(event) => setForm((value) => ({ ...value, device_mac: event.target.value }))}
            placeholder="aa:bb:cc:dd:ee:ff"
            fullWidth
          />
          <TextField
            label="Token lifetime (minutes)"
            value={form.ttl_minutes}
            onChange={(event) => setForm((value) => ({ ...value, ttl_minutes: event.target.value }))}
            inputProps={{ inputMode: "numeric" }}
            helperText="5 – 10,080 minutes"
            required
            fullWidth
          />
        </Stack>
      </FormDialog>

      <Dialog open={Boolean(issued)} onClose={() => setIssued(null)} maxWidth="md" fullWidth>
        <DialogTitle>Enrollment token issued</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            <Typography variant="body2" color="text.secondary">
              This token is shown exactly once. Deliver it to the appliance through your bootstrap
              channel; it expires {issued ? formatDateTime(issued.expires_at) : EMPTY}.
            </Typography>
            <CodeBlock title="bootstrap url" code={issued?.bootstrap_url ?? ""} wrap />
            <CodeBlock title="token" code={issued?.token ?? ""} wrap />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button onClick={() => setIssued(null)} variant="contained">
            Done
          </Button>
        </DialogActions>
      </Dialog>

      <ConfirmDialog
        open={Boolean(revokeTarget)}
        title="Revoke enrollment"
        description={
          revokeTarget
            ? `Revoke the token for ${revokeTarget.hostname || revokeTarget.token_hint}? The device will no longer be able to enroll.`
            : undefined
        }
        confirmLabel="Revoke"
        confirmColor="warning"
        loading={revokeMutation.isPending}
        onConfirm={() => revokeTarget && revokeMutation.mutate(revokeTarget.id)}
        onClose={() => setRevokeTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete enrollment"
        description={
          deleteTarget
            ? `Delete the enrollment record for ${deleteTarget.hostname || deleteTarget.token_hint}?`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onClose={() => setDeleteTarget(null)}
      />
    </>
  );
}

export default ZtpPage;
