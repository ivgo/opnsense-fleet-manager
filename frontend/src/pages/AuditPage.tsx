import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
  alpha,
  useTheme,
} from "@mui/material";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import FingerprintOutlinedIcon from "@mui/icons-material/FingerprintOutlined";
import HistoryOutlinedIcon from "@mui/icons-material/HistoryOutlined";
import RefreshIcon from "@mui/icons-material/Refresh";
import ShieldOutlinedIcon from "@mui/icons-material/ShieldOutlined";
import VerifiedUserOutlinedIcon from "@mui/icons-material/VerifiedUserOutlined";
import { useMutation, useQuery } from "@tanstack/react-query";

import { auditApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { AuditEntry } from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import DetailGrid from "@/components/DetailGrid";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { downloadBlob, formatDateTime, formatNumber, fromNow, prettyJson } from "@/utils/format";

interface DateFilters {
  from_date: string;
  to_date: string;
}

const EMPTY_DATES: DateFilters = { from_date: "", to_date: "" };

function toIso(value: string): string | undefined {
  if (!value) return undefined;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
}

function resultColor(result: string): "success" | "error" {
  return result === "success" ? "success" : "error";
}

export function AuditPage() {
  const dispatch = useAppDispatch();
  const theme = useTheme();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [actionFilter, setActionFilter] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");
  const [resultFilter, setResultFilter] = useState("");
  const [dates, setDates] = useState<DateFilters>(EMPTY_DATES);
  const [selectingDates, setSelectingDates] = useState<DateFilters>(EMPTY_DATES);
  const [dateDialogOpen, setDateDialogOpen] = useState(false);
  const [selected, setSelected] = useState<AuditEntry | null>(null);
  const [eventTarget, setEventTarget] = useState<AuditEntry | null>(null);

  const listParams = useMemo(
    () => ({
      page,
      size,
      action: actionFilter || undefined,
      resource_type: resourceFilter || undefined,
      result: resultFilter || undefined,
      from_date: toIso(dates.from_date),
      to_date: toIso(dates.to_date),
    }),
    [page, size, actionFilter, resourceFilter, resultFilter, dates],
  );

  const auditQuery = useQuery({
    queryKey: qk.audit.list(listParams),
    queryFn: () => auditApi.list(listParams),
    refetchInterval: 30_000,
  });

  const integrityQuery = useQuery({
    queryKey: qk.audit.integrity,
    queryFn: () => auditApi.integrity(),
    staleTime: 60_000,
  });

  const actionsQuery = useQuery({
    queryKey: qk.audit.actions,
    queryFn: () => auditApi.actions(),
    staleTime: 120_000,
  });

  const eventsQuery = useQuery({
    queryKey: [...qk.audit.all, "events", eventTarget?.resource_type ?? "", eventTarget?.resource_id ?? ""],
    queryFn: () =>
      auditApi.events(eventTarget?.resource_type ?? "", eventTarget?.resource_id ?? ""),
    enabled: Boolean(eventTarget?.resource_id),
  });

  useEffect(() => {
    setPage(1);
  }, [actionFilter, resourceFilter, resultFilter, dates]);

  const exportMutation = useMutation({
    mutationFn: () =>
      auditApi.export({
        action: actionFilter || undefined,
        resource_type: resourceFilter || undefined,
        result: resultFilter || undefined,
        from_date: toIso(dates.from_date),
        to_date: toIso(dates.to_date),
      }),
    onSuccess: (blob) => {
      downloadBlob(blob, `ofme-audit-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`);
      dispatch(showToast({ message: "Audit export downloaded", severity: "success" }));
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const actions = useMemo(() => actionsQuery.data ?? [], [actionsQuery.data]);
  const actionOptions = useMemo(() => {
    const unique = new Map<string, string>();
    for (const entry of actions) {
      if (!unique.has(entry.action)) {
        unique.set(entry.action, entry.resource_type);
      }
    }
    return [...unique.entries()].map(([action, resourceType]) => ({ action, resourceType }));
  }, [actions]);

  const resourceTypes = useMemo(
    () => [...new Set(actions.map((entry) => entry.resource_type))].sort(),
    [actions],
  );

  const integrity = integrityQuery.data;
  const hasFilters = Boolean(
    actionFilter || resourceFilter || resultFilter || dates.from_date || dates.to_date,
  );

  const columns: Array<DataTableColumn<AuditEntry>> = [
    {
      key: "id",
      label: "ID",
      width: 82,
      monospace: true,
      render: (row) => `#${row.id}`,
    },
    {
      key: "created_at",
      label: "Timestamp",
      width: 180,
      render: (row) => (
        <Tooltip title={fromNow(row.created_at)}>
          <span>{formatDateTime(row.created_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: "actor",
      label: "Actor",
      width: 190,
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.actor ?? "system"}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" fontFamily="monospace">
            {row.ip_address ?? "no ip"}
          </Typography>
        </Box>
      ),
    },
    {
      key: "action",
      label: "Action",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600} fontFamily="monospace" fontSize={12.5}>
            {row.action}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {row.resource_type}
            {row.resource_id ? ` · ${row.resource_id.slice(0, 18)}` : ""}
          </Typography>
        </Box>
      ),
    },
    {
      key: "result",
      label: "Result",
      width: 110,
      render: (row) => (
        <Chip
          size="small"
          variant="outlined"
          color={resultColor(row.result)}
          label={row.result}
        />
      ),
    },
    {
      key: "request",
      label: "Request",
      width: 230,
      hideBelow: "lg",
      monospace: true,
      render: (row) =>
        row.method && row.path ? (
          <Typography variant="caption" color="text.secondary">
            {row.method} {row.path}
            {row.status_code ? ` · ${row.status_code}` : ""}
          </Typography>
        ) : (
          <Typography variant="caption" color="text.disabled">
            —
          </Typography>
        ),
    },
    {
      key: "request_id",
      label: "Request ID",
      width: 150,
      hideBelow: "lg",
      monospace: true,
      render: (row) => (row.request_id ? row.request_id.slice(0, 13) : "—"),
    },
  ];

  return (
    <>
      <PageHeader
        title="Audit trail"
        subtitle="Append-only, hash-chained record of every security-relevant action across the platform."
        actions={
          <>
            <Button
              variant="outlined"
              startIcon={<RefreshIcon />}
              onClick={() => {
                void integrityQuery.refetch();
                void actionsQuery.refetch();
                void auditQuery.refetch();
              }}
              disabled={auditQuery.isFetching || integrityQuery.isFetching}
            >
              Refresh
            </Button>
            <Button
              variant="contained"
              startIcon={<DownloadOutlinedIcon />}
              onClick={() => exportMutation.mutate()}
              disabled={exportMutation.isPending}
            >
              Export CSV
            </Button>
          </>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${formatNumber(auditQuery.data?.meta.total ?? 0)} entries`} />
            <Chip size="small" variant="outlined" label={`${formatNumber(actions.length)} actions observed`} />
            {integrity && (
              <Chip
                size="small"
                color={integrity.valid ? "success" : "error"}
                variant="outlined"
                label={integrity.valid ? "chain verified" : "chain broken"}
              />
            )}
          </Stack>
        }
      />

      <Card
        sx={{
          mb: 2,
          border: 1,
          borderColor: integrity && !integrity.valid ? "error.main" : "divider",
          bgcolor:
            integrity && !integrity.valid ? alpha(theme.palette.error.main, 0.06) : "background.paper",
        }}
      >
        <CardContent>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between">
            <Stack direction="row" spacing={1.5} alignItems="flex-start">
              <Box
                sx={{
                  p: 1,
                  borderRadius: 1.5,
                  bgcolor: alpha(
                    integrity && !integrity.valid ? theme.palette.error.main : theme.palette.success.main,
                    0.12,
                  ),
                  color: integrity && !integrity.valid ? "error.main" : "success.main",
                  display: "flex",
                }}
              >
                {integrity && !integrity.valid ? (
                  <ShieldOutlinedIcon />
                ) : (
                  <VerifiedUserOutlinedIcon />
                )}
              </Box>
              <Box>
                <Typography variant="h5" sx={{ mb: 0.25 }}>
                  {integrityQuery.isLoading
                    ? "Verifying hash chain…"
                    : integrity?.valid
                      ? "Audit chain integrity verified"
                      : "Audit chain integrity failure"}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {integrity
                    ? integrity.valid
                      ? `${formatNumber(integrity.checked)} entries were recomputed from the genesis block. Every entry links to its predecessor with SHA-256.`
                      : `The chain breaks at entry #${integrity.first_broken_id ?? "?"}. Treat the trail as tampered and escalate to security operations immediately.`
                    : "The integrity endpoint runs a full recomputation of the stored hash chain."}
                </Typography>
              </Box>
            </Stack>
            <Stack spacing={0.5} sx={{ minWidth: 260 }}>
              <DetailGrid
                dense
                items={[
                  { label: "Entries checked", value: formatNumber(integrity?.checked ?? 0) },
                  {
                    label: "Last hash",
                    value: integrity?.last_hash ? (
                      <Typography variant="caption" fontFamily="monospace">
                        {integrity.last_hash.slice(0, 20)}…
                      </Typography>
                    ) : (
                      "—"
                    ),
                  },
                  { label: "Verified", value: integrity ? formatDateTime(new Date().toISOString()) : "—" },
                ]}
              />
            </Stack>
          </Stack>
          {integrity && !integrity.valid && (
            <Alert severity="error" sx={{ mt: 2 }}>
              Hash chain verification failed. Do not delete entries; preserve the database and object storage for
              forensic analysis.
            </Alert>
          )}
          {integrityQuery.isError && (
            <Alert severity="warning" sx={{ mt: 2 }}>
              {toApiError(integrityQuery.error).message}
            </Alert>
          )}
        </CardContent>
      </Card>

      <DataTable
        columns={columns}
        rows={auditQuery.data?.items ?? []}
        getRowId={(row) => String(row.id)}
        loading={auditQuery.isLoading}
        error={auditQuery.error ? toApiError(auditQuery.error).message : null}
        onRetry={() => auditQuery.refetch()}
        page={page}
        size={size}
        total={auditQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        onRowClick={(row) => setSelected(row)}
        dense
        maxHeight="62vh"
        stickyHeader
        emptyTitle={hasFilters ? "No audit entries match the filters" : "No audit entries yet"}
        emptyDescription={
          hasFilters
            ? "Widen the time window or clear the filters. The trail only contains actions that were actually performed."
            : "Authentication, configuration changes, deployments and administrative actions appear here as they happen."
        }
        toolbar={
          <Stack
            direction={{ xs: "column", xl: "row" }}
            spacing={1}
            alignItems={{ xs: "stretch", xl: "center" }}
            justifyContent="space-between"
          >
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap>
              <TextField
                select
                label="Action"
                value={actionFilter}
                onChange={(event) => setActionFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 260 } }}
              >
                <MenuItem value="">All actions</MenuItem>
                {actionOptions.map((option) => (
                  <MenuItem key={option.action} value={option.action}>
                    {option.action}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Resource"
                value={resourceFilter}
                onChange={(event) => setResourceFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 180 } }}
              >
                <MenuItem value="">All resources</MenuItem>
                {resourceTypes.map((type) => (
                  <MenuItem key={type} value={type}>
                    {type}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Result"
                value={resultFilter}
                onChange={(event) => setResultFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 140 } }}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="success">Success</MenuItem>
                <MenuItem value="failure">Failure</MenuItem>
              </TextField>
              <Button
                variant="outlined"
                startIcon={<HistoryOutlinedIcon />}
                onClick={() => {
                  setSelectingDates(dates);
                  setDateDialogOpen(true);
                }}
              >
                {dates.from_date || dates.to_date ? "Time window set" : "Time window"}
              </Button>
              {hasFilters && (
                <Button
                  color="inherit"
                  onClick={() => {
                    setActionFilter("");
                    setResourceFilter("");
                    setResultFilter("");
                    setDates(EMPTY_DATES);
                  }}
                >
                  Clear filters
                </Button>
              )}
            </Stack>
            <Stack direction="row" spacing={1} alignItems="center">
              <FingerprintOutlinedIcon fontSize="small" color="action" />
              <Typography variant="caption" color="text.secondary">
                {formatNumber(auditQuery.data?.meta.total ?? 0)} entries · newest first
              </Typography>
            </Stack>
          </Stack>
        }
      />

      <FormDialog
        open={dateDialogOpen}
        title="Filter by time window"
        description={
          <Typography variant="body2" color="text.secondary">
            Times are interpreted in your local timezone and sent as UTC. Leave a field empty for an open-ended
            range.
          </Typography>
        }
        submitLabel="Apply window"
        onSubmit={() => {
          setDates(selectingDates);
          setDateDialogOpen(false);
        }}
        onClose={() => setDateDialogOpen(false)}
        maxWidth="sm"
      >
        <TextField
          label="From"
          type="datetime-local"
          value={selectingDates.from_date}
          onChange={(event) =>
            setSelectingDates((value) => ({ ...value, from_date: event.target.value }))
          }
          InputLabelProps={{ shrink: true }}
        />
        <TextField
          label="To"
          type="datetime-local"
          value={selectingDates.to_date}
          onChange={(event) => setSelectingDates((value) => ({ ...value, to_date: event.target.value }))}
          InputLabelProps={{ shrink: true }}
        />
      </FormDialog>

      <FormDialog
        open={Boolean(selected)}
        title={selected ? `Audit entry #${selected.id}` : "Audit entry"}
        description={
          selected ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip size="small" color={resultColor(selected.result)} label={selected.result} />
              <Chip size="small" variant="outlined" label={selected.action} />
              <Chip size="small" variant="outlined" label={selected.resource_type} />
              <Chip size="small" variant="outlined" label={formatDateTime(selected.created_at)} />
            </Stack>
          ) : undefined
        }
        submitLabel="Close"
        onSubmit={() => setSelected(null)}
        onClose={() => setSelected(null)}
        maxWidth="lg"
      >
        {selected && (
          <Stack spacing={2}>
            <DetailGrid
              items={[
                { label: "Entry", value: `#${selected.id}` },
                { label: "Timestamp", value: formatDateTime(selected.created_at) },
                { label: "Actor", value: selected.actor ?? "system" },
                { label: "User ID", value: selected.user_id ?? "—" },
                { label: "Tenant", value: selected.tenant_id ?? "platform" },
                { label: "IP address", value: selected.ip_address ?? "—" },
                { label: "Action", value: selected.action },
                { label: "Resource", value: `${selected.resource_type}${selected.resource_id ? ` · ${selected.resource_id}` : ""}` },
                { label: "Result", value: selected.result },
                { label: "HTTP status", value: selected.status_code ?? "—" },
                { label: "Request", value: selected.method && selected.path ? `${selected.method} ${selected.path}` : "—" },
                { label: "Request ID", value: selected.request_id ?? "—" },
              ]}
            />
            {selected.error && (
              <Alert severity="error">
                <Typography variant="body2" fontFamily="monospace">
                  {selected.error}
                </Typography>
              </Alert>
            )}
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  Before
                </Typography>
                <CodeBlock
                  code={selected.before ? prettyJson(selected.before) : "null"}
                  language="json"
                  maxHeight={280}
                  showCopy={Boolean(selected.before)}
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  After
                </Typography>
                <CodeBlock
                  code={selected.after ? prettyJson(selected.after) : "null"}
                  language="json"
                  maxHeight={280}
                  showCopy={Boolean(selected.after)}
                />
              </Grid>
            </Grid>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button
                variant="outlined"
                startIcon={<HistoryOutlinedIcon />}
                disabled={!selected.resource_id}
                onClick={() => setEventTarget(selected)}
              >
                Load domain events
              </Button>
              <Button
                variant="outlined"
                startIcon={<DownloadOutlinedIcon />}
                onClick={() =>
                  exportMutation.mutate()
                }
                disabled={exportMutation.isPending}
              >
                Export filtered CSV
              </Button>
            </Stack>
            {eventTarget && eventTarget.id === selected.id && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  Aggregate event stream
                </Typography>
                {eventsQuery.isLoading ? (
                  <Typography variant="body2" color="text.secondary">
                    Loading events…
                  </Typography>
                ) : eventsQuery.isError ? (
                  <Alert severity="error">{toApiError(eventsQuery.error).message}</Alert>
                ) : (eventsQuery.data ?? []).length === 0 ? (
                  <Alert severity="info">No domain events were recorded for this aggregate.</Alert>
                ) : (
                  <Stack spacing={1}>
                    {(eventsQuery.data ?? []).map((event, index) => (
                      <Box
                        key={`${String(event.event_id ?? index)}`}
                        sx={{ border: 1, borderColor: "divider", borderRadius: 1.5, p: 1.5 }}
                      >
                        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                          <Chip size="small" label={`#${String(event.sequence ?? index + 1)}`} />
                          <Typography variant="body2" fontWeight={600} fontFamily="monospace">
                            {String(event.event_type ?? "event")}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {formatDateTime(
                              typeof event.occurred_at === "string" ? event.occurred_at : null,
                            )}
                          </Typography>
                        </Stack>
                        <CodeBlock
                          code={prettyJson(event.payload ?? {})}
                          language="json"
                          maxHeight={180}
                          showCopy={false}
                        />
                      </Box>
                    ))}
                  </Stack>
                )}
              </Box>
            )}
          </Stack>
        )}
      </FormDialog>
    </>
  );
}

export default AuditPage;
