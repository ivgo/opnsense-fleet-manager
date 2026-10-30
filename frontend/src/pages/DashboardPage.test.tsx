import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  dashboardMock,
  trafficMock,
} = vi.hoisted(() => ({
  dashboardMock: vi.fn(),
  trafficMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  metricsApi: {
    dashboard: dashboardMock,
    fleetTraffic: trafficMock,
  },
  alertsApi: {
    acknowledge: vi.fn(),
  },
  complianceApi: {
    run: vi.fn(),
  },
  backupsApi: {
    sweep: vi.fn(),
  },
}));

import DashboardPage from "@/pages/DashboardPage";

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

const MOCK_DASHBOARD = {
  generated_at: "2026-10-30T12:00:00Z",
  summary: {
    devices_total: 10,
    devices_online: 8,
    devices_offline: 1,
    devices_error: 1,
    open_alerts: 3,
    critical_alerts: 1,
    compliance_score: 85.5,
    policies_drifted: 2,
    policies_total: 15,
    tunnels_up: 5,
    tunnels_total: 6,
  },
  health: [
    {
      device_id: "device-1",
      name: "fw-edge-01",
      status: "online",
      cpu_pct: 25.5,
      memory_pct: 45.2,
      disk_pct: 60.0,
      in_bps: 1000000,
      out_bps: 500000,
      vpn_up: 3,
      vpn_total: 4,
      uptime_seconds: 86400,
      recorded_at: "2026-10-30T12:00:00Z",
      gateways_up: 2,
      gateways_total: 2,
      carp_status: "MASTER",
    },
    {
      device_id: "device-2",
      name: "fw-branch-01",
      status: "online",
      cpu_pct: 15.0,
      memory_pct: 35.0,
      disk_pct: 40.0,
      in_bps: 500000,
      out_bps: 200000,
      vpn_up: 2,
      vpn_total: 2,
      uptime_seconds: 172800,
      recorded_at: "2026-10-30T12:00:00Z",
      gateways_up: 1,
      gateways_total: 1,
      carp_status: "BACKUP",
    },
  ],
  alerts: [
    {
      id: "alert-1",
      severity: "critical",
      title: "High CPU",
      message: "CPU usage above 90%",
      status: "firing",
      starts_at: "2026-10-30T11:00:00Z",
    },
    {
      id: "alert-2",
      severity: "warning",
      title: "Disk space low",
      message: "Disk usage above 80%",
      status: "firing",
      starts_at: "2026-10-30T10:00:00Z",
    },
    {
      id: "alert-3",
      severity: "info",
      title: "Backup completed",
      message: "Scheduled backup finished successfully",
      status: "acknowledged",
      starts_at: "2026-10-30T09:00:00Z",
      acknowledged_at: "2026-10-30T09:05:00Z",
    },
  ],
  top_alerts_by_severity: {
    critical: 1,
    warning: 1,
    info: 1,
  },
  trends: [
    {
      timestamp: "2026-10-30T10:00:00Z",
      online: 8,
      offline: 2,
    },
    {
      timestamp: "2026-10-30T11:00:00Z",
      online: 9,
      offline: 1,
    },
    {
      timestamp: "2026-10-30T12:00:00Z",
      online: 8,
      offline: 1,
    },
  ],
};

const MOCK_TRAFFIC = {
  bucket_seconds: 300,
  devices: [
    {
      device_id: "device-1",
      name: "fw-edge-01",
      interface_name: "wan",
      in_bps: 1000000,
      out_bps: 500000,
      recorded_at: "2026-10-30T12:00:00Z",
    },
  ],
  points: [
    {
      recorded_at: "2026-10-30T11:00:00Z",
      in_bps: 1000000,
      out_bps: 500000,
    },
  ],
};

async function renderDashboardPage() {
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
          <MemoryRouter initialEntries={["/dashboard"]}>
            <DashboardPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(dashboardMock).toHaveBeenCalled());

  return { store };
}

describe("DashboardPage", () => {
  beforeEach(() => {
    dashboardMock.mockReset();
    trafficMock.mockReset();

    dashboardMock.mockResolvedValue(MOCK_DASHBOARD);
    trafficMock.mockResolvedValue(MOCK_TRAFFIC);
  });

  it("renders the page header", async () => {
    await renderDashboardPage();

    expect(await screen.findByRole("heading", { name: "Fleet overview" })).toBeInTheDocument();
  });

  it("shows stat cards with summary data", async () => {
    await renderDashboardPage();

    expect(screen.getByText(/8 \/ 10/)).toBeInTheDocument(); // devices online
    expect(screen.getByText("3")).toBeInTheDocument(); // open alerts
    expect(screen.getByText("85.5%")).toBeInTheDocument(); // compliance score
    expect(screen.getByText("2")).toBeInTheDocument(); // policy drift
    expect(screen.getByText(/5 \/ 6/)).toBeInTheDocument(); // tunnels
  });

  it("shows fleet overview title", async () => {
    await renderDashboardPage();

    expect(await screen.findByRole("heading", { name: "Fleet overview" })).toBeInTheDocument();
  });

  it("shows add device button", async () => {
    await renderDashboardPage();

    expect(screen.getByRole("button", { name: "Add device" })).toBeInTheDocument();
  });

  it("shows run CIS scan button", async () => {
    await renderDashboardPage();

    expect(screen.getByRole("button", { name: "Run CIS scan" })).toBeInTheDocument();
  });

  it("shows backup all button", async () => {
    await renderDashboardPage();

    expect(screen.getByRole("button", { name: "Backup all" })).toBeInTheDocument();
  });

  it("shows fleet health section", async () => {
    await renderDashboardPage();

    expect(await screen.findByText("Fleet health")).toBeInTheDocument();
    expect(screen.getByText("Latest rates")).toBeInTheDocument();
  });

  it("shows recent alerts table", async () => {
    await renderDashboardPage();

    expect(await screen.findByText("Recent alerts")).toBeInTheDocument();
    expect(screen.getByText("High CPU")).toBeInTheDocument();
    expect(screen.getByText("Disk space low")).toBeInTheDocument();
    expect(screen.getByText("Backup completed")).toBeInTheDocument();
  });

  it("shows availability trend chart", async () => {
    await renderDashboardPage();

    expect(await screen.findByText("Availability trend")).toBeInTheDocument();
  });

  it("shows open alerts by severity chart", async () => {
    await renderDashboardPage();

    expect(await screen.findByText("Open alerts by severity")).toBeInTheDocument();
  });

  it("shows interface throughput chart", async () => {
    await renderDashboardPage();

    expect(await screen.findByText("Interface throughput")).toBeInTheDocument();
  });
});