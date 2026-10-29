import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  LinearProgress,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CancelOutlinedIcon from "@mui/icons-material/CancelOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import ReplayOutlinedIcon from "@mui/icons-material/ReplayOutlined";
import ScheduleOutlinedIcon from "@mui/icons-material/ScheduleOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { jobsApi, tasksApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type {
  Job,
  JobPayload,
  JobStatus,
  ScheduledTask,
  ScheduledTaskPayload,
  TaskKind,
} from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import StatusChip from "@/components/StatusChip";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import {
  CRON_PRESETS,
  DEFAULT_PAGE_SIZE,
  JOB_STATUS_LABELS,
  TASK_KINDS,
} from "@/utils/constants";
import { formatDateTime, fromNow, prettyJson } from "@/utils/format";

const TASK_NAMES: Array<{ value: string; label: string; description: string }> = [
  {
    value: "ofme.backups.run_scheduled",
    label: "Back up fleet",
    description: "Configuration backup for every manageable device",
  },
  {
    value: "ofme.backups.create",
    label: "Back up one device",
    description: "Single-device backup; params.device_id is required",
  },
  {
    value: "ofme.compliance.run",
    label: "Compliance assessment",
    description: "Evaluate the fleet against a framework",
  },
  {
    value: "ofme.policies.drift_scan",
    label: "Drift scan",
    description: "Compare running configuration against deployed policy",
  },
  {
    value: "ofme.policies.deploy",
    label: "Policy deployment",
    description: "Deploy a validated policy revision",
  },
  {
    value: "ofme.monitoring.collect",
    label: "Collect telemetry",
    description: "Poll the agent for a fresh metric snapshot",
  },
  {
    value: "ofme.monitoring.heartbeat_timeout",
    label: "Heartbeat timeout sweep",
    description: "Move stale devices to offline",
  },
  {
    value: "ofme.monitoring.purge_metrics",
    label: "Purge expired metrics",
    description: "Apply the telemetry retention window",
  },
  {
    value: "ofme.devices.rotate_certificates",
    label: "Rotate certificates",
    description: "Renew certificates approaching expiry",
  },
  {
    value: "ofme.gitops.sync_repository",
    label: "Git repository sync",
    description: "Pull policy definitions from a repository",
  },
  {
    value: "ofme.sdwan.health_sweep",
    label: "SD-WAN health sweep",
    description: "Measure links and re-evaluate SLA steering",
  },
  {
    value: "ofme.tasks.custom",
    label: "Custom task",
    description: "Safe actions only: noop, echo, touch",
  },
];

const JOB_STATUSES: JobStatus[] = ["pending", "running", "completed", "failed", "cancelled"];

interface JobFormState {
  task_name: string;
  params: string;
}

const EMPTY_JOB: JobFormState = {
  task_name: "ofme.backups.run_scheduled",
  params: "{}",
};

interface TaskFormState {
  name: string;
  kind: TaskKind;
  cron: string;
  payload: string;
  enabled: boolean;
}

const EMPTY_TASK: TaskFormState = {
  name: "",
  kind: "backup",
  cron: "0 2 * * *",
  payload: "{}",
  enabled: true,
};

function progressColor(status: JobStatus): "primary" | "success" | "error" | "warning" {
  if (status === "completed") return "success";
  if (status === "failed" || status === "cancelled") return "error";
  if (status === "running") return "primary";
  return "warning";
}

export function JobsPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState(0);

  const [jobPage, setJobPage] = useState(1);
  const [jobSize, setJobSize] = useState(DEFAULT_PAGE_SIZE);
  const [statusFilter, setStatusFilter] = useState("");
  const [taskNameFilter, setTaskNameFilter] = useState("");
  const [jobFormOpen, setJobFormOpen] = useState(false);
  const [jobForm, setJobForm] = useState<JobFormState>(EMPTY_JOB);
  const [jobFormError, setJobFormError] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Job | null>(null);
  const [jobDetail, setJobDetail] = useState<Job | null>(null);

  const [taskPage, setTaskPage] = useState(1);
  const [taskSize, setTaskSize] = useState(DEFAULT_PAGE_SIZE);
  const [enabledFilter, setEnabledFilter] = useState("");
  const [taskFormOpen, setTaskFormOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<ScheduledTask | null>(null);
  const [taskForm, setTaskForm] = useState<TaskFormState>(EMPTY_TASK);
  const [taskFormError, setTaskFormError] = useState<string | null>(null);
  const [deleteTaskTarget, setDeleteTaskTarget] = useState<ScheduledTask | null>(null);
  const [runTaskTarget, setRunTaskTarget] = useState<ScheduledTask | null>(null);

  const jobParams = useMemo(
    () => ({
      page: jobPage,
      size: jobSize,
      status: statusFilter || undefined,
      task_name: taskNameFilter || undefined,
    }),
    [jobPage, jobSize, statusFilter, taskNameFilter],
  );

  const taskParams = useMemo(
    () => ({
      page: taskPage,
      size: taskSize,
      enabled: enabledFilter === "" ? undefined : enabledFilter === "true",
    }),
    [taskPage, taskSize, enabledFilter],
  );

  const jobsQuery = useQuery({
    queryKey: qk.jobs.list(jobParams),
    queryFn: () => jobsApi.list(jobParams),
    refetchInterval: tab === 0 ? 5_000 : false,
  });

  const tasksQuery = useQuery({
    queryKey: qk.tasks.list(taskParams),
    queryFn: () => tasksApi.list(taskParams),
    enabled: tab === 1,
    refetchInterval: tab === 1 ? 30_000 : false,
  });

  useEffect(() => {
    setJobPage(1);
  }, [statusFilter, taskNameFilter]);

  useEffect(() => {
    setTaskPage(1);
  }, [enabledFilter]);

  const invalidateJobs = () => {
    void queryClient.invalidateQueries({ queryKey: qk.jobs.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const invalidateTasks = () => {
    void queryClient.invalidateQueries({ queryKey: qk.tasks.all });
    void queryClient.invalidateQueries({ queryKey: qk.jobs.all });
  };

  const createJobMutation = useMutation({
    mutationFn: (payload: JobPayload) => jobsApi.create(payload),
    onSuccess: (job) => {
      invalidateJobs();
      setJobFormOpen(false);
      setJobForm(EMPTY_JOB);
      setJobFormError(null);
      dispatch(showToast({ message: `Job queued: ${job.task_name}`, severity: "success" }));
    },
    onError: (error) => setJobFormError(toApiError(error).message),
  });

  const cancelMutation = useMutation({
    mutationFn: (job: Job) => jobsApi.cancel(job.id),
    onSuccess: () => {
      invalidateJobs();
      setCancelTarget(null);
      dispatch(showToast({ message: "Job cancelled", severity: "success" }));
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const saveTaskMutation = useMutation({
    mutationFn: (payload: ScheduledTaskPayload) =>
      editingTask ? tasksApi.update(editingTask.id, payload) : tasksApi.create(payload),
    onSuccess: (task) => {
      invalidateTasks();
      setTaskFormOpen(false);
      setEditingTask(null);
      setTaskForm(EMPTY_TASK);
      setTaskFormError(null);
      dispatch(showToast({ message: `Schedule ${task.name} saved`, severity: "success" }));
    },
    onError: (error) => setTaskFormError(toApiError(error).message),
  });

  const deleteTaskMutation = useMutation({
    mutationFn: (task: ScheduledTask) => tasksApi.remove(task.id),
    onSuccess: () => {
      invalidateTasks();
      setDeleteTaskTarget(null);
      dispatch(showToast({ message: "Scheduled task deleted", severity: "success" }));
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const runTaskMutation = useMutation({
    mutationFn: (task: ScheduledTask) => tasksApi.run(task.id),
    onSuccess: (job) => {
      invalidateTasks();
      setRunTaskTarget(null);
      dispatch(showToast({ message: `Task queued as job ${job.id.slice(0, 8)}`, severity: "success" }));
    },
    onError: (error) =>
      dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const submitJob = () => {
    let params: Record<string, unknown>;
    try {
      params = jobForm.params.trim() ? (JSON.parse(jobForm.params) as Record<string, unknown>) : {};
    } catch {
      setJobFormError("Parameters must be valid JSON.");
      return;
    }
    createJobMutation.mutate({ task_name: jobForm.task_name, params });
  };

  const openCreateTask = () => {
    setEditingTask(null);
    setTaskForm(EMPTY_TASK);
    setTaskFormError(null);
    setTaskFormOpen(true);
  };

  const openEditTask = (task: ScheduledTask) => {
    setEditingTask(task);
    setTaskForm({
      name: task.name,
      kind: task.kind,
      cron: task.cron,
      payload: prettyJson(task.payload ?? {}),
      enabled: task.enabled,
    });
    setTaskFormError(null);
    setTaskFormOpen(true);
  };

  const submitTask = () => {
    let payload: Record<string, unknown>;
    try {
      payload = taskForm.payload.trim()
        ? (JSON.parse(taskForm.payload) as Record<string, unknown>)
        : {};
    } catch {
      setTaskFormError("Payload must be valid JSON.");
      return;
    }
    saveTaskMutation.mutate({
      name: taskForm.name.trim(),
      kind: taskForm.kind,
      cron: taskForm.cron.trim(),
      payload,
      enabled: taskForm.enabled,
    });
  };

  const jobColumns: Array<DataTableColumn<Job>> = [
    {
      key: "task_name",
      label: "Task",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600} fontFamily="monospace" fontSize={12.5}>
            {row.task_name}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block">
            {row.id.slice(0, 8)}
            {row.celery_task_id ? ` Â· celery ${row.celery_task_id.slice(0, 8)}` : ""}
          </Typography>
        </Box>
      ),
    },
    {
      key: "status",
      label: "Status",
      width: 130,
      render: (row) => <StatusChip status={row.status} />,
    },
    {
      key: "progress",
      label: "Progress",
      width: 150,
      hideBelow: "sm",
      render: (row) => (
        <Stack spacing={0.5}>
          <LinearProgress
            variant="determinate"
            value={Math.min(100, Math.max(0, row.progress))}
            color={progressColor(row.status)}
            sx={{ height: 6, borderRadius: 3 }}
          />
          <Typography variant="caption" color="text.secondary">
            {Math.round(row.progress)}%
          </Typography>
        </Stack>
      ),
    },
    {
      key: "created",
      label: "Queued",
      width: 160,
      hideBelow: "md",
      render: (row) => (
        <Tooltip title={formatDateTime(row.created_at)}>
          <span>{fromNow(row.created_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: "duration",
      label: "Runtime",
      width: 150,
      hideBelow: "lg",
      render: (row) => {
        if (!row.started_at) return "â€”";
        const start = new Date(row.started_at).getTime();
        const end = row.finished_at ? new Date(row.finished_at).getTime() : Date.now();
        const seconds = Math.max(0, Math.round((end - start) / 1000));
        return `${seconds}s`;
      },
    },
    {
      key: "error",
      label: "Result",
      hideBelow: "lg",
      render: (row) =>
        row.error ? (
          <Typography variant="caption" color="error" noWrap sx={{ maxWidth: 220, display: "block" }}>
            {row.error}
          </Typography>
        ) : (
          <Typography variant="caption" color="text.secondary">
            {row.result ? "completed" : "â€”"}
          </Typography>
        ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 110,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <Tooltip title="Inspect job">
            <IconButton size="small" onClick={() => setJobDetail(row)}>
              <ReplayOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          {(row.status === "pending" || row.status === "running") && (
            <PermissionGate permission="job:cancel">
              <Tooltip title="Cancel job">
                <IconButton size="small" color="error" onClick={() => setCancelTarget(row)}>
                  <CancelOutlinedIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </PermissionGate>
          )}
        </Stack>
      ),
    },
  ];

  const taskColumns: Array<DataTableColumn<ScheduledTask>> = [
    {
      key: "name",
      label: "Schedule",
      render: (row) => (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {row.name}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {TASK_KINDS.find((kind) => kind.value === row.kind)?.label ?? row.kind}
          </Typography>
        </Box>
      ),
    },
    {
      key: "cron",
      label: "Cron",
      width: 160,
      monospace: true,
      render: (row) => row.cron,
    },
    {
      key: "enabled",
      label: "State",
      width: 110,
      render: (row) => <StatusChip status={row.enabled ? "enabled" : "disabled"} />,
    },
    {
      key: "last_run",
      label: "Last run",
      width: 160,
      hideBelow: "md",
      render: (row) => (
        <Tooltip title={formatDateTime(row.last_run_at)}>
          <span>{row.last_run_at ? fromNow(row.last_run_at) : "never"}</span>
        </Tooltip>
      ),
    },
    {
      key: "next_run",
      label: "Next run",
      width: 160,
      hideBelow: "md",
      render: (row) => (
        <Tooltip title={formatDateTime(row.next_run_at)}>
          <span>{row.next_run_at ? fromNow(row.next_run_at) : "paused"}</span>
        </Tooltip>
      ),
    },
    {
      key: "payload",
      label: "Payload",
      hideBelow: "lg",
      monospace: true,
      render: (row) => prettyJson(row.payload).replace(/\s+/g, " ").slice(0, 60),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 140,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="task:write">
            <Tooltip title="Run now">
              <IconButton size="small" onClick={() => setRunTaskTarget(row)}>
                <PlayCircleOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="task:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEditTask(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="task:write">
            <Tooltip title="Delete">
              <IconButton size="small" color="error" onClick={() => setDeleteTaskTarget(row)}>
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
        title="Jobs & schedules"
        subtitle="Background work queued on Celery and tenant-owned cron schedules evaluated by the scheduler beat."
        actions={
          <>
            <PermissionGate permission="task:write">
              <Button variant="outlined" startIcon={<AddIcon />} onClick={openCreateTask}>
                New schedule
              </Button>
            </PermissionGate>
            <PermissionGate permission="task:write">
              <Button
                variant="contained"
                startIcon={<ScheduleOutlinedIcon />}
                onClick={() => {
                  setJobForm(EMPTY_JOB);
                  setJobFormError(null);
                  setJobFormOpen(true);
                }}
              >
                Run task
              </Button>
            </PermissionGate>
          </>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${jobsQuery.data?.meta.total ?? 0} jobs`} />
            <Chip size="small" variant="outlined" label={`${tasksQuery.data?.meta.total ?? 0} schedules`} />
            <Chip
              size="small"
              variant="outlined"
              color="warning"
              label={`${(jobsQuery.data?.items ?? []).filter((job) => job.status === "running").length} running on this page`}
            />
          </Stack>
        }
      />

      <Tabs value={tab} onChange={(_event, value: number) => setTab(value)} sx={{ mb: 2 }}>
        <Tab label="Jobs" />
        <Tab label="Scheduled tasks" />
      </Tabs>

      {tab === 0 && (
        <DataTable
          columns={jobColumns}
          rows={jobsQuery.data?.items ?? []}
          getRowId={(row) => row.id}
          loading={jobsQuery.isLoading}
          error={jobsQuery.error ? toApiError(jobsQuery.error).message : null}
          onRetry={() => jobsQuery.refetch()}
          page={jobPage}
          size={jobSize}
          total={jobsQuery.data?.meta.total}
          onPageChange={setJobPage}
          onSizeChange={setJobSize}
          onRowClick={(row) => setJobDetail(row)}
          emptyTitle="No background jobs"
          emptyDescription="Deployments, backups, compliance scans and scheduled tasks appear here with their progress."
          toolbar={
            <Stack
              direction={{ xs: "column", md: "row" }}
              spacing={1}
              alignItems={{ xs: "stretch", md: "center" }}
              justifyContent="space-between"
            >
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap>
                <TextField
                  select
                  label="Status"
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                  sx={{ width: { xs: "100%", sm: 160 } }}
                >
                  <MenuItem value="">All</MenuItem>
                  {JOB_STATUSES.map((status) => (
                    <MenuItem key={status} value={status}>
                      {JOB_STATUS_LABELS[status] ?? status}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  label="Task"
                  value={taskNameFilter}
                  onChange={(event) => setTaskNameFilter(event.target.value)}
                  sx={{ width: { xs: "100%", sm: 280 } }}
                >
                  <MenuItem value="">All tasks</MenuItem>
                  {TASK_NAMES.map((task) => (
                    <MenuItem key={task.value} value={task.value}>
                      {task.label}
                    </MenuItem>
                  ))}
                </TextField>
                {(statusFilter || taskNameFilter) && (
                  <Button
                    color="inherit"
                    onClick={() => {
                      setStatusFilter("");
                      setTaskNameFilter("");
                    }}
                  >
                    Clear
                  </Button>
                )}
              </Stack>
              <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
                Auto-refresh every 5 seconds Â· {jobsQuery.isFetching ? "syncing" : "idle"}
              </Typography>
            </Stack>
          }
        />
      )}

      {tab === 1 && (
        <DataTable
          columns={taskColumns}
          rows={tasksQuery.data?.items ?? []}
          getRowId={(row) => row.id}
          loading={tasksQuery.isLoading}
          error={tasksQuery.error ? toApiError(tasksQuery.error).message : null}
          onRetry={() => tasksQuery.refetch()}
          page={taskPage}
          size={taskSize}
          total={tasksQuery.data?.meta.total}
          onPageChange={setTaskPage}
          onSizeChange={setTaskSize}
          onRowClick={openEditTask}
          emptyTitle="No scheduled tasks"
          emptyDescription="Create a cron schedule to run backups, compliance scans, drift detection or safe custom actions."
          emptyAction={
            <PermissionGate permission="task:write">
              <Button variant="contained" startIcon={<AddIcon />} onClick={openCreateTask}>
                New schedule
              </Button>
            </PermissionGate>
          }
          toolbar={
            <Stack
              direction={{ xs: "column", md: "row" }}
              spacing={1}
              alignItems={{ xs: "stretch", md: "center" }}
              justifyContent="space-between"
            >
              <TextField
                select
                label="State"
                value={enabledFilter}
                onChange={(event) => setEnabledFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 180 } }}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="true">Enabled</MenuItem>
                <MenuItem value="false">Paused</MenuItem>
              </TextField>
              <Typography variant="caption" color="text.secondary">
                Schedules are materialised every minute by the scheduler beat; child jobs keep their own audit
                trail.
              </Typography>
            </Stack>
          }
        />
      )}

      <FormDialog
        open={jobFormOpen}
        title="Run a background task"
        description={
          <Typography variant="body2" color="text.secondary">
            Parameters are validated by the worker. Arbitrary task names are rejected by the API whitelist.
          </Typography>
        }
        submitLabel="Queue task"
        loading={createJobMutation.isPending}
        error={jobFormError}
        submitDisabled={!jobForm.task_name}
        onSubmit={submitJob}
        onClose={() => setJobFormOpen(false)}
        maxWidth="md"
      >
        <TextField
          select
          label="Task"
          value={jobForm.task_name}
          onChange={(event) => setJobForm((value) => ({ ...value, task_name: event.target.value }))}
        >
          {TASK_NAMES.map((task) => (
            <MenuItem key={task.value} value={task.value}>
              {task.label} Â· {task.description}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Parameters (JSON)"
          value={jobForm.params}
          onChange={(event) => setJobForm((value) => ({ ...value, params: event.target.value }))}
          multiline
          minRows={5}
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 12.5 },
          }}
          helperText='Examples: {"device_id": "â€¦"} for a single backup, {"framework": "cis"} for compliance'
        />
        <Alert severity="info">
          The job is persisted before it is sent to the broker, so a broker outage shows as a failed job instead
          of a silent loss.
        </Alert>
      </FormDialog>

      <FormDialog
        open={taskFormOpen}
        title={editingTask ? `Edit ${editingTask.name}` : "New scheduled task"}
        description={
          <Typography variant="body2" color="text.secondary">
            The task kind selects the worker task. Custom tasks may only perform safe actions
            (<code>noop</code>, <code>echo</code>, <code>touch</code>) and never execute shell commands.
          </Typography>
        }
        submitLabel={editingTask ? "Save schedule" : "Create schedule"}
        loading={saveTaskMutation.isPending}
        error={taskFormError}
        submitDisabled={!taskForm.name.trim() || !taskForm.cron.trim()}
        onSubmit={submitTask}
        onClose={() => {
          setTaskFormOpen(false);
          setEditingTask(null);
        }}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Name"
            value={taskForm.name}
            onChange={(event) => setTaskForm((value) => ({ ...value, name: event.target.value }))}
            required
            autoFocus
          />
          <TextField
            select
            label="Kind"
            value={taskForm.kind}
            onChange={(event) =>
              setTaskForm((value) => ({ ...value, kind: event.target.value as TaskKind }))
            }
            disabled={Boolean(editingTask)}
            helperText={editingTask ? "Kind cannot be changed after creation" : undefined}
          >
            {TASK_KINDS.map((kind) => (
              <MenuItem key={kind.value} value={kind.value}>
                {kind.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <TextField
          select
          label="Cron preset"
          value=""
          onChange={(event) => {
            if (!event.target.value) return;
            setTaskForm((value) => ({ ...value, cron: event.target.value }));
          }}
          helperText="Pick a preset or type a custom five-field cron expression"
        >
          <MenuItem value="">Custom</MenuItem>
          {CRON_PRESETS.map((preset) => (
            <MenuItem key={preset.value} value={preset.value}>
              {preset.label} Â· {preset.value}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Cron expression"
          value={taskForm.cron}
          onChange={(event) => setTaskForm((value) => ({ ...value, cron: event.target.value }))}
          required
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace" },
          }}
          helperText="UTC, standard five-field cron syntax (minute hour day-of-month month day-of-week)"
        />
        <TextField
          label="Payload (JSON)"
          value={taskForm.payload}
          onChange={(event) => setTaskForm((value) => ({ ...value, payload: event.target.value }))}
          multiline
          minRows={5}
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 12.5 },
          }}
          helperText='For custom tasks: {"task_name": "ofme.tasks.custom", "action": "noop"}'
        />
        <TextField
          select
          label="State"
          value={taskForm.enabled ? "true" : "false"}
          onChange={(event) =>
            setTaskForm((value) => ({ ...value, enabled: event.target.value === "true" }))
          }
        >
          <MenuItem value="true">Enabled</MenuItem>
          <MenuItem value="false">Paused</MenuItem>
        </TextField>
      </FormDialog>

      <FormDialog
        open={Boolean(jobDetail)}
        title={jobDetail ? `Job ${jobDetail.id.slice(0, 8)}` : "Job"}
        description={
          jobDetail ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <StatusChip status={jobDetail.status} />
              <Chip size="small" variant="outlined" label={jobDetail.task_name} />
              <Chip size="small" variant="outlined" label={`${Math.round(jobDetail.progress)}%`} />
            </Stack>
          ) : undefined
        }
        submitLabel="Close"
        onSubmit={() => setJobDetail(null)}
        onClose={() => setJobDetail(null)}
        maxWidth="md"
      >
        {jobDetail && (
          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Parameters
              </Typography>
              <CodeBlock code={prettyJson(jobDetail.params)} language="json" maxHeight={200} />
            </Box>
            {jobDetail.error && (
              <Alert severity="error">
                <Typography variant="body2" fontFamily="monospace">
                  {jobDetail.error}
                </Typography>
              </Alert>
            )}
            {jobDetail.result && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  Result
                </Typography>
                <CodeBlock code={prettyJson(jobDetail.result)} language="json" maxHeight={260} />
              </Box>
            )}
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Timeline
              </Typography>
              <CodeBlock
                code={prettyJson({
                  created_at: jobDetail.created_at,
                  started_at: jobDetail.started_at,
                  finished_at: jobDetail.finished_at,
                  celery_task_id: jobDetail.celery_task_id,
                })}
                language="json"
                maxHeight={160}
                showCopy={false}
              />
            </Box>
          </Stack>
        )}
      </FormDialog>

      <ConfirmDialog
        open={Boolean(cancelTarget)}
        title="Cancel job"
        description={
          cancelTarget
            ? `Cancel ${cancelTarget.task_name}? Running work is revoked with SIGTERM and the job is marked cancelled. Partial side effects are not rolled back automatically.`
            : undefined
        }
        confirmLabel="Cancel job"
        confirmColor="warning"
        loading={cancelMutation.isPending}
        onConfirm={() => cancelTarget && cancelMutation.mutate(cancelTarget)}
        onClose={() => setCancelTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(runTaskTarget)}
        title="Run schedule now"
        description={
          runTaskTarget
            ? `Queue ${runTaskTarget.name} immediately? The next scheduled run stays unchanged and the manual run is audited.`
            : undefined
        }
        confirmLabel="Run now"
        loading={runTaskMutation.isPending}
        onConfirm={() => runTaskTarget && runTaskMutation.mutate(runTaskTarget)}
        onClose={() => setRunTaskTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(deleteTaskTarget)}
        title="Delete scheduled task"
        description={
          deleteTaskTarget
            ? `Delete ${deleteTaskTarget.name}? The schedule stops immediately. Jobs already queued keep running.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteTaskMutation.isPending}
        onConfirm={() => deleteTaskTarget && deleteTaskMutation.mutate(deleteTaskTarget)}
        onClose={() => setDeleteTaskTarget(null)}
      />
    </>
  );
}

export default JobsPage;
