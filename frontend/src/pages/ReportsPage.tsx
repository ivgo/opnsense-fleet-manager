import { useMemo, useState } from "react";
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
import CloudDownloadOutlinedIcon from "@mui/icons-material/CloudDownloadOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import PictureAsPdfOutlinedIcon from "@mui/icons-material/PictureAsPdfOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toApiError } from "@/api/client";
import { reportsApi } from "@/api/endpoints";
import { qk } from "@/api/queryKeys";
import type { Report, ReportKind } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { REPORT_KINDS, REPORT_KIND_LABELS } from "@/utils/constants";
import { downloadBlob, formatBytes, formatDateTime, fromNow } from "@/utils/format";

const PERIOD_PRESETS = [1, 7, 30, 90, 365];

const PENDING_STATUSES = new Set(["pending", "generating"]);

interface ReportFormState {
  name: string;
  kind: ReportKind;
  period_days: number;
}

function defaultForm(): ReportFormState {
  return { name: "", kind: "fleet", period_days: 7 };
}

export function ReportsPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<ReportFormState>(defaultForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Report | null>(null);

  const reportsQuery = useQuery({
    queryKey: qk.reports.list,
    queryFn: () => reportsApi.list(),
    // Poll only while the worker is still producing a PDF.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((report) => PENDING_STATUSES.has(report.status)) ? 5_000 : false,
  });

  const reports = useMemo(() => reportsQuery.data ?? [], [reportsQuery.data]);
  const readyCount = reports.filter((report) => report.status === "ready").length;
  const runningCount = reports.filter((report) => PENDING_STATUSES.has(report.status)).length;
  const failedCount = reports.filter((report) => report.status === "failed").length;

  const createMutation = useMutation({
    mutationFn: () =>
      reportsApi.create({
        name: form.name.trim() || null,
        kind: form.kind,
        period_days: form.period_days,
      }),
    onSuccess: (report) => {
      void queryClient.invalidateQueries({ queryKey: qk.reports.all });
      setDialogOpen(false);
      setForm(defaultForm());
      setFormError(null);
      dispatch(
        showToast({
          message: `Report "${report.name}" queued — it appears here once the PDF is ready.`,
          severity: "success",
        }),
      );
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const downloadMutation = useMutation({
    mutationFn: (report: Report) => reportsApi.download(report.id),
    onSuccess: (blob, report) => {
      downloadBlob(blob, `${report.kind}-report-${report.id.slice(0, 8)}.pdf`);
      dispatch(showToast({ message: "Report downloaded", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const deleteMutation = useMutation({
    mutationFn: (report: Report) => reportsApi.remove(report.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.reports.all });
      setDeleteTarget(null);
      dispatch(showToast({ message: "Report deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreate = () => {
    setForm(defaultForm());
    setFormError(null);
    setDialogOpen(true);
  };

  const submit = () => {
    if (!Number.isInteger(form.period_days) || form.period_days < 1 || form.period_days > 365) {
      setFormError("The reporting period must be between 1 and 365 days.");
      return;
    }
    if (form.name.trim() && form.name.trim().length < 2) {
      setFormError("Use at least two characters for the report name, or leave it blank.");
      return;
    }
    setFormError(null);
    createMutation.mutate();
  };

  const columns: Array<DataTableColumn<Report>> = [
    {
      key: "name",
      label: "Report",
      render: (report) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {report.name}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {REPORT_KIND_LABELS[report.kind] ?? report.kind} · created {fromNow(report.created_at)}
          </Typography>
        </Box>
      ),
    },
    {
      key: "period",
      label: "Period",
      width: 210,
      render: (report) => (
        <Typography variant="body2">
          {formatDateTime(report.period_start)} → {formatDateTime(report.period_end)}
        </Typography>
      ),
    },
    {
      key: "status",
      label: "Status",
      width: 150,
      render: (report) => (
        <Stack spacing={0.5} alignItems="flex-start">
          <StatusChip status={report.status} />
          {report.error && (
            <Typography variant="caption" color="error" sx={{ maxWidth: 220 }}>
              {report.error}
            </Typography>
          )}
        </Stack>
      ),
    },
    {
      key: "size",
      label: "Size",
      width: 110,
      align: "right",
      hideBelow: "md",
      render: (report) => <Typography variant="body2">{formatBytes(report.size_bytes)}</Typography>,
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 120,
      render: (report) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="report:read">
            <Tooltip title={report.status === "ready" ? "Download PDF" : "Available once the PDF is ready"}>
              <span>
                <IconButton
                  size="small"
                  disabled={report.status !== "ready" || downloadMutation.isPending}
                  onClick={(event) => {
                    event.stopPropagation();
                    downloadMutation.mutate(report);
                  }}
                >
                  <CloudDownloadOutlinedIcon fontSize="small" />
                </IconButton>
              </span>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="report:write">
            <Tooltip title="Delete report">
              <IconButton
                size="small"
                color="error"
                onClick={(event) => {
                  event.stopPropagation();
                  setDeleteTarget(report);
                }}
              >
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
        title="Reports"
        subtitle="Generate signed PDF reports for the fleet, compliance posture, traffic or alert history. Reports are produced in the background and kept with their parameters for audit."
        actions={
          <PermissionGate permission="report:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New report
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
            <Chip size="small" label={`${reports.length} reports`} />
            <Chip size="small" color="success" variant="outlined" label={`${readyCount} ready`} />
            <Chip size="small" color="warning" variant="outlined" label={`${runningCount} running`} />
            {failedCount > 0 && (
              <Chip size="small" color="error" variant="outlined" label={`${failedCount} failed`} />
            )}
          </Stack>
        }
      />

      <DataTable
        columns={columns}
        rows={reports}
        getRowId={(report) => report.id}
        loading={reportsQuery.isLoading}
        error={reportsQuery.error ? toApiError(reportsQuery.error).message : null}
        onRetry={() => reportsQuery.refetch()}
        emptyTitle="No reports yet"
        emptyDescription="Queue a report to export fleet, compliance, traffic or alert data as a PDF."
        emptyAction={
          <PermissionGate permission="report:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New report
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
            <Stack direction="row" spacing={1} alignItems="center">
              <PictureAsPdfOutlinedIcon fontSize="small" color="disabled" />
              <Typography variant="body2" color="text.secondary">
                Generation runs as a background task; the list refreshes while a report is queued.
              </Typography>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              PDF · generated by the report worker
            </Typography>
          </Stack>
        }
      />

      <FormDialog
        open={dialogOpen}
        title="New PDF report"
        description={
          <Typography variant="body2" color="text.secondary">
            The report covers the trailing period ending now. Generation is asynchronous, so it may take a
            few seconds before the PDF is downloadable.
          </Typography>
        }
        submitLabel="Queue report"
        loading={createMutation.isPending}
        error={formError}
        onSubmit={submit}
        onClose={() => setDialogOpen(false)}
        maxWidth="sm"
      >
        <TextField
          label="Report name"
          value={form.name}
          onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
          helperText="Optional. A descriptive name is generated when left blank."
          autoFocus
        />
        <TextField
          select
          label="Report kind"
          value={form.kind}
          onChange={(event) => setForm((value) => ({ ...value, kind: event.target.value as ReportKind }))}
          helperText={REPORT_KINDS.find((kind) => kind.value === form.kind)?.description}
        >
          {REPORT_KINDS.map((kind) => (
            <MenuItem key={kind.value} value={kind.value}>
              {kind.label}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Period (days)"
          type="number"
          value={form.period_days}
          onChange={(event) =>
            setForm((value) => ({ ...value, period_days: Number(event.target.value) || 0 }))
          }
          inputProps={{ min: 1, max: 365 }}
          helperText="Between 1 and 365 days of history."
        />
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {PERIOD_PRESETS.map((days) => (
            <Chip
              key={days}
              label={`${days}d`}
              size="small"
              variant={form.period_days === days ? "filled" : "outlined"}
              color={form.period_days === days ? "primary" : "default"}
              onClick={() => setForm((value) => ({ ...value, period_days: days }))}
            />
          ))}
        </Stack>
        {form.kind === "traffic" && (
          <Alert severity="info">
            Traffic reports summarise interface throughput recorded in telemetry snapshots for the period.
          </Alert>
        )}
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete report"
        description={
          deleteTarget
            ? `Delete "${deleteTarget.name}" and its stored PDF? The deletion is recorded in the audit trail.`
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

export default ReportsPage;
