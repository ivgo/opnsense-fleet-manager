import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, ComplianceReport, ComplianceSummary } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  complianceSummaryMock,
  complianceReportsMock,
} = vi.hoisted(() => ({
  complianceSummaryMock: vi.fn(),
  complianceReportsMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  complianceApi: {
    summary: complianceSummaryMock,
    reports: complianceReportsMock,
    run: vi.fn(),
    evidence: vi.fn(),
    removeReport: vi.fn(),
    remediate: vi.fn(),
  },
}));

import CompliancePage from "@/pages/CompliancePage";

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

const MOCK_SUMMARY: ComplianceSummary[] = [
  {
    framework: "cis",
    controls_total: 150,
    controls_passed: 135,
    controls_failed: 15,
    latest_score: 90.0,
    last_run: "2026-10-30T10:00:00Z",
    trend: [
      { timestamp: "2026-10-25T10:00:00Z", score: 88.5 },
      { timestamp: "2026-10-28T10:00:00Z", score: 89.2 },
      { timestamp: "2026-10-30T10:00:00Z", score: 90.0 },
    ],
  },
  {
    framework: "iso27001",
    controls_total: 114,
    controls_passed: 98,
    controls_failed: 16,
    latest_score: 86.0,
    last_run: "2026-10-29T10:00:00Z",
    trend: [
      { timestamp: "2026-10-25T10:00:00Z", score: 84.0 },
      { timestamp: "2026-10-29T10:00:00Z", score: 86.0 },
    ],
  },
];

const MOCK_REPORTS: ComplianceReport[] = [
  {
    id: "report-1",
    tenant_id: "tenant-1",
    framework: "cis",
    score: 90.0,
    status: "completed",
    scope: { device_ids: ["device-1", "device-2"] },
    controls_total: 150,
    controls_passed: 135,
    controls_failed: 15,
    controls: [
      { control_id: "1.1.1", title: "Ensure SSH access is limited", status: "passed", severity: "medium", evidence: "OK", remediation: null, affected_devices: [] },
      { control_id: "1.1.2", title: "Ensure password complexity", status: "failed", severity: "high", evidence: "FAIL", remediation: "Update PAM config", affected_devices: ["device-1"] },
    ],
    summary: "CIS benchmark assessment completed",
    generated_at: "2026-10-30T10:00:00Z",
    created_at: "2026-10-30T10:00:00Z",
  },
  {
    id: "report-2",
    tenant_id: "tenant-1",
    framework: "iso27001",
    score: 86.0,
    status: "completed",
    scope: { device_ids: [] },
    controls_total: 114,
    controls_passed: 98,
    controls_failed: 16,
    controls: [],
    summary: "ISO 27001 assessment completed",
    generated_at: "2026-10-29T10:00:00Z",
    created_at: "2026-10-29T10:00:00Z",
  },
];

async function renderCompliancePage() {
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
          <MemoryRouter initialEntries={["/compliance"]}>
            <CompliancePage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(complianceSummaryMock).toHaveBeenCalled());

  return { store };
}

describe("CompliancePage", () => {
  beforeEach(() => {
    complianceSummaryMock.mockReset();
    complianceReportsMock.mockReset();

    complianceSummaryMock.mockResolvedValue(MOCK_SUMMARY);
    complianceReportsMock.mockResolvedValue({ items: MOCK_REPORTS, meta: { total: 2, page: 1, size: 25 } });
  });

  it("renders the page header and compliance cards", async () => {
    await renderCompliancePage();

    expect(await screen.findByRole("heading", { name: "Compliance" })).toBeInTheDocument();
    expect(screen.getAllByText("CIS Benchmark").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("ISO/IEC 27001").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("90.0%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("86.0%").length).toBeGreaterThanOrEqual(1);
  });

  it("shows framework scores with correct colors", async () => {
    await renderCompliancePage();

    expect(screen.getAllByText("pass").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("risk")).toBeInTheDocument(); // ISO 86% -> risk
  });

  it("shows controls count in framework cards", async () => {
    await renderCompliancePage();

    expect(screen.getAllByText("150 controls · 15 failed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("114 controls · 16 failed").length).toBeGreaterThanOrEqual(1);
  });

  it("renders run assessment button", async () => {
    await renderCompliancePage();

    expect(screen.getByRole("button", { name: "Run assessment" })).toBeInTheDocument();
  });

  it("shows reports count in header", async () => {
    await renderCompliancePage();

    expect(screen.getAllByText(/reports/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows evaluated frameworks count in header", async () => {
    await renderCompliancePage();

    expect(screen.getAllByText(/evaluated frameworks/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders assessment history table", async () => {
    await renderCompliancePage();

    expect(screen.getAllByText("CIS Benchmark").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("ISO/IEC 27001").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("90.0%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("86.0%").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("pass").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("at risk")).toBeInTheDocument();
    // StatusChip renders "Completed" - appears twice (once per report row)
    expect(screen.getAllByText(/completed/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders framework filter select", async () => {
    await renderCompliancePage();

    expect(screen.getByLabelText("Framework")).toBeInTheDocument();
  });

  it("runs assessment dialog opens", async () => {
    await renderCompliancePage();

    // Click Run assessment button
    const button = await screen.findByRole("button", { name: "Run assessment" });
    await waitFor(() => button.click());

    expect(await screen.findByText("Run compliance assessment")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Framework").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("button", { name: "Start assessment" })).toBeInTheDocument();
  });
});