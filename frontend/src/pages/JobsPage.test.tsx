import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Job, ScheduledTask } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  jobsListMock,
  jobsCreateMock,
  jobsCancelMock,
  jobsRetryMock,
  tasksListMock,
  tasksCreateMock,
  tasksUpdateMock,
  tasksRemoveMock,
} = vi.hoisted(() => ({
  jobsListMock: vi.fn(),
  jobsCreateMock: vi.fn(),
  jobsCancelMock: vi.fn(),
  jobsRetryMock: vi.fn(),
  tasksListMock: vi.fn(),
  tasksCreateMock: vi.fn(),
  tasksUpdateMock: vi.fn(),
  tasksRemoveMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  jobsApi: {
    list: jobsListMock,
    create: jobsCreateMock,
    cancel: jobsCancelMock,
    retry: jobsRetryMock,
  },
  tasksApi: {
    list: tasksListMock,
    create: tasksCreateMock,
    update: tasksUpdateMock,
    remove: tasksRemoveMock,
  },
}));

import JobsPage from "@/pages/JobsPage";

const USER: AuthUser = {
  id: "8f0d3a7e-6b1c-4a5d-9c2e-7f3b1a0d6e4c",
  tenant_id: null,
  username: "admin",
  email: "admin@example.com",
  full_name: "Platform Admin",
  roles: ["SuperAdmin"],
  permissions: ["*"],
  is_superadmin: true,
  mfa_enabled: false,
  auth_provider: "local",
  last_login_at: null,
};

const MOCK_JOBS: Job[] = [
  {
    id: "job-1",
    tenant_id: "tenant-1",
    task_name: "ofme.backups.create",
    celery_task_id: "celery-abc123",
    status: "completed",
    progress: 100,
    params: { device_id: "device-1" },
    result: { backup_id: "backup-1" },
    error: null,
    started_at: "2026-10-30T11:55:00Z",
    finished_at: "2026-10-30T12:00:00Z",
    created_at: "2026-10-30T11:55:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "job-2",
    tenant_id: "tenant-1",
    task_name: "ofme.compliance.run",
    celery_task_id: "celery-def456",
    status: "running",
    progress: 45,
    params: { framework: "cis" },
    result: null,
    error: null,
    started_at: "2026-10-30T12:00:00Z",
    finished_at: null,
    created_at: "2026-10-30T12:00:00Z",
    updated_at: "2026-10-30T12:05:00Z",
  },
];

const MOCK_TASKS: ScheduledTask[] = [
  {
    id: "task-1",
    tenant_id: "tenant-1",
    name: "Daily Backup",
    kind: "backup",
    cron: "0 2 * * *",
    payload: {},
    enabled: true,
    last_run_at: "2026-10-30T02:00:00Z",
    next_run_at: "2026-10-31T02:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-30T02:00:00Z",
  },
  {
    id: "task-2",
    tenant_id: "tenant-1",
    name: "Weekly Compliance",
    kind: "compliance_scan",
    cron: "0 3 * * 1",
    payload: { framework: "cis" },
    enabled: false,
    last_run_at: null,
    next_run_at: "2026-11-03T03:00:00Z",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

async function renderJobsPage() {
  const store = configureStore({
    reducer: { auth: authReducer, ui: uiReducer },
    preloadedState: {
      auth: {
        user: USER,
        status: "authenticated",
        hydrated: true,
        error: null,
        mfaRequired: false,
        challengeToken: null,
        mfaMethods: [],
      },
      ui: { toasts: [] },
    },
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  render(
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider theme={buildTheme("light")}>
          <MemoryRouter initialEntries={["/jobs"]}>
            <JobsPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(jobsListMock).toHaveBeenCalled());

  return { store };
}

async function renderJobsPageOnTasksTab() {
  await renderJobsPage();
  const user = userEvent.setup();
  const tasksTab = await screen.findByRole("tab", { name: "Scheduled tasks" });
  await user.click(tasksTab);
  await waitFor(() => expect(tasksListMock).toHaveBeenCalled());
}

describe("JobsPage", () => {
  beforeEach(() => {
    jobsListMock.mockReset();
    jobsCreateMock.mockReset();
    jobsCancelMock.mockReset();
    jobsRetryMock.mockReset();
    tasksListMock.mockReset();
    tasksCreateMock.mockReset();
    tasksUpdateMock.mockReset();
    tasksRemoveMock.mockReset();

    jobsListMock.mockResolvedValue({ items: MOCK_JOBS, meta: { total: 2, page: 1, size: 25 } });
    tasksListMock.mockResolvedValue({ items: MOCK_TASKS, meta: { total: 2, page: 1, size: 25 } });
  });

  describe("Jobs tab", () => {
    it("renders the page header and jobs table", async () => {
      await renderJobsPage(0);

      expect(await screen.findByRole("heading", { name: "Jobs & schedules" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "Jobs" })).toBeInTheDocument();
      expect(screen.getByText("ofme.backups.create")).toBeInTheDocument();
      expect(screen.getByText("ofme.compliance.run")).toBeInTheDocument();
    });

    it("shows jobs count in header", async () => {
      await renderJobsPage();

      expect(screen.getByText("2 jobs")).toBeInTheDocument();
    });

    it("renders run task button", async () => {
      await renderJobsPage();

      expect(screen.getByRole("button", { name: /run task/i })).toBeInTheDocument();
    });
  });

  describe("Scheduled Tasks tab", () => {
    it("renders scheduled tasks table when switching tabs", async () => {
      await renderJobsPage();
      const user = userEvent.setup();

      const tasksTab = screen.getByRole("tab", { name: "Scheduled tasks" });
      await user.click(tasksTab);

      expect(screen.getByText("Daily Backup")).toBeInTheDocument();
      expect(screen.getByText("Weekly Compliance")).toBeInTheDocument();
    });

    it("shows kind badges", async () => {
      await renderJobsPage();
      const user = userEvent.setup();

      const tasksTab = screen.getByRole("tab", { name: "Scheduled tasks" });
      await user.click(tasksTab);

      expect(await screen.findByText("Configuration backup")).toBeInTheDocument();
      expect(screen.getByText("Compliance scan")).toBeInTheDocument();
    });

    it("shows enabled status", async () => {
      await renderJobsPage();
      const user = userEvent.setup();

      const tasksTab = screen.getByRole("tab", { name: "Scheduled tasks" });
      await user.click(tasksTab);

      expect(await screen.findByText("Enabled")).toBeInTheDocument();
      expect(screen.getByText("Disabled")).toBeInTheDocument();
    });

    it("shows cron expressions", async () => {
      await renderJobsPage();
      const user = userEvent.setup();

      const tasksTab = screen.getByRole("tab", { name: "Scheduled tasks" });
      await user.click(tasksTab);

      expect(screen.getByText("0 2 * * *")).toBeInTheDocument();
      expect(screen.getByText("0 3 * * 1")).toBeInTheDocument();
    });

    it("renders new schedule button", async () => {
      await renderJobsPage();
      const user = userEvent.setup();

      const tasksTab = screen.getByRole("tab", { name: "Scheduled tasks" });
      await user.click(tasksTab);

      expect(screen.getByRole("button", { name: "New schedule" })).toBeInTheDocument();
    });

    it("shows scheduled tasks count in header", async () => {
      await renderJobsPage();
      const user = userEvent.setup();

      const tasksTab = screen.getByRole("tab", { name: "Scheduled tasks" });
      await user.click(tasksTab);

      expect(await screen.findByText("2 schedules")).toBeInTheDocument();
    });
  });
});