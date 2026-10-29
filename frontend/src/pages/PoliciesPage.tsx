import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
  useTheme,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import RuleOutlinedIcon from "@mui/icons-material/RuleOutlined";
import CompareArrowsOutlinedIcon from "@mui/icons-material/CompareArrowsOutlined";
import RocketLaunchOutlinedIcon from "@mui/icons-material/RocketLaunchOutlined";
import TravelExploreOutlinedIcon from "@mui/icons-material/TravelExploreOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deploymentsApi, driftApi, policiesApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type {
  Deployment,
  DriftReport,
  Environment,
  Policy,
  PolicyDiff,
  PolicyKind,
  PolicyPayload,
  PolicyValidation,
} from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useDebounce } from "@/hooks/useDebounce";
import { usePermissions } from "@/hooks/usePermissions";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import {
  DEFAULT_PAGE_SIZE,
  ENVIRONMENTS,
  POLICY_KINDS,
  POLICY_STATUS_LABELS,
} from "@/utils/constants";
import { formatDateTime, fromNow, prettyJson } from "@/utils/format";

const DEFAULT_CONTENT = '{\n  "rules": []\n}';

interface PolicyFormState {
  name: string;
  kind: PolicyKind;
  environment: Environment;
  description: string;
  content: string;
  target_selector: string;
}

const EMPTY_FORM: PolicyFormState = {
  name: "",
  kind: "firewall",
  environment: "development",
  description: "",
  content: DEFAULT_CONTENT,
  target_selector: "{}",
};

interface SimulateFormState {
  source_ip: string;
  destination_ip: string;
  protocol: string;
  destination_port: string;
  interface: string;
}

const EMPTY_SIMULATE: SimulateFormState = {
  source_ip: "10.0.0.10",
  destination_ip: "8.8.8.8",
  protocol: "tcp",
  destination_port: "443",
  interface: "",
};

export function PoliciesPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();
  const theme = useTheme();
  const { can } = usePermissions();
  const [params] = useSearchParams();
  const initialTab = params.get("tab") === "drift" ? 1 : params.get("tab") === "deployments" ? 2 : 0;
  const [tab, setTab] = useState(initialTab);

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [sort, setSort] = useState("updated_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [search, setSearch] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [envFilter, setEnvFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);

  const [driftPage, setDriftPage] = useState(1);
  const [driftSize, setDriftSize] = useState(DEFAULT_PAGE_SIZE);
  const [deploymentPage, setDeploymentPage] = useState(1);
  const [deploymentSize, setDeploymentSize] = useState(DEFAULT_PAGE_SIZE);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Policy | null>(null);
  const [form, setForm] = useState<PolicyFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Policy | null>(null);

  const [actionAnchor, setActionAnchor] = useState<HTMLElement | null>(null);
  const [actionPolicy, setActionPolicy] = useState<Policy | null>(null);

  const [validation, setValidation] = useState<PolicyValidation | null>(null);
  const [validationPolicy, setValidationPolicy] = useState<Policy | null>(null);
  const [diffPolicy, setDiffPolicy] = useState<Policy | null>(null);
  const [deployPolicy, setDeployPolicy] = useState<Policy | null>(null);
  const [deployDryRun, setDeployDryRun] = useState(true);
  const [deployError, setDeployError] = useState<string | null>(null);

  const [simulatePolicy, setSimulatePolicy] = useState<Policy | null>(null);
  const [simulateForm, setSimulateForm] = useState<SimulateFormState>(EMPTY_SIMULATE);
  const [simulateResult, setSimulateResult] = useState<Record<string, unknown> | null>(null);
  const [simulateError, setSimulateError] = useState<string | null>(null);

  const [promotePolicy, setPromotePolicy] = useState<Policy | null>(null);
  const [promoteTarget, setPromoteTarget] = useState<Environment>("staging");
  const [promoteChangeRequest, setPromoteChangeRequest] = useState(true);
  const [promoteError, setPromoteError] = useState<string | null>(null);

  const [driftScanOpen, setDriftScanOpen] = useState(false);
  const [driftResolveTarget, setDriftResolveTarget] = useState<DriftReport | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<Deployment | null>(null);

  const listParams = useMemo(
    () => ({
      page,
      size,
      sort,
      order,
      search: debouncedSearch || undefined,
      kind: kindFilter || undefined,
      environment: (envFilter || undefined) as Environment | undefined,
      status: statusFilter || undefined,
    }),
    [page, size, sort, order, debouncedSearch, kindFilter, envFilter, statusFilter],
  );

  const policiesQuery = useQuery({
    queryKey: qk.policies.list(listParams),
    queryFn: () => policiesApi.list(listParams),
  });

  const driftQuery = useQuery({
    queryKey: qk.drift.list({ page: driftPage, size: driftSize }),
    queryFn: () => driftApi.list({ page: driftPage, size: driftSize }),
    enabled: tab === 1,
  });

  const deploymentsQuery = useQuery({
    queryKey: qk.deployments.list({ page: deploymentPage, size: deploymentSize }),
    queryFn: () => deploymentsApi.list({ page: deploymentPage, size: deploymentSize }),
    enabled: tab === 2,
  });

  const diffQuery = useQuery({
    queryKey: qk.policies.diff(diffPolicy?.id ?? ""),
    queryFn: () => policiesApi.diff(diffPolicy?.id ?? ""),
    enabled: Boolean(diffPolicy),
  });

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, kindFilter, envFilter, statusFilter]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.policies.all });
    void queryClient.invalidateQueries({ queryKey: qk.drift.all });
    void queryClient.invalidateQueries({ queryKey: qk.deployments.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const saveMutation = useMutation({
    mutationFn: (payload: PolicyPayload | Partial<PolicyPayload>) => {
      if (editing) return policiesApi.update(editing.id, payload);
      return policiesApi.create(payload as PolicyPayload);
    },
    onSuccess: (policy) => {
      invalidate();
      setFormOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(showToast({ message: `Policy ${policy.name} saved`, severity: "success" }));
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => policiesApi.remove(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Policy deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const validateMutation = useMutation({
    mutationFn: (policy: Policy) => policiesApi.validate(policy.id),
    onSuccess: (result, policy) => {
      setValidation(result);
      setValidationPolicy(policy);
      setActionAnchor(null);
      invalidate();
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const deployMutation = useMutation({
    mutationFn: (policy: Policy) =>
      policiesApi.deploy(policy.id, { dry_run: deployDryRun, device_ids: [] }),
    onSuccess: (deployment) => {
      invalidate();
      setDeployPolicy(null);
      setDeployError(null);
      dispatch(
        showToast({
          message: `Deployment ${deployment.status} (${deployment.target_device_ids.length} device(s))`,
          severity: deployment.status === "failed" ? "error" : "success",
        }),
      );
    },
    onError: (error) => setDeployError(toApiError(error).message),
  });

  const simulateMutation = useMutation({
    mutationFn: (policy: Policy) =>
      policiesApi.simulate(policy.id, {
        source_ip: simulateForm.source_ip.trim(),
        destination_ip: simulateForm.destination_ip.trim(),
        protocol: simulateForm.protocol,
        destination_port: simulateForm.destination_port ? Number(simulateForm.destination_port) : null,
        interface: simulateForm.interface.trim() || null,
      }),
    onSuccess: (result) => {
      setSimulateResult(result);
      setSimulateError(null);
    },
    onError: (error) => setSimulateError(toApiError(error).message),
  });

  const promoteMutation = useMutation({
    mutationFn: (policy: Policy) =>
      policiesApi.promote(policy.id, {
        source_environment: policy.environment,
        target_environment: promoteTarget,
        create_change_request: promoteChangeRequest,
      }),
    onSuccess: () => {
      invalidate();
      setPromotePolicy(null);
      setPromoteError(null);
      dispatch(showToast({ message: "Policy promotion initiated", severity: "success" }));
    },
    onError: (error) => setPromoteError(toApiError(error).message),
  });

  const driftScanMutation = useMutation({
    mutationFn: () => driftApi.scan([]),
    onSuccess: (result) => {
      setDriftScanOpen(false);
      invalidate();
      dispatch(
        showToast({ message: `Drift scan finished: ${result.scanned} device(s) evaluated`, severity: "success" }),
      );
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const resolveDriftMutation = useMutation({
    mutationFn: (id: string) => driftApi.resolve(id),
    onSuccess: () => {
      invalidate();
      setDriftResolveTarget(null);
      dispatch(showToast({ message: "Drift report marked remediated", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const rollbackMutation = useMutation({
    mutationFn: (id: string) => deploymentsApi.rollback(id),
    onSuccess: () => {
      invalidate();
      setRollbackTarget(null);
      dispatch(showToast({ message: "Deployment rolled back", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = (policy: Policy) => {
    setEditing(policy);
    setForm({
      name: policy.name,
      kind: policy.kind,
      environment: policy.environment,
      description: policy.description ?? "",
      content: policy.content,
      target_selector: prettyJson(policy.target_selector ?? {}),
    });
    setFormError(null);
    setActionAnchor(null);
    setFormOpen(true);
  };

  const submitForm = () => {
    let selector: Record<string, unknown>;
    try {
      selector = form.target_selector.trim() ? (JSON.parse(form.target_selector) as Record<string, unknown>) : {};
    } catch {
      setFormError("Target selector must be valid JSON.");
      return;
    }

    if (editing) {
      saveMutation.mutate({
        description: form.description.trim() || null,
        content: form.content,
        target_selector: selector,
      });
      return;
    }

    saveMutation.mutate({
      name: form.name.trim(),
      kind: form.kind,
      environment: form.environment,
      description: form.description.trim() || null,
      content: form.content,
      target_selector: selector,
    });
  };

  const openActionMenu = (event: MouseEvent<HTMLElement>, policy: Policy) => {
    setActionAnchor(event.currentTarget);
    setActionPolicy(policy);
  };

  const closeActionMenu = () => {
    setActionAnchor(null);
    setActionPolicy(null);
  };

  const policyColumns: Array<DataTableColumn<Policy>> = [
    {
      key: "name",
      label: "Policy",
      sortable: true,
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.name}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {row.description ?? row.path ?? "No description"}
          </Typography>
        </Box>
      ),
    },
    {
      key: "kind",
      label: "Kind",
      width: 120,
      render: (row) => <Chip size="small" variant="outlined" label={row.kind} />,
    },
    {
      key: "environment",
      label: "Environment",
      width: 140,
      render: (row) => <Chip size="small" label={row.environment} />,
    },
    { key: "status", label: "Status", width: 130, render: (row) => <StatusChip status={row.status} /> },
    {
      key: "version",
      label: "Version",
      width: 90,
      align: "center",
      sortable: true,
      render: (row) => `v${row.version}`,
    },
    {
      key: "updated_at",
      label: "Updated",
      width: 150,
      hideBelow: "md",
      sortable: true,
      render: (row) => (
        <Tooltip title={formatDateTime(row.updated_at)}>
          <span>{fromNow(row.updated_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 160,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="policy:validate">
            <Tooltip title="Validate policy">
              <IconButton
                size="small"
                onClick={(event) => {
                  event.stopPropagation();
                  validateMutation.mutate(row);
                }}
                disabled={validateMutation.isPending}
              >
                <RuleOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="policy:deploy">
            <Tooltip title="Deploy">
              <IconButton
                size="small"
                onClick={(event) => {
                  event.stopPropagation();
                  setDeployPolicy(row);
                  setDeployDryRun(true);
                  setDeployError(null);
                }}
              >
                <RocketLaunchOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <Tooltip title="More actions">
            <IconButton
              size="small"
              onClick={(event) => {
                event.stopPropagation();
                openActionMenu(event, row);
              }}
            >
              <MoreVertIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      ),
    },
  ];

  const driftColumns: Array<DataTableColumn<DriftReport>> = [
    {
      key: "device_id",
      label: "Device",
      render: (row) => (
        <Typography variant="body2" fontFamily="monospace">
          {row.device_id.slice(0, 8)}
        </Typography>
      ),
    },
    {
      key: "policy",
      label: "Policy",
      render: (row) => (row.policy_id ? row.policy_id.slice(0, 8) : "All policies"),
    },
    { key: "status", label: "Status", width: 130, render: (row) => <StatusChip status={row.status} /> },
    {
      key: "differences",
      label: "Differences",
      width: 130,
      align: "center",
      render: (row) => <Chip size="small" label={row.differences.length} variant="outlined" />,
    },
    {
      key: "detected",
      label: "Detected",
      width: 170,
      render: (row) => (
        <Tooltip title={formatDateTime(row.detected_at)}>
          <span>{fromNow(row.detected_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: "resolved",
      label: "Resolved",
      width: 150,
      hideBelow: "md",
      render: (row) => formatDateTime(row.resolved_at),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 100,
      render: (row) =>
        row.status === "open" ? (
          <PermissionGate permission="policy:write">
            <Button size="small" onClick={() => setDriftResolveTarget(row)}>
              Resolve
            </Button>
          </PermissionGate>
        ) : null,
    },
  ];

  const deploymentColumns: Array<DataTableColumn<Deployment>> = [
    {
      key: "policy_id",
      label: "Policy",
      render: (row) => (
        <Typography variant="body2" fontFamily="monospace">
          {row.policy_id.slice(0, 8)}
        </Typography>
      ),
    },
    { key: "environment", label: "Environment", width: 130, render: (row) => <Chip size="small" label={row.environment} /> },
    { key: "status", label: "Status", width: 140, render: (row) => <StatusChip status={row.status} /> },
    {
      key: "targets",
      label: "Targets",
      width: 100,
      align: "center",
      render: (row) => row.target_device_ids.length,
    },
    {
      key: "commit",
      label: "Commit",
      width: 120,
      hideBelow: "md",
      monospace: true,
      render: (row) => (row.commit_sha ? row.commit_sha.slice(0, 8) : "—"),
    },
    {
      key: "started",
      label: "Started",
      width: 170,
      render: (row) => (row.started_at ? fromNow(row.started_at) : formatDateTime(row.created_at)),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 100,
      render: (row) =>
        row.status === "completed" ? (
          <PermissionGate permission="policy:rollback">
            <Button size="small" color="warning" onClick={() => setRollbackTarget(row)}>
              Rollback
            </Button>
          </PermissionGate>
        ) : null,
    },
  ];

  const actionMenu = (
    <Menu anchorEl={actionAnchor} open={Boolean(actionAnchor)} onClose={closeActionMenu}>
      <MenuItem
        disabled={!actionPolicy}
        onClick={() => {
          if (!actionPolicy) return;
          setDiffPolicy(actionPolicy);
          closeActionMenu();
        }}
      >
        <ListItemIcon>
          <CompareArrowsOutlinedIcon fontSize="small" />
        </ListItemIcon>
        <ListItemText primary="Compare with deployed version" />
      </MenuItem>
      <MenuItem
        disabled={!actionPolicy}
        onClick={() => {
          if (!actionPolicy) return;
          setSimulatePolicy(actionPolicy);
          setSimulateForm(EMPTY_SIMULATE);
          setSimulateResult(null);
          setSimulateError(null);
          closeActionMenu();
        }}
      >
        <ListItemIcon>
          <TravelExploreOutlinedIcon fontSize="small" />
        </ListItemIcon>
        <ListItemText primary="Simulate rule match" />
      </MenuItem>
      <MenuItem
        disabled={!actionPolicy || actionPolicy.environment === "production"}
        onClick={() => {
          if (!actionPolicy) return;
          const next: Environment =
            actionPolicy.environment === "development"
              ? "staging"
              : actionPolicy.environment === "testing"
                ? "staging"
                : "production";
          setPromotePolicy(actionPolicy);
          setPromoteTarget(next);
          setPromoteChangeRequest(true);
          setPromoteError(null);
          closeActionMenu();
        }}
      >
        <ListItemIcon>
          <PlayArrowIcon fontSize="small" />
        </ListItemIcon>
        <ListItemText primary="Promote to environment" />
      </MenuItem>
      {can("policy:write") && (
        <MenuItem
          disabled={!actionPolicy}
          onClick={() => {
            if (actionPolicy) openEdit(actionPolicy);
          }}
        >
          <ListItemIcon>
            <EditOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText primary="Edit policy" />
        </MenuItem>
      )}
      {can("policy:write") && (
        <MenuItem
          disabled={!actionPolicy}
          onClick={() => {
            setDeleteTarget(actionPolicy);
            closeActionMenu();
          }}
        >
          <ListItemIcon>
            <DeleteOutlineIcon fontSize="small" color="error" />
          </ListItemIcon>
          <ListItemText primary="Delete policy" primaryTypographyProps={{ color: "error" }} />
        </MenuItem>
      )}
    </Menu>
  );

  return (
    <>
      <PageHeader
        title="Policies"
        subtitle="Policy-as-code definitions, validation, approval, deployment and drift across environments."
        actions={
          <>
            <PermissionGate permission="policy:read">
              <Button variant="outlined" startIcon={<TravelExploreOutlinedIcon />} onClick={() => setDriftScanOpen(true)}>
                Scan drift
              </Button>
            </PermissionGate>
            <PermissionGate permission="policy:write">
              <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
                New policy
              </Button>
            </PermissionGate>
          </>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <Chip size="small" label={`${policiesQuery.data?.meta.total ?? 0} policies`} />
            <Chip
              size="small"
              variant="outlined"
              color="warning"
              label={`${driftQuery.data?.meta.total ?? 0} drift reports`}
            />
          </Stack>
        }
      />

      <Tabs value={tab} onChange={(_event, value: number) => setTab(value)} sx={{ mb: 2 }}>
        <Tab label="Policies" />
        <Tab label="Drift" />
        <Tab label="Deployments" />
      </Tabs>

      {tab === 0 && (
        <DataTable
          columns={policyColumns}
          rows={policiesQuery.data?.items ?? []}
          getRowId={(row) => row.id}
          loading={policiesQuery.isLoading}
          error={policiesQuery.error ? toApiError(policiesQuery.error).message : null}
          onRetry={() => policiesQuery.refetch()}
          page={page}
          size={size}
          total={policiesQuery.data?.meta.total}
          onPageChange={setPage}
          onSizeChange={setSize}
          sort={sort}
          order={order}
          onSortChange={(key, nextOrder) => {
            setSort(key);
            setOrder(nextOrder);
          }}
          onRowClick={(row) => {
            setDiffPolicy(row);
          }}
          emptyTitle="No policies yet"
          emptyDescription="Author policy-as-code in the editor or import it from a connected Git repository."
          emptyAction={
            <PermissionGate permission="policy:write">
              <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
                New policy
              </Button>
            </PermissionGate>
          }
          toolbar={
            <Stack direction={{ xs: "column", lg: "row" }} spacing={1} justifyContent="space-between">
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap>
                <TextField
                  placeholder="Search policies"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  sx={{ width: { xs: "100%", sm: 240 } }}
                />
                <TextField
                  select
                  label="Kind"
                  value={kindFilter}
                  onChange={(event) => setKindFilter(event.target.value)}
                  sx={{ width: { xs: "100%", sm: 140 } }}
                >
                  <MenuItem value="">All</MenuItem>
                  {POLICY_KINDS.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  label="Environment"
                  value={envFilter}
                  onChange={(event) => setEnvFilter(event.target.value)}
                  sx={{ width: { xs: "100%", sm: 150 } }}
                >
                  <MenuItem value="">All</MenuItem>
                  {ENVIRONMENTS.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  label="Status"
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                  sx={{ width: { xs: "100%", sm: 140 } }}
                >
                  <MenuItem value="">All</MenuItem>
                  {Object.entries(POLICY_STATUS_LABELS).map(([value, label]) => (
                    <MenuItem key={value} value={value}>
                      {label}
                    </MenuItem>
                  ))}
                </TextField>
              </Stack>
              <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
                {policiesQuery.data?.meta.total ?? 0} policies
              </Typography>
            </Stack>
          }
        />
      )}

      {tab === 1 && (
        <DataTable
          columns={driftColumns}
          rows={driftQuery.data?.items ?? []}
          getRowId={(row) => row.id}
          loading={driftQuery.isLoading}
          error={driftQuery.error ? toApiError(driftQuery.error).message : null}
          onRetry={() => driftQuery.refetch()}
          page={driftPage}
          size={driftSize}
          total={driftQuery.data?.meta.total}
          onPageChange={setDriftPage}
          onSizeChange={setDriftSize}
          emptyTitle="No drift detected"
          emptyDescription="Drift reports appear when a device configuration no longer matches its desired policy."
          toolbar={
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Typography variant="h5">Configuration drift</Typography>
              <Button
                size="small"
                startIcon={<TravelExploreOutlinedIcon />}
                onClick={() => setDriftScanOpen(true)}
              >
                Scan now
              </Button>
            </Stack>
          }
        />
      )}

      {tab === 2 && (
        <DataTable
          columns={deploymentColumns}
          rows={deploymentsQuery.data?.items ?? []}
          getRowId={(row) => row.id}
          loading={deploymentsQuery.isLoading}
          error={deploymentsQuery.error ? toApiError(deploymentsQuery.error).message : null}
          onRetry={() => deploymentsQuery.refetch()}
          page={deploymentPage}
          size={deploymentSize}
          total={deploymentsQuery.data?.meta.total}
          onPageChange={setDeploymentPage}
          onSizeChange={setDeploymentSize}
          emptyTitle="No deployments"
          emptyDescription="Deploy a validated policy to see its execution history here."
          toolbar={
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Typography variant="h5">Deployment history</Typography>
              <Typography variant="caption" color="text.secondary">
                Rollback applies the previous known-good revision
              </Typography>
            </Stack>
          }
        />
      )}

      {actionMenu}

      <FormDialog
        open={formOpen}
        title={editing ? `Edit ${editing.name}` : "New policy"}
        description={
          <Typography variant="body2" color="text.secondary">
            {editing
              ? "Editing creates a new policy version. Validation and deployment are required before the change reaches devices."
              : "Policies are versioned on save. Use JSON or YAML supported by the compiler; validation runs before any deployment."}
          </Typography>
        }
        submitLabel={editing ? "Save new version" : "Create policy"}
        loading={saveMutation.isPending}
        error={formError}
        submitDisabled={!form.name.trim() || !form.content.trim()}
        onSubmit={submitForm}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        maxWidth="lg"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Name"
            value={form.name}
            onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
            required
            disabled={Boolean(editing)}
            autoFocus
          />
          <TextField
            select
            label="Kind"
            value={form.kind}
            onChange={(event) => setForm((value) => ({ ...value, kind: event.target.value as PolicyKind }))}
            disabled={Boolean(editing)}
          >
            {POLICY_KINDS.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Environment"
            value={form.environment}
            onChange={(event) =>
              setForm((value) => ({ ...value, environment: event.target.value as Environment }))
            }
            disabled={Boolean(editing)}
          >
            {ENVIRONMENTS.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <TextField
          label="Description"
          value={form.description}
          onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))}
        />
        <TextField
          label="Policy content"
          value={form.content}
          onChange={(event) => setForm((value) => ({ ...value, content: event.target.value }))}
          multiline
          minRows={14}
          required
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 12.5, lineHeight: 1.55 },
          }}
        />
        <TextField
          label="Target selector (JSON)"
          value={form.target_selector}
          onChange={(event) => setForm((value) => ({ ...value, target_selector: event.target.value }))}
          multiline
          minRows={4}
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 12.5 },
          }}
          helperText='Examples: {"all": true}, {"site_ids": ["…"]}, {"group_ids": ["…"]}, {"tags": ["branch"]}'
        />
      </FormDialog>

      <FormDialog
        open={Boolean(validation) && Boolean(validationPolicy)}
        title={validation?.valid ? "Policy is valid" : "Validation failed"}
        submitLabel="Close"
        onSubmit={() => {
          setValidation(null);
          setValidationPolicy(null);
        }}
        onClose={() => {
          setValidation(null);
          setValidationPolicy(null);
        }}
        maxWidth="md"
      >
        {validation && (
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip
                color={validation.valid ? "success" : "error"}
                label={validation.valid ? "Valid" : "Invalid"}
              />
              <Chip variant="outlined" label={`${validation.rule_count} rules`} />
              <Chip
                variant="outlined"
                color={validation.conflict_count > 0 ? "warning" : "default"}
                label={`${validation.conflict_count} conflicts`}
              />
              <Chip variant="outlined" label={validationPolicy?.name ?? ""} />
            </Stack>
            {validation.errors.length > 0 && (
              <Alert severity="error">
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                  Errors
                </Typography>
                {validation.errors.map((issue, index) => (
                  <Typography variant="body2" key={`${issue.code}-${index}`} component="div">
                    <strong>{issue.code}</strong>: {issue.message}
                    {issue.path ? ` (${issue.path}${issue.line ? `:${issue.line}` : ""})` : ""}
                  </Typography>
                ))}
              </Alert>
            )}
            {validation.warnings.length > 0 && (
              <Alert severity="warning">
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                  Warnings
                </Typography>
                {validation.warnings.map((issue, index) => (
                  <Typography variant="body2" key={`${issue.code}-${index}`} component="div">
                    <strong>{issue.code}</strong>: {issue.message}
                  </Typography>
                ))}
              </Alert>
            )}
            {validation.compiled && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  Compiled output
                </Typography>
                <CodeBlock code={prettyJson(validation.compiled)} language="json" maxHeight={300} />
              </Box>
            )}
          </Stack>
        )}
      </FormDialog>

      <FormDialog
        open={Boolean(diffPolicy)}
        title={`Diff · ${diffPolicy?.name ?? ""}`}
        submitLabel="Close"
        onSubmit={() => setDiffPolicy(null)}
        onClose={() => setDiffPolicy(null)}
        maxWidth="md"
      >
        {diffQuery.isLoading && <Typography variant="body2">Loading diff…</Typography>}
        {diffQuery.isError && <Alert severity="error">{toApiError(diffQuery.error).message}</Alert>}
        {diffQuery.data && <DiffView diff={diffQuery.data} />}
      </FormDialog>

      <FormDialog
        open={Boolean(deployPolicy)}
        title={`Deploy ${deployPolicy?.name ?? ""}`}
        description={
          <Typography variant="body2" color="text.secondary">
            The deployment service compiles the policy, batches changes per device, commits to the audit
            trail and records the plan. A dry run validates the plan without touching appliances.
          </Typography>
        }
        submitLabel={deployDryRun ? "Run dry run" : "Deploy now"}
        loading={deployMutation.isPending}
        error={deployError}
        submitDisabled={!deployPolicy}
        onSubmit={() => deployPolicy && deployMutation.mutate(deployPolicy)}
        onClose={() => setDeployPolicy(null)}
        maxWidth="sm"
      >
        <FormControlLabel
          control={
            <Checkbox checked={deployDryRun} onChange={(event) => setDeployDryRun(event.target.checked)} />
          }
          label="Dry run (validate the plan, do not apply)"
        />
        {deployPolicy?.status === "draft" && (
          <Alert severity="warning">
            This policy is still a draft. Validate it before deploying so the compiler can report conflicts.
          </Alert>
        )}
        {deployPolicy && (
          <Box sx={{ p: 1.5, border: 1, borderColor: "divider", borderRadius: 1.5 }}>
            <Typography variant="caption" color="text.secondary">
              Environment: {deployPolicy.environment} · v{deployPolicy.version} · selector{" "}
              {prettyJson(deployPolicy.target_selector)}
            </Typography>
          </Box>
        )}
      </FormDialog>

      <FormDialog
        open={Boolean(simulatePolicy)}
        title={`Simulate · ${simulatePolicy?.name ?? ""}`}
        submitLabel="Run simulation"
        loading={simulateMutation.isPending}
        error={simulateError}
        submitDisabled={!simulateForm.source_ip.trim() || !simulateForm.destination_ip.trim()}
        onSubmit={() => simulatePolicy && simulateMutation.mutate(simulatePolicy)}
        onClose={() => setSimulatePolicy(null)}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Source IP"
            value={simulateForm.source_ip}
            onChange={(event) => setSimulateForm((value) => ({ ...value, source_ip: event.target.value }))}
            required
          />
          <TextField
            label="Destination IP"
            value={simulateForm.destination_ip}
            onChange={(event) =>
              setSimulateForm((value) => ({ ...value, destination_ip: event.target.value }))
            }
            required
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Protocol"
            value={simulateForm.protocol}
            onChange={(event) => setSimulateForm((value) => ({ ...value, protocol: event.target.value }))}
          >
            <MenuItem value="tcp">TCP</MenuItem>
            <MenuItem value="udp">UDP</MenuItem>
            <MenuItem value="icmp">ICMP</MenuItem>
            <MenuItem value="any">Any</MenuItem>
          </TextField>
          <TextField
            label="Destination port"
            value={simulateForm.destination_port}
            onChange={(event) =>
              setSimulateForm((value) => ({ ...value, destination_port: event.target.value }))
            }
            inputProps={{ inputMode: "numeric" }}
          />
          <TextField
            label="Interface"
            value={simulateForm.interface}
            onChange={(event) => setSimulateForm((value) => ({ ...value, interface: event.target.value }))}
            placeholder="wan"
          />
        </Stack>
        {simulateResult && <CodeBlock code={prettyJson(simulateResult)} language="json" maxHeight={280} />}
      </FormDialog>

      <FormDialog
        open={Boolean(promotePolicy)}
        title={`Promote ${promotePolicy?.name ?? ""}`}
        description={
          <Typography variant="body2" color="text.secondary">
            Promotion copies the current content to the target environment. Creating a change request routes
            it through the approval workflow before deployment.
          </Typography>
        }
        submitLabel="Promote"
        loading={promoteMutation.isPending}
        error={promoteError}
        submitDisabled={!promotePolicy || promotePolicy.environment === promoteTarget}
        onSubmit={() => promotePolicy && promoteMutation.mutate(promotePolicy)}
        onClose={() => setPromotePolicy(null)}
      >
        <TextField
          label="Source environment"
          value={promotePolicy?.environment ?? ""}
          disabled
          helperText="The source environment is fixed by the policy revision"
        />
        <TextField
          select
          label="Target environment"
          value={promoteTarget}
          onChange={(event) => setPromoteTarget(event.target.value as Environment)}
        >
          {ENVIRONMENTS.map((option) => (
            <MenuItem key={option.value} value={option.value}>
              {option.label}
            </MenuItem>
          ))}
        </TextField>
        <FormControlLabel
          control={
            <Checkbox
              checked={promoteChangeRequest}
              onChange={(event) => setPromoteChangeRequest(event.target.checked)}
            />
          }
          label="Create a change request for approval"
        />
      </FormDialog>

      <ConfirmDialog
        open={driftScanOpen}
        title="Scan for configuration drift"
        description="Compares the running configuration of every device against the deployed policies. The scan runs in the background and can take several minutes on large fleets."
        confirmLabel="Start scan"
        loading={driftScanMutation.isPending}
        onConfirm={() => driftScanMutation.mutate()}
        onClose={() => setDriftScanOpen(false)}
      />

      <ConfirmDialog
        open={Boolean(driftResolveTarget)}
        title="Resolve drift report"
        description={
          driftResolveTarget
            ? `Mark the drift on device ${driftResolveTarget.device_id.slice(0, 8)} as remediated? Audit records retain the original differences.`
            : undefined
        }
        confirmLabel="Mark remediated"
        loading={resolveDriftMutation.isPending}
        onConfirm={() => driftResolveTarget && resolveDriftMutation.mutate(driftResolveTarget.id)}
        onClose={() => setDriftResolveTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(rollbackTarget)}
        title="Roll back deployment"
        description="Rolling back restores the previous known-good configuration on every target device. The action is audited and cannot be undone automatically."
        confirmLabel="Roll back"
        confirmColor="warning"
        loading={rollbackMutation.isPending}
        onConfirm={() => rollbackTarget && rollbackMutation.mutate(rollbackTarget.id)}
        onClose={() => setRollbackTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete policy"
        description={
          deleteTarget
            ? `Delete ${deleteTarget.name}? Deployment history and audit records are retained, but the policy is removed from GitOps synchronisation.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onClose={() => setDeleteTarget(null)}
      />

      <Box sx={{ mt: 2 }}>
        <Alert severity="info" variant="outlined" sx={{ bgcolor: theme.palette.background.paper }}>
          Policy changes are validated, versioned and audited. Approval rules and protected environments are
          configured in Settings → Change management.
        </Alert>
      </Box>
    </>
  );
}

function DiffView({ diff }: { diff: PolicyDiff }) {
  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Chip size="small" label={`base v${diff.base_version}`} />
        <Chip size="small" color="info" label={`target v${diff.target_version}`} />
        <Chip size="small" variant="outlined" label={`${diff.entries.length} changes`} />
      </Stack>
      <Typography variant="body2" color="text.secondary">
        {diff.summary}
      </Typography>
      {diff.entries.length === 0 ? (
        <Alert severity="success">No differences between the selected versions.</Alert>
      ) : (
        <Stack spacing={1}>
          {diff.entries.map((entry, index) => (
            <Box
              key={`${entry.path}-${index}`}
              sx={{ border: 1, borderColor: "divider", borderRadius: 1.5, p: 1.5 }}
            >
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="body2" fontWeight={600} fontFamily="monospace">
                  {entry.path}
                </Typography>
                <Chip size="small" label={entry.change} />
              </Stack>
              <Box sx={{ display: "grid", gap: 1, gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, mt: 1 }}>
                <Box>
                  <Typography variant="overline" color="text.secondary">
                    Before
                  </Typography>
                  <CodeBlock code={prettyJson(entry.before)} maxHeight={180} showCopy={false} />
                </Box>
                <Box>
                  <Typography variant="overline" color="text.secondary">
                    After
                  </Typography>
                  <CodeBlock code={prettyJson(entry.after)} maxHeight={180} showCopy={false} />
                </Box>
              </Box>
            </Box>
          ))}
        </Stack>
      )}
    </Stack>
  );
}

export default PoliciesPage;
