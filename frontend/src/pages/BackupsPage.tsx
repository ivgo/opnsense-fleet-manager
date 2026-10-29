import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  FormControlLabel,
  Grid,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
  alpha,
  useTheme,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CloudDownloadOutlinedIcon from "@mui/icons-material/CloudDownloadOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import HistoryOutlinedIcon from "@mui/icons-material/HistoryOutlined";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import RestoreOutlinedIcon from "@mui/icons-material/RestoreOutlined";
import StorageOutlinedIcon from "@mui/icons-material/StorageOutlined";
import VerifiedOutlinedIcon from "@mui/icons-material/VerifiedOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { backupsApi, devicesApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { Backup, BackupType, BackupVerification } from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import DetailGrid from "@/components/DetailGrid";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { BACKUP_TYPE_LABELS, DEFAULT_PAGE_SIZE } from "@/utils/constants";
import {
  downloadBlob,
  formatBytes,
  formatDateTime,
  formatNumber,
  fromNow,
  prettyJson,
} from "@/utils/format";

const BACKUP_TYPES: BackupType[] = ["manual", "scheduled", "pre_upgrade", "pre_change", "auto"];

export function BackupsPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const theme = useTheme();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [deviceFilter, setDeviceFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [createDevice, setCreateDevice] = useState("");
  const [createType, setCreateType] = useState<BackupType>("manual");
  const [createNotes, setCreateNotes] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);

  const [verifyTarget, setVerifyTarget] = useState<Backup | null>(null);
  const [verification, setVerification] = useState<BackupVerification | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  const [restoreTarget, setRestoreTarget] = useState<Backup | null>(null);
  const [restoreDryRun, setRestoreDryRun] = useState(true);
  const [restoreReboot, setRestoreReboot] = useState(false);
  const [restoreResult, setRestoreResult] = useState<Record<string, unknown> | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<Backup | null>(null);
  const [sweepOpen, setSweepOpen] = useState(false);
  const [retentionOpen, setRetentionOpen] = useState(false);
  const [retentionDays, setRetentionDays] = useState("30");
  const [keepPerDevice, setKeepPerDevice] = useState("30");
  const [retentionResult, setRetentionResult] = useState<Record<string, unknown> | null>(null);
  const [retentionError, setRetentionError] = useState<string | null>(null);

  const listParams = useMemo(
    () => ({
      page,
      size,
      device_id: deviceFilter || undefined,
      type: typeFilter || undefined,
    }),
    [page, size, deviceFilter, typeFilter],
  );

  const backupsQuery = useQuery({
    queryKey: qk.backups.list(listParams),
    queryFn: () => backupsApi.list(listParams),
    refetchInterval: 60_000,
  });

  const devicesQuery = useQuery({
    queryKey: qk.devices.list({ size: 500 }),
    queryFn: () => devicesApi.list({ size: 500 }),
    staleTime: 120_000,
  });

  const usageQuery = useQuery({
    queryKey: qk.backups.usage,
    queryFn: () => backupsApi.storageUsage(),
    staleTime: 60_000,
  });

  useEffect(() => {
    setPage(1);
  }, [deviceFilter, typeFilter]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.backups.all });
    void queryClient.invalidateQueries({ queryKey: qk.jobs.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const deviceName = (id: string) =>
    devicesQuery.data?.items.find((device) => device.id === id)?.name ?? id.slice(0, 8);

  const devices = devicesQuery.data?.items ?? [];
  const backups = backupsQuery.data?.items ?? [];
  const encryptedCount = backups.filter((backup) => backup.is_encrypted).length;
  const totalBytesOnPage = backups.reduce((total, backup) => total + (backup.size_bytes ?? 0), 0);

  const createMutation = useMutation({
    mutationFn: () =>
      backupsApi.create({
        device_id: createDevice,
        type: createType,
        notes: createNotes.trim() || null,
      }),
    onSuccess: (backup) => {
      invalidate();
      setCreateOpen(false);
      setCreateDevice("");
      setCreateNotes("");
      setCreateError(null);
      dispatch(
        showToast({
          message: `Backup created for ${deviceName(backup.device_id)} (${formatBytes(backup.size_bytes)})`,
          severity: "success",
        }),
      );
    },
    onError: (error) => setCreateError(toApiError(error).message),
  });

  const verifyMutation = useMutation({
    mutationFn: (backup: Backup) => backupsApi.verify(backup.id),
    onSuccess: (result) => {
      setVerification(result);
      setVerifyError(null);
    },
    onError: (error) => setVerifyError(toApiError(error).message),
  });

  const downloadMutation = useMutation({
    mutationFn: (backup: Backup) => backupsApi.download(backup.id),
    onSuccess: (blob, backup) => {
      downloadBlob(blob, `ofme-backup-${backup.device_id}-${backup.id.slice(0, 8)}.xml`);
      dispatch(
        showToast({
          message: "Configuration backup downloaded",
          severity: "success",
        }),
      );
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const restoreMutation = useMutation({
    mutationFn: (backup: Backup) =>
      backupsApi.restore(backup.id, { dry_run: restoreDryRun, reboot: restoreReboot }),
    onSuccess: (result) => {
      setRestoreResult(result);
      setRestoreError(null);
      invalidate();
      dispatch(
        showToast({
          message: restoreDryRun ? "Restore dry run completed" : "Restore command dispatched",
          severity: "success",
        }),
      );
    },
    onError: (error) => setRestoreError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (backup: Backup) => backupsApi.remove(backup.id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Backup deleted", severity: "success" }));
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const sweepMutation = useMutation({
    mutationFn: () => backupsApi.sweep("scheduled"),
    onSuccess: (result) => {
      setSweepOpen(false);
      invalidate();
      dispatch(
        showToast({
          message: `Backup sweep queued as job ${String(result.job_id ?? "unknown")}`,
          severity: "success",
        }),
      );
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const retentionMutation = useMutation({
    mutationFn: () =>
      backupsApi.retention({
        retention_days: retentionDays ? Number(retentionDays) : undefined,
        keep_per_device: Number(keepPerDevice) || 30,
      }),
    onSuccess: (result) => {
      setRetentionResult(result);
      setRetentionError(null);
      invalidate();
      dispatch(showToast({ message: "Retention policy applied", severity: "success" }));
    },
    onError: (error) => setRetentionError(toApiError(error).message),
  });

  const openVerify = (backup: Backup) => {
    setVerifyTarget(backup);
    setVerification(null);
    setVerifyError(null);
    verifyMutation.mutate(backup);
  };

  const openRestore = (backup: Backup) => {
    setRestoreTarget(backup);
    setRestoreDryRun(true);
    setRestoreReboot(false);
    setRestoreResult(null);
    setRestoreError(null);
  };

  const columns: Array<DataTableColumn<Backup>> = [
    {
      key: "id",
      label: "Backup",
      render: (row) => (
        <Box>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" fontWeight={600}>
              {deviceName(row.device_id)}
            </Typography>
            {row.is_encrypted && (
              <Chip size="small" variant="outlined" color="success" label="encrypted" />
            )}
          </Stack>
          <Typography variant="caption" color="text.secondary" fontFamily="monospace">
            {row.id.slice(0, 8)} · {row.storage_key}
          </Typography>
        </Box>
      ),
    },
    {
      key: "type",
      label: "Type",
      width: 130,
      render: (row) => (
        <Chip size="small" variant="outlined" label={BACKUP_TYPE_LABELS[row.type] ?? row.type} />
      ),
    },
    {
      key: "size",
      label: "Size",
      width: 100,
      align: "right",
      render: (row) => formatBytes(row.size_bytes),
    },
    {
      key: "firmware",
      label: "Firmware",
      width: 120,
      hideBelow: "md",
      render: (row) => row.firmware_version ?? "—",
    },
    {
      key: "checksum",
      label: "Checksum",
      width: 190,
      hideBelow: "lg",
      monospace: true,
      render: (row) => (
        <Tooltip title={row.checksum_sha256}>
          <span>{row.checksum_sha256.slice(0, 18)}…</span>
        </Tooltip>
      ),
    },
    {
      key: "created",
      label: "Created",
      width: 160,
      render: (row) => (
        <Tooltip title={formatDateTime(row.created_at)}>
          <span>{fromNow(row.created_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 200,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <Tooltip title="Verify integrity">
            <IconButton size="small" onClick={() => openVerify(row)}>
              <VerifiedOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <PermissionGate permission="backup:read">
            <Tooltip title="Create download link">
              <IconButton
                size="small"
                onClick={() => downloadMutation.mutate(row)}
                disabled={downloadMutation.isPending}
              >
                <CloudDownloadOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="backup:restore">
            <Tooltip title="Restore">
              <IconButton size="small" onClick={() => openRestore(row)}>
                <RestoreOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="backup:delete">
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
        title="Backups"
        subtitle="Encrypted, signed configuration backups with verification, restore and per-device retention."
        actions={
          <>
            <PermissionGate permission="backup:create">
              <Button
                variant="outlined"
                startIcon={<HistoryOutlinedIcon />}
                onClick={() => setRetentionOpen(true)}
              >
                Retention
              </Button>
            </PermissionGate>
            <PermissionGate permission="backup:create">
              <Button
                variant="outlined"
                startIcon={<PlayArrowIcon />}
                onClick={() => setSweepOpen(true)}
              >
                Back up fleet
              </Button>
            </PermissionGate>
            <PermissionGate permission="backup:create">
              <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
                New backup
              </Button>
            </PermissionGate>
          </>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${formatNumber(backupsQuery.data?.meta.total ?? 0)} backups`} />
            <Chip size="small" variant="outlined" label={`${encryptedCount} encrypted on this page`} />
            <Chip
              size="small"
              variant="outlined"
              label={`${formatBytes(totalBytesOnPage)} on this page`}
            />
          </Stack>
        }
      />

      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: "100%" }}>
            <CardContent>
              <Stack direction="row" spacing={1.5} alignItems="center">
                <Box
                  sx={{
                    p: 1,
                    borderRadius: 1.5,
                    color: "primary.main",
                    bgcolor: alpha(theme.palette.primary.main, 0.12),
                    display: "flex",
                  }}
                >
                  <StorageOutlinedIcon />
                </Box>
                <Box>
                  <Typography variant="overline" color="text.secondary">
                    Object storage used
                  </Typography>
                  <Typography variant="h3" sx={{ lineHeight: 1.2 }}>
                    {usageQuery.isLoading
                      ? "…"
                      : formatBytes(usageQuery.data?.storage_bytes ?? 0)}
                  </Typography>
                </Box>
              </Stack>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                Compressed XML artifacts in S3/MinIO. Each artifact is AES-encrypted at rest and signed with
                HMAC-SHA256 before upload.
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                Integrity model
              </Typography>
              <Typography variant="h3" sx={{ lineHeight: 1.2 }}>
                SHA-256
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                Restore is refused unless the stored checksum and signature both match. Verification never
                mutates the artifact.
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: "100%" }}>
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                Retention
              </Typography>
              <Typography variant="h3" sx={{ lineHeight: 1.2 }}>
                30 / device
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                Default policy keeps the newest 30 backups per device plus anything inside the retention
                window. Adjust it from the Retention dialog.
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <DataTable
        columns={columns}
        rows={backups}
        getRowId={(row) => row.id}
        loading={backupsQuery.isLoading}
        error={backupsQuery.error ? toApiError(backupsQuery.error).message : null}
        onRetry={() => backupsQuery.refetch()}
        page={page}
        size={size}
        total={backupsQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        onRowClick={openVerify}
        emptyTitle="No backups stored"
        emptyDescription="Create a backup for a single device or run a fleet-wide sweep. Scheduled backups keep artifacts fresh automatically."
        emptyAction={
          <PermissionGate permission="backup:create">
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
              New backup
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack
            direction={{ xs: "column", lg: "row" }}
            spacing={1}
            alignItems={{ xs: "stretch", lg: "center" }}
            justifyContent="space-between"
          >
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap>
              <TextField
                select
                label="Device"
                value={deviceFilter}
                onChange={(event) => setDeviceFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 260 } }}
              >
                <MenuItem value="">All devices</MenuItem>
                {devices.map((device) => (
                  <MenuItem key={device.id} value={device.id}>
                    {device.name}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Type"
                value={typeFilter}
                onChange={(event) => setTypeFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 180 } }}
              >
                <MenuItem value="">All types</MenuItem>
                {BACKUP_TYPES.map((type) => (
                  <MenuItem key={type} value={type}>
                    {BACKUP_TYPE_LABELS[type] ?? type}
                  </MenuItem>
                ))}
              </TextField>
              {(deviceFilter || typeFilter) && (
                <Button
                  color="inherit"
                  onClick={() => {
                    setDeviceFilter("");
                    setTypeFilter("");
                  }}
                >
                  Clear
                </Button>
              )}
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
              {formatNumber(backupsQuery.data?.meta.total ?? 0)} artifacts
            </Typography>
          </Stack>
        }
      />

      <FormDialog
        open={createOpen}
        title="Create configuration backup"
        description={
          <Typography variant="body2" color="text.secondary">
            The control plane asks the agent for a configuration export, compresses it, encrypts the artifact and
            stores it with a checksum and signature.
          </Typography>
        }
        submitLabel="Create backup"
        loading={createMutation.isPending}
        error={createError}
        submitDisabled={!createDevice}
        onSubmit={() => createMutation.mutate()}
        onClose={() => setCreateOpen(false)}
        maxWidth="sm"
      >
        <TextField
          select
          label="Device"
          value={createDevice}
          onChange={(event) => setCreateDevice(event.target.value)}
          required
        >
          {devices.map((device) => (
            <MenuItem key={device.id} value={device.id}>
              {device.name} · {device.connection_status}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Backup type"
          value={createType}
          onChange={(event) => setCreateType(event.target.value as BackupType)}
        >
          {BACKUP_TYPES.map((type) => (
            <MenuItem key={type} value={type}>
              {BACKUP_TYPE_LABELS[type] ?? type}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Notes"
          value={createNotes}
          onChange={(event) => setCreateNotes(event.target.value)}
          multiline
          minRows={2}
          helperText="Optional context stored with the backup, for example the change ticket"
        />
      </FormDialog>

      <FormDialog
        open={Boolean(verifyTarget)}
        title={verifyTarget ? `Verify backup ${verifyTarget.id.slice(0, 8)}` : "Verify backup"}
        description={
          verifyTarget ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip size="small" variant="outlined" label={deviceName(verifyTarget.device_id)} />
              <Chip
                size="small"
                variant="outlined"
                label={BACKUP_TYPE_LABELS[verifyTarget.type] ?? verifyTarget.type}
              />
              <Chip size="small" variant="outlined" label={formatDateTime(verifyTarget.created_at)} />
            </Stack>
          ) : undefined
        }
        submitLabel="Close"
        onSubmit={() => setVerifyTarget(null)}
        onClose={() => setVerifyTarget(null)}
        maxWidth="md"
      >
        {verifyMutation.isPending && (
          <Alert severity="info">Downloading the artifact and recomputing its checksum…</Alert>
        )}
        {verifyError && <Alert severity="error">{verifyError}</Alert>}
        {verification && (
          <Stack spacing={2}>
            <Alert severity={verification.valid ? "success" : "error"}>
              {verification.valid
                ? "Checksum and HMAC signature are valid. The artifact is safe to restore."
                : "Verification failed. Do not restore this artifact; create a fresh backup instead."}
            </Alert>
            <DetailGrid
              items={[
                { label: "Overall", value: <StatusChip status={verification.valid ? "passed" : "failed"} label={verification.valid ? "passed" : "failed"} /> },
                { label: "Checksum", value: <StatusChip status={verification.checksum_ok ? "passed" : "failed"} label={verification.checksum_ok ? "match" : "mismatch"} /> },
                { label: "Signature", value: <StatusChip status={verification.signature_ok ? "passed" : "failed"} label={verification.signature_ok ? "valid" : "invalid"} /> },
                { label: "Size", value: formatBytes(verification.size_bytes) },
              ]}
            />
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Checksums
              </Typography>
              <CodeBlock
                code={prettyJson({
                  stored: verification.stored_checksum,
                  computed: verification.computed_checksum,
                })}
                language="json"
                maxHeight={160}
              />
            </Box>
          </Stack>
        )}
        {verifyTarget?.notes && (
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
              Notes
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {verifyTarget.notes}
            </Typography>
          </Box>
        )}
      </FormDialog>

      <FormDialog
        open={Boolean(restoreTarget)}
        title={restoreTarget ? `Restore ${deviceName(restoreTarget.device_id)}` : "Restore backup"}
        description={
          <Typography variant="body2" color="text.secondary">
            Restoring pushes the archived configuration to the selected appliance after re-verifying the
            artifact. A dry run reports the diff without changing the device.
          </Typography>
        }
        submitLabel={restoreDryRun ? "Run dry run" : "Restore now"}
        loading={restoreMutation.isPending}
        error={restoreError}
        submitDisabled={!restoreTarget}
        onSubmit={() => restoreTarget && restoreMutation.mutate(restoreTarget)}
        onClose={() => {
          setRestoreTarget(null);
          setRestoreResult(null);
        }}
        maxWidth="md"
      >
        <FormControlLabel
          control={
            <Checkbox
              checked={restoreDryRun}
              onChange={(event) => setRestoreDryRun(event.target.checked)}
            />
          }
          label="Dry run (validate and diff, do not apply)"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={restoreReboot}
              onChange={(event) => setRestoreReboot(event.target.checked)}
              disabled={restoreDryRun}
            />
          }
          label="Reboot the appliance after applying the configuration"
        />
        {restoreTarget && (
          <Box sx={{ p: 1.5, border: 1, borderColor: "divider", borderRadius: 1.5 }}>
            <DetailGrid
              dense
              items={[
                { label: "Device", value: deviceName(restoreTarget.device_id) },
                { label: "Created", value: formatDateTime(restoreTarget.created_at) },
                { label: "Firmware", value: restoreTarget.firmware_version ?? "—" },
                { label: "Size", value: formatBytes(restoreTarget.size_bytes) },
              ]}
            />
          </Box>
        )}
        {!restoreDryRun && (
          <Alert severity="warning">
            A non-dry-run restore overwrites the running configuration. The operation is audited and creates a
            pre-restore backup when the device is reachable.
          </Alert>
        )}
        {restoreResult && (
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Restore result
            </Typography>
            <CodeBlock code={prettyJson(restoreResult)} language="json" maxHeight={240} />
          </Box>
        )}
      </FormDialog>

      <FormDialog
        open={retentionOpen}
        title="Apply retention policy"
        description={
          <Typography variant="body2" color="text.secondary">
            Artifacts older than the retention window and beyond the per-device keep count are deleted from
            object storage. Deletions are audited and cannot be undone.
          </Typography>
        }
        submitLabel="Apply policy"
        loading={retentionMutation.isPending}
        error={retentionError}
        onSubmit={() => retentionMutation.mutate()}
        onClose={() => {
          setRetentionOpen(false);
          setRetentionResult(null);
        }}
        maxWidth="sm"
      >
        <TextField
          label="Retention days"
          type="number"
          value={retentionDays}
          onChange={(event) => setRetentionDays(event.target.value)}
          inputProps={{ min: 1, max: 3650 }}
          helperText="Leave empty to keep only the per-device count"
        />
        <TextField
          label="Keep per device"
          type="number"
          value={keepPerDevice}
          onChange={(event) => setKeepPerDevice(event.target.value)}
          inputProps={{ min: 1, max: 500 }}
        />
        {retentionResult && (
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Result
            </Typography>
            <CodeBlock code={prettyJson(retentionResult)} language="json" maxHeight={200} />
          </Box>
        )}
      </FormDialog>

      <ConfirmDialog
        open={sweepOpen}
        title="Back up every device"
        description="Queues one scheduled backup per manageable device in the tenant. The job runs in the background and appears under Jobs. Devices that are offline are skipped."
        confirmLabel="Queue sweep"
        loading={sweepMutation.isPending}
        onConfirm={() => sweepMutation.mutate()}
        onClose={() => setSweepOpen(false)}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete backup"
        description={
          deleteTarget
            ? `Delete the ${BACKUP_TYPE_LABELS[deleteTarget.type] ?? deleteTarget.type} backup for ${deviceName(deleteTarget.device_id)}? The artifact is removed from object storage and cannot be recovered.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
      />
    </>
  );
}

export default BackupsPage;
