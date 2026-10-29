import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  LinearProgress,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
  alpha,
  useTheme,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import BuildOutlinedIcon from "@mui/icons-material/BuildOutlined";
import VerifiedUserOutlinedIcon from "@mui/icons-material/VerifiedUserOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { complianceApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { ComplianceFramework, ComplianceReport, ComplianceSummary } from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE, FRAMEWORKS, FRAMEWORK_LABELS } from "@/utils/constants";
import { formatDateTime, fromNow, prettyJson } from "@/utils/format";

function scoreColor(score: number | null): "success" | "warning" | "error" | "primary" {
  if (score === null) return "primary";
  if (score >= 90) return "success";
  if (score >= 70) return "warning";
  return "error";
}

interface ControlRow {
  control_id?: string;
  title?: string;
  status?: string;
  severity?: string;
  evidence?: string | null;
  remediation?: string | null;
  affected_devices?: string[];
}

export function CompliancePage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const theme = useTheme();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [frameworkFilter, setFrameworkFilter] = useState("");
  const [runOpen, setRunOpen] = useState(false);
  const [runFramework, setRunFramework] = useState<ComplianceFramework>("cis");
  const [runError, setRunError] = useState<string | null>(null);
  const [reportTarget, setReportTarget] = useState<ComplianceReport | null>(null);
  const [evidence, setEvidence] = useState<Record<string, unknown> | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ComplianceReport | null>(null);
  const [remediateOpen, setRemediateOpen] = useState(false);

  const summaryQuery = useQuery({
    queryKey: qk.compliance.summary,
    queryFn: () => complianceApi.summary(),
    staleTime: 60_000,
  });

  const reportsQuery = useQuery({
    queryKey: qk.compliance.reports({ page, size, framework: frameworkFilter || undefined }),
    queryFn: () =>
      complianceApi.reports({
        page,
        size,
        framework: (frameworkFilter || undefined) as ComplianceFramework | undefined,
      }),
    refetchInterval: 60_000,
  });

  const runMutation = useMutation({
    mutationFn: () => complianceApi.run({ framework: runFramework, device_ids: [] }),
    onSuccess: (report) => {
      queryClient.setQueryData(qk.compliance.report(report.id), report);
      setReportTarget(report);
      setRunOpen(false);
      setRunError(null);
      void queryClient.invalidateQueries({ queryKey: qk.compliance.all });
      void queryClient.invalidateQueries({ queryKey: qk.dashboard });
      dispatch(
        showToast({
          message: `${FRAMEWORK_LABELS[report.framework] ?? report.framework} scan finished: ${report.score.toFixed(1)}%`,
          severity: report.score >= 80 ? "success" : "warning",
        }),
      );
    },
    onError: (error) => setRunError(toApiError(error).message),
  });

  const evidenceMutation = useMutation({
    mutationFn: (reportId: string) => complianceApi.evidence(reportId),
    onSuccess: (result) => {
      setEvidence(result);
      dispatch(showToast({ message: "Evidence bundle loaded", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => complianceApi.removeReport(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.compliance.all });
      setDeleteTarget(null);
      dispatch(showToast({ message: "Compliance report deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const remediateMutation = useMutation({
    mutationFn: (report: ComplianceReport) =>
      complianceApi.remediate({
        finding_ids: report.findings.map((finding, index) => String(finding.id ?? index)),
        device_ids: [],
        dry_run: false,
      }),
    onSuccess: (result) => {
      setRemediateOpen(false);
      void queryClient.invalidateQueries({ queryKey: qk.compliance.all });
      dispatch(
        showToast({
          message: `Remediation finished: ${String(result.remediated ?? 0)} applied, ${String(result.failed ?? 0)} failed`,
          severity: "success",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const columns: Array<DataTableColumn<ComplianceReport>> = [
    {
      key: "framework",
      label: "Framework",
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <VerifiedUserOutlinedIcon fontSize="small" color="action" />
          <Box>
            <Typography variant="body2" fontWeight={600}>
              {FRAMEWORK_LABELS[row.framework] ?? row.framework}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {row.controls_total} controls · {row.controls_failed} failed
            </Typography>
          </Box>
        </Stack>
      ),
    },
    {
      key: "score",
      label: "Score",
      width: 160,
      render: (row) => (
        <Stack spacing={0.5}>
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="body2" fontWeight={700}>
              {row.score.toFixed(1)}%
            </Typography>
            <Chip size="small" color={scoreColor(row.score)} label={row.score >= 90 ? "pass" : row.score >= 70 ? "at risk" : "fail"} />
          </Stack>
          <LinearProgress
            variant="determinate"
            value={Math.min(100, Math.max(0, row.score))}
            color={scoreColor(row.score)}
            sx={{ height: 5, borderRadius: 3 }}
          />
        </Stack>
      ),
    },
    { key: "status", label: "Status", width: 120, render: (row) => <StatusChip status={row.status} /> },
    {
      key: "scope",
      label: "Scope",
      width: 120,
      hideBelow: "md",
      render: (row) => {
        const count = Array.isArray(row.scope.device_ids) ? row.scope.device_ids.length : 0;
        return count ? `${count} devices` : "Tenant";
      },
    },
    {
      key: "generated",
      label: "Generated",
      width: 170,
      render: (row) => (
        <Tooltip title={formatDateTime(row.generated_at)}>
          <span>{fromNow(row.generated_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 140,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <Tooltip title="Open report">
            <Button
              size="small"
              onClick={(event) => {
                event.stopPropagation();
                setReportTarget(row);
                setEvidence(null);
              }}
            >
              Open
            </Button>
          </Tooltip>
          <PermissionGate permission="compliance:run">
            <Tooltip title="Delete report">
              <Button
                size="small"
                color="error"
                onClick={(event) => {
                  event.stopPropagation();
                  setDeleteTarget(row);
                }}
              >
                <DeleteOutlineIcon fontSize="small" />
              </Button>
            </Tooltip>
          </PermissionGate>
        </Stack>
      ),
    },
  ];

  const summaries: ComplianceSummary[] = summaryQuery.data ?? [];

  return (
    <>
      <PageHeader
        title="Compliance"
        subtitle="Continuous control evaluation for CIS, ISO/IEC 27001, NIS2, PCI DSS and SOC 2 with evidence retention."
        actions={
          <PermissionGate permission="compliance:run">
            <Button variant="contained" startIcon={<PlayArrowIcon />} onClick={() => setRunOpen(true)}>
              Run assessment
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <Chip size="small" label={`${reportsQuery.data?.meta.total ?? 0} reports`} />
            <Chip size="small" variant="outlined" label={`${summaries.filter((item) => item.latest_score !== null).length} evaluated frameworks`} />
          </Stack>
        }
      />

      {summaryQuery.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {toApiError(summaryQuery.error).message}
        </Alert>
      )}

      <Grid container spacing={2} sx={{ mb: 3 }}>
        {FRAMEWORKS.map((framework) => {
          const summary = summaries.find((item) => item.framework === framework.value);
          const score = summary?.latest_score ?? null;
          return (
            <Grid item xs={12} sm={6} lg={2.4} key={framework.value}>
              <Card sx={{ height: "100%" }}>
                <CardContent>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
                    <Box>
                      <Typography variant="overline" color="text.secondary">
                        {framework.label}
                      </Typography>
                      <Typography variant="h2" sx={{ fontSize: "1.75rem", lineHeight: 1.2 }}>
                        {score !== null ? `${score.toFixed(1)}%` : "—"}
                      </Typography>
                    </Box>
                    <Chip size="small" color={scoreColor(score)} label={score === null ? "no data" : score >= 90 ? "pass" : score >= 70 ? "risk" : "fail"} />
                  </Stack>
                  <LinearProgress
                    variant="determinate"
                    value={score ?? 0}
                    color={scoreColor(score)}
                    sx={{ height: 6, borderRadius: 3, my: 1.25 }}
                  />
                  <Typography variant="caption" color="text.secondary" display="block">
                    {summary ? `${summary.controls_total} controls · ${summary.controls_failed} failed` : framework.description}
                  </Typography>
                  <Typography variant="caption" color="text.disabled" display="block" sx={{ mt: 0.25 }}>
                    {summary?.last_run ? `Last run ${fromNow(summary.last_run)}` : "Not yet assessed"}
                  </Typography>
                  {summary && summary.trend.length > 1 && (
                    <Stack direction="row" spacing={0.25} alignItems="flex-end" sx={{ mt: 1, height: 26 }}>
                      {summary.trend.slice(-12).map((point, index) => {
                        const value = Number(point.score ?? 0);
                        return (
                          <Box
                            key={`${framework.value}-${index}`}
                            sx={{
                              flex: 1,
                              height: `${Math.max(8, value)}%`,
                              borderRadius: 0.5,
                              bgcolor:
                                value >= 90
                                  ? theme.palette.success.main
                                  : value >= 70
                                    ? theme.palette.warning.main
                                    : theme.palette.error.main,
                              opacity: 0.7,
                            }}
                          />
                        );
                      })}
                    </Stack>
                  )}
                </CardContent>
              </Card>
            </Grid>
          );
        })}
      </Grid>

      <DataTable
        columns={columns}
        rows={reportsQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={reportsQuery.isLoading}
        error={reportsQuery.error ? toApiError(reportsQuery.error).message : null}
        onRetry={() => reportsQuery.refetch()}
        page={page}
        size={size}
        total={reportsQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        onRowClick={(row) => {
          setReportTarget(row);
          setEvidence(null);
        }}
        emptyTitle="No compliance reports"
        emptyDescription="Run an assessment to evaluate the fleet against a framework."
        emptyAction={
          <PermissionGate permission="compliance:run">
            <Button variant="contained" startIcon={<PlayArrowIcon />} onClick={() => setRunOpen(true)}>
              Run assessment
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction="row" spacing={1} justifyContent="space-between" alignItems="center">
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <Typography variant="h5" sx={{ alignSelf: "center", mr: 1 }}>
                Assessment history
              </Typography>
              <TextField
                select
                label="Framework"
                value={frameworkFilter}
                onChange={(event) => {
                  setFrameworkFilter(event.target.value);
                  setPage(1);
                }}
                sx={{ minWidth: 200 }}
              >
                <MenuItem value="">All frameworks</MenuItem>
                {FRAMEWORKS.map((framework) => (
                  <MenuItem key={framework.value} value={framework.value}>
                    {framework.label}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
            <Typography variant="caption" color="text.secondary">
              {reportsQuery.data?.meta.total ?? 0} reports
            </Typography>
          </Stack>
        }
      />

      <FormDialog
        open={runOpen}
        title="Run compliance assessment"
        description={
          <Typography variant="body2" color="text.secondary">
            The engine collects configuration evidence from every device in the tenant, evaluates the selected
            control set and stores an immutable report with a downloadable evidence bundle.
          </Typography>
        }
        submitLabel="Start assessment"
        loading={runMutation.isPending}
        error={runError}
        onSubmit={() => runMutation.mutate()}
        onClose={() => setRunOpen(false)}
      >
        <TextField
          select
          label="Framework"
          value={runFramework}
          onChange={(event) => setRunFramework(event.target.value as ComplianceFramework)}
        >
          {FRAMEWORKS.map((framework) => (
            <MenuItem key={framework.value} value={framework.value}>
              {framework.label} — {framework.description}
            </MenuItem>
          ))}
        </TextField>
        <Alert severity="info">
          Large fleets may take several minutes. The report appears here when evaluation completes and the run is
          recorded in the audit trail.
        </Alert>
      </FormDialog>

      <FormDialog
        open={Boolean(reportTarget)}
        title={
          reportTarget
            ? `${FRAMEWORK_LABELS[reportTarget.framework] ?? reportTarget.framework} · ${reportTarget.score.toFixed(1)}%`
            : "Compliance report"
        }
        submitLabel="Close"
        onSubmit={() => {
          setReportTarget(null);
          setEvidence(null);
        }}
        onClose={() => {
          setReportTarget(null);
          setEvidence(null);
        }}
        maxWidth="lg"
      >
        {reportTarget && (
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip color={scoreColor(reportTarget.score)} label={`${reportTarget.score.toFixed(1)}% score`} />
              <StatusChip status={reportTarget.status} />
              <Chip variant="outlined" label={`${reportTarget.controls_total} controls`} />
              <Chip variant="outlined" color="success" label={`${reportTarget.controls_passed} passed`} />
              <Chip variant="outlined" color="error" label={`${reportTarget.controls_failed} failed`} />
              <Chip variant="outlined" label={formatDateTime(reportTarget.generated_at)} />
            </Stack>
            {reportTarget.summary && (
              <Typography variant="body2" color="text.secondary">
                {reportTarget.summary}
              </Typography>
            )}
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button
                size="small"
                variant="outlined"
                startIcon={<VisibilityOutlinedIcon />}
                onClick={() => evidenceMutation.mutate(reportTarget.id)}
                disabled={evidenceMutation.isPending}
              >
                Load evidence bundle
              </Button>
              <PermissionGate permission="compliance:remediate">
                <Button
                  size="small"
                  variant="outlined"
                  color="warning"
                  startIcon={<BuildOutlinedIcon />}
                  onClick={() => setRemediateOpen(true)}
                  disabled={reportTarget.controls_failed === 0}
                >
                  Remediate failed controls
                </Button>
              </PermissionGate>
              <PermissionGate permission="compliance:run">
                <Button size="small" color="error" onClick={() => setDeleteTarget(reportTarget)}>
                  Delete report
                </Button>
              </PermissionGate>
              {reportTarget.artifact_key && (
                <Chip size="small" variant="outlined" label={reportTarget.artifact_key} />
              )}
            </Stack>

            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Controls
              </Typography>
              <Stack spacing={0.75}>
                {(reportTarget.controls as unknown as ControlRow[]).slice(0, 40).map((control, index) => (
                  <Stack
                    key={`${control.control_id ?? index}`}
                    direction={{ xs: "column", sm: "row" }}
                    spacing={1}
                    alignItems={{ xs: "flex-start", sm: "center" }}
                    justifyContent="space-between"
                    sx={{
                      p: 1.25,
                      border: 1,
                      borderColor: "divider",
                      borderRadius: 1.5,
                      bgcolor:
                        control.status === "failed"
                          ? alpha(theme.palette.error.main, 0.05)
                          : control.status === "passed"
                            ? alpha(theme.palette.success.main, 0.04)
                            : undefined,
                    }}
                  >
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="body2" fontWeight={600}>
                        {control.control_id ?? "Control"} · {control.title ?? ""}
                      </Typography>
                      {control.evidence && (
                        <Typography variant="caption" color="text.secondary" display="block">
                          {control.evidence}
                        </Typography>
                      )}
                      {control.remediation && control.status === "failed" && (
                        <Typography variant="caption" color="warning.main" display="block">
                          Fix: {control.remediation}
                        </Typography>
                      )}
                    </Box>
                    <Stack direction="row" spacing={1} alignItems="center">
                      {Array.isArray(control.affected_devices) && control.affected_devices.length > 0 && (
                        <Chip size="small" variant="outlined" label={`${control.affected_devices.length} devices`} />
                      )}
                      <StatusChip status={control.status} />
                    </Stack>
                  </Stack>
                ))}
                {reportTarget.controls.length > 40 && (
                  <Typography variant="caption" color="text.secondary">
                    Showing 40 of {reportTarget.controls.length} controls. Export the evidence bundle for the full
                    report.
                  </Typography>
                )}
              </Stack>
            </Box>

            {evidence && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  Evidence bundle
                </Typography>
                <CodeBlock code={prettyJson(evidence)} language="json" maxHeight={320} />
              </Box>
            )}
          </Stack>
        )}
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete compliance report"
        description="Deleting a report removes its stored evidence artifact. Audit records of the assessment remain immutable."
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => {
          if (!deleteTarget) return;
          deleteMutation.mutate(deleteTarget.id);
          setReportTarget(null);
        }}
        onClose={() => setDeleteTarget(null)}
      />

      <ConfirmDialog
        open={remediateOpen}
        title="Remediate failed controls"
        description="The remediation engine applies known-safe configuration fixes for failed controls. A pre-change backup is created automatically when backups are configured."
        confirmLabel="Apply fixes"
        confirmColor="warning"
        loading={remediateMutation.isPending}
        onConfirm={() => reportTarget && remediateMutation.mutate(reportTarget)}
        onClose={() => setRemediateOpen(false)}
      />
    </>
  );
}

export default CompliancePage;
