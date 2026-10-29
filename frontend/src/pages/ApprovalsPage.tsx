import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  LinearProgress,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CancelOutlinedIcon from "@mui/icons-material/CancelOutlined";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import HighlightOffOutlinedIcon from "@mui/icons-material/HighlightOffOutlined";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { toApiError } from "@/api/client";
import { changesApi } from "@/api/endpoints";
import { qk } from "@/api/queryKeys";
import type { ChangeRequest, Environment } from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE, ENVIRONMENTS } from "@/utils/constants";
import { EMPTY, formatDateTime, fromNow, prettyJson, titleCase } from "@/utils/format";

const STATUS_FILTERS = [
  { value: "", label: "All statuses" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "applied", label: "Applied" },
  { value: "expired", label: "Expired" },
  { value: "cancelled", label: "Cancelled" },
];

const CHANGE_TYPES = [
  { value: "firewall_rule", label: "Firewall rule" },
  { value: "nat", label: "NAT" },
  { value: "vpn", label: "VPN" },
  { value: "template", label: "Template" },
  { value: "config", label: "Configuration" },
  { value: "policy", label: "Policy" },
];

const PRIORITIES = ["low", "medium", "high", "critical"];

const PRIORITY_COLORS: Record<string, "default" | "info" | "warning" | "error"> = {
  low: "default",
  medium: "info",
  high: "warning",
  critical: "error",
};

interface ApprovalEntry {
  user_id?: string;
  decision?: string;
  comment?: string | null;
  at?: string;
}

interface CreateFormState {
  title: string;
  description: string;
  type: string;
  priority: string;
  environment: string;
  required_approvals: number;
}

const EMPTY_FORM: CreateFormState = {
  title: "",
  description: "",
  type: "policy",
  priority: "medium",
  environment: "",
  required_approvals: 1,
};

export function ApprovalsPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const currentUser = useAppSelector((state) => state.auth.user);

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<ChangeRequest | null>(null);
  const [decision, setDecision] = useState<{ change: ChangeRequest; mode: "approve" | "reject" } | null>(
    null,
  );
  const [comment, setComment] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState<CreateFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const listParams = useMemo(
    () => ({
      page,
      size,
      sort: "created_at",
      order: "desc" as const,
      status: status || undefined,
      search: search.trim() || undefined,
    }),
    [page, size, status, search],
  );

  const changesQuery = useQuery({
    queryKey: qk.changes.list(listParams),
    queryFn: () => changesApi.list(listParams),
    refetchInterval: 60_000,
  });

  useEffect(() => {
    setPage(1);
  }, [status]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.changes.all });
  };

  const approveMutation = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      changesApi.approve(id, note.trim() || undefined),
    onSuccess: (change) => {
      invalidate();
      setDecision(null);
      setComment("");
      setSelected((current) => (current?.id === change.id ? change : current));
      dispatch(
        showToast({
          message:
            change.status === "approved"
              ? "Change request approved"
              : "Approval recorded — more approvals required",
          severity: "success",
        }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      changesApi.reject(id, note.trim() || undefined),
    onSuccess: (change) => {
      invalidate();
      setDecision(null);
      setComment("");
      setSelected((current) => (current?.id === change.id ? change : current));
      dispatch(showToast({ message: "Change request rejected", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => changesApi.cancel(id),
    onSuccess: () => {
      invalidate();
      setSelected(null);
      dispatch(showToast({ message: "Change request cancelled", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      changesApi.create({
        title: form.title.trim(),
        description: form.description.trim() || null,
        type: form.type,
        priority: form.priority,
        environment: (form.environment || null) as Environment | null,
        required_approvals: form.required_approvals,
        payload: {},
      }),
    onSuccess: (change) => {
      invalidate();
      setCreateOpen(false);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(showToast({ message: `Change request ${change.title} opened`, severity: "success" }));
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const approvalStats = (change: ChangeRequest) => {
    const approvals = (change.approvals ?? []) as ApprovalEntry[];
    const approved = approvals.filter((entry) => entry.decision === "approved").length;
    const rejected = approvals.filter((entry) => entry.decision === "rejected").length;
    return {
      approvals,
      approved,
      rejected,
      required: change.required_approvals,
      progress: Math.min(100, (approved / Math.max(1, change.required_approvals)) * 100),
    };
  };

  const columns: Array<DataTableColumn<ChangeRequest>> = [
    {
      key: "title",
      label: "Change request",
      render: (row) => (
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" fontWeight={600} noWrap>
            {row.title}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap display="block">
            {titleCase(row.type)}
            {row.description ? ` · ${row.description}` : ""}
          </Typography>
        </Box>
      ),
    },
    {
      key: "status",
      label: "Status",
      width: 120,
      render: (row) => <StatusChip status={row.status} />,
    },
    {
      key: "priority",
      label: "Priority",
      width: 110,
      hideBelow: "md",
      render: (row) => (
        <Chip
          size="small"
          variant="outlined"
          color={PRIORITY_COLORS[row.priority] ?? "default"}
          label={titleCase(row.priority)}
        />
      ),
    },
    {
      key: "approvals",
      label: "Approvals",
      width: 170,
      hideBelow: "md",
      render: (row) => {
        const stats = approvalStats(row);
        return (
          <Box>
            <Stack direction="row" justifyContent="space-between">
              <Typography variant="caption" color="text.secondary">
                {stats.approved}/{stats.required}
              </Typography>
              {stats.rejected > 0 && (
                <Typography variant="caption" color="error.main">
                  {stats.rejected} rejected
                </Typography>
              )}
            </Stack>
            <LinearProgress
              variant="determinate"
              value={stats.progress}
              color={stats.approved >= stats.required ? "success" : "primary"}
              sx={{ height: 5, borderRadius: 3, mt: 0.5 }}
            />
          </Box>
        );
      },
    },
    {
      key: "environment",
      label: "Environment",
      width: 130,
      hideBelow: "lg",
      render: (row) => (row.environment ? <Chip size="small" variant="outlined" label={row.environment} /> : EMPTY),
    },
    {
      key: "expires_at",
      label: "Expires",
      width: 140,
      hideBelow: "lg",
      render: (row) => (
        <Tooltip title={formatDateTime(row.expires_at)}>
          <Typography variant="body2" color="text.secondary">
            {row.expires_at ? fromNow(row.expires_at) : EMPTY}
          </Typography>
        </Tooltip>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 150,
      render: (row) => {
        const pending = row.status === "pending" || row.status === "approved";
        const ownRequest = Boolean(currentUser?.id) && row.requested_by === currentUser?.id;
        return (
          <Stack direction="row" spacing={0.25} justifyContent="flex-end">
            <Tooltip title="Details">
              <Button
                size="small"
                onClick={(event) => {
                  event.stopPropagation();
                  setSelected(row);
                }}
                sx={{ minWidth: 0, px: 0.75 }}
              >
                <VisibilityOutlinedIcon fontSize="small" />
              </Button>
            </Tooltip>
            {pending && (
              <PermissionGate permission="change:approve">
                <Tooltip
                  title={ownRequest ? "Four-eyes principle: you cannot approve your own change" : "Approve"}
                >
                  <span>
                    <Button
                      size="small"
                      color="success"
                      disabled={ownRequest}
                      onClick={(event) => {
                        event.stopPropagation();
                        setComment("");
                        setDecision({ change: row, mode: "approve" });
                      }}
                      sx={{ minWidth: 0, px: 0.75 }}
                    >
                      <CheckCircleOutlineIcon fontSize="small" />
                    </Button>
                  </span>
                </Tooltip>
                <Tooltip title="Reject">
                  <Button
                    size="small"
                    color="error"
                    onClick={(event) => {
                      event.stopPropagation();
                      setComment("");
                      setDecision({ change: row, mode: "reject" });
                    }}
                    sx={{ minWidth: 0, px: 0.75 }}
                  >
                    <HighlightOffOutlinedIcon fontSize="small" />
                  </Button>
                </Tooltip>
              </PermissionGate>
            )}
            {pending && (
              <PermissionGate permission="change:write">
                <Tooltip title="Cancel">
                  <Button
                    size="small"
                    color="inherit"
                    disabled={cancelMutation.isPending}
                    onClick={(event) => {
                      event.stopPropagation();
                      cancelMutation.mutate(row.id);
                    }}
                    sx={{ minWidth: 0, px: 0.75 }}
                  >
                    <CancelOutlinedIcon fontSize="small" />
                  </Button>
                </Tooltip>
              </PermissionGate>
            )}
          </Stack>
        );
      },
    },
  ];

  const detailStats = selected ? approvalStats(selected) : null;

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Four-eyes approval workflow for firewall, NAT, VPN, template and policy changes."
        actions={
          <PermissionGate permission="change:write">
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => {
                setForm(EMPTY_FORM);
                setFormError(null);
                setCreateOpen(true);
              }}
            >
              New change request
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${changesQuery.data?.meta.total ?? 0} change requests`} />
            <Chip size="small" variant="outlined" label={`${status ? titleCase(status) : "All statuses"}`} />
          </Stack>
        }
      />

      <DataTable
        columns={columns}
        rows={changesQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={changesQuery.isLoading}
        error={changesQuery.error ? toApiError(changesQuery.error).message : null}
        onRetry={() => changesQuery.refetch()}
        page={page}
        size={size}
        total={changesQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        onRowClick={(row) => setSelected(row)}
        sort="created_at"
        order="desc"
        emptyTitle="No change requests"
        emptyDescription="Open a change request to route a risky configuration change through approval."
        toolbar={
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={1}
            alignItems={{ xs: "stretch", sm: "center" }}
            justifyContent="space-between"
          >
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
              <TextField
                select
                size="small"
                label="Status"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                sx={{ minWidth: 170 }}
              >
                {STATUS_FILTERS.map((option) => (
                  <MenuItem key={option.value || "all"} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                size="small"
                placeholder="Search change requests"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                sx={{ minWidth: 260 }}
              />
            </Stack>
            <Typography variant="caption" color="text.secondary">
              {changesQuery.data?.meta.total ?? 0} results
            </Typography>
          </Stack>
        }
      />

      <Dialog open={Boolean(selected)} onClose={() => setSelected(null)} maxWidth="md" fullWidth>
        {selected && detailStats && (
          <>
            <DialogTitle>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography variant="h5">{selected.title}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {titleCase(selected.type)} · requested {formatDateTime(selected.created_at)}
                  </Typography>
                </Box>
                <StatusChip status={selected.status} />
                <Chip
                  size="small"
                  variant="outlined"
                  color={PRIORITY_COLORS[selected.priority] ?? "default"}
                  label={titleCase(selected.priority)}
                />
              </Stack>
            </DialogTitle>
            <DialogContent dividers>
              <Stack spacing={2}>
                {selected.description && <Typography variant="body2">{selected.description}</Typography>}

                <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                  <Typography variant="caption" color="text.secondary">
                    Environment: {selected.environment ?? "any"}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Expires: {formatDateTime(selected.expires_at)}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Required approvals: {detailStats.required}
                  </Typography>
                  {selected.applied_at && (
                    <Typography variant="caption" color="text.secondary">
                      Applied: {formatDateTime(selected.applied_at)}
                    </Typography>
                  )}
                </Stack>

                <Box>
                  <Typography variant="overline" color="text.secondary">
                    Approval history
                  </Typography>
                  {detailStats.approvals.length === 0 ? (
                    <Alert severity="info" sx={{ mt: 0.5 }}>
                      No decisions recorded yet.
                    </Alert>
                  ) : (
                    <Stack divider={<Divider flexItem />} spacing={1} sx={{ mt: 0.5 }}>
                      {detailStats.approvals.map((entry, index) => (
                        <Stack
                          key={`${entry.user_id ?? "reviewer"}-${index}`}
                          direction={{ xs: "column", sm: "row" }}
                          spacing={1}
                          justifyContent="space-between"
                        >
                          <Box sx={{ minWidth: 0 }}>
                            <Typography variant="body2" fontWeight={600}>
                              {entry.decision === "approved" ? "Approved" : "Rejected"}
                              {entry.user_id ? ` by ${entry.user_id}` : ""}
                            </Typography>
                            {entry.comment && (
                              <Typography variant="caption" color="text.secondary">
                                {entry.comment}
                              </Typography>
                            )}
                          </Box>
                          <Typography variant="caption" color="text.disabled">
                            {formatDateTime(entry.at)}
                          </Typography>
                        </Stack>
                      ))}
                    </Stack>
                  )}
                </Box>

                <Box>
                  <Typography variant="overline" color="text.secondary">
                    Payload
                  </Typography>
                  <CodeBlock code={prettyJson(selected.payload ?? {})} language="payload.json" maxHeight={280} />
                </Box>
              </Stack>
            </DialogContent>
            <DialogActions sx={{ px: 3, py: 2 }}>
              <Button color="inherit" onClick={() => setSelected(null)}>
                Close
              </Button>
              {(selected.status === "pending" || selected.status === "approved") && (
                <PermissionGate permission="change:approve">
                  <Button
                    color="error"
                    startIcon={<HighlightOffOutlinedIcon />}
                    onClick={() => {
                      setComment("");
                      setDecision({ change: selected, mode: "reject" });
                    }}
                  >
                    Reject
                  </Button>
                  <Button
                    variant="contained"
                    color="success"
                    startIcon={<CheckCircleOutlineIcon />}
                    disabled={selected.requested_by === currentUser?.id}
                    onClick={() => {
                      setComment("");
                      setDecision({ change: selected, mode: "approve" });
                    }}
                  >
                    Approve
                  </Button>
                </PermissionGate>
              )}
            </DialogActions>
          </>
        )}
      </Dialog>

      <Dialog
        open={Boolean(decision)}
        onClose={() => setDecision(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          {decision?.mode === "approve" ? "Approve change request" : "Reject change request"}
        </DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            <Typography variant="body2">
              {decision?.change.title}
            </Typography>
            <TextField
              label="Comment"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              multiline
              minRows={3}
              helperText="Recorded in the approval history and the audit log."
              inputProps={{ maxLength: 2000 }}
              autoFocus
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button color="inherit" onClick={() => setDecision(null)}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color={decision?.mode === "approve" ? "success" : "error"}
            disabled={approveMutation.isPending || rejectMutation.isPending || !decision}
            onClick={() => {
              if (!decision) return;
              if (decision.mode === "approve") {
                approveMutation.mutate({ id: decision.change.id, note: comment });
              } else {
                rejectMutation.mutate({ id: decision.change.id, note: comment });
              }
            }}
          >
            {decision?.mode === "approve" ? "Approve" : "Reject"}
          </Button>
        </DialogActions>
      </Dialog>

      <FormDialog
        open={createOpen}
        title="New change request"
        description="Open a governed change. Approvers must be different from the requester."
        loading={createMutation.isPending}
        error={formError}
        submitLabel="Open change request"
        submitDisabled={!form.title.trim()}
        onSubmit={() => createMutation.mutate()}
        onClose={() => setCreateOpen(false)}
        maxWidth="md"
      >
        <TextField
          label="Title"
          value={form.title}
          onChange={(event) => setForm((value) => ({ ...value, title: event.target.value }))}
          required
          autoFocus
          inputProps={{ maxLength: 255 }}
        />
        <TextField
          label="Description"
          value={form.description}
          onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))}
          multiline
          minRows={2}
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Type"
            value={form.type}
            onChange={(event) => setForm((value) => ({ ...value, type: event.target.value }))}
          >
            {CHANGE_TYPES.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Priority"
            value={form.priority}
            onChange={(event) => setForm((value) => ({ ...value, priority: event.target.value }))}
          >
            {PRIORITIES.map((priority) => (
              <MenuItem key={priority} value={priority}>
                {titleCase(priority)}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Environment"
            value={form.environment}
            onChange={(event) => setForm((value) => ({ ...value, environment: event.target.value }))}
            helperText="Leave empty for environment-agnostic changes"
          >
            <MenuItem value="">Any environment</MenuItem>
            {ENVIRONMENTS.map((environment) => (
              <MenuItem key={environment.value} value={environment.value}>
                {environment.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Required approvals"
            type="number"
            value={form.required_approvals}
            onChange={(event) =>
              setForm((value) => ({
                ...value,
                required_approvals: Math.min(5, Math.max(1, Number(event.target.value) || 1)),
              }))
            }
            inputProps={{ min: 1, max: 5 }}
          />
        </Stack>
      </FormDialog>
    </>
  );
}

export default ApprovalsPage;
