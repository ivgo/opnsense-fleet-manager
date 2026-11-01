import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Report } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  reportsListMock,
  reportsCreateMock,
  reportsDownloadMock,
  reportsRemoveMock,
} = vi.hoisted(() => ({
  reportsListMock: vi.fn(),
  reportsCreateMock: vi.fn(),
  reportsDownloadMock: vi.fn(),
  reportsRemoveMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  reportsApi: {
    list: reportsListMock,
    create: reportsCreateMock,
    download: reportsDownloadMock,
    remove: reportsRemoveMock,
  },
}));

import ReportsPage from "@/pages/ReportsPage";

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

const MOCK_REPORTS: Report[] = [
  {
    id: "report-1",
    tenant_id: "tenant-1",
    name: "Fleet Weekly Report",
    kind: "fleet",
    status: "ready",
    period_start: "2026-10-23T12:00:00Z",
    period_end: "2026-10-30T12:00:00Z",
    params: {},
    size_bytes: 102400,
    checksum_sha256: null,
    error: null,
    generated_at: "2026-10-30T12:00:00Z",
    created_by: "user-1",
    download_url: "/reports/report-1.pdf",
    created_at: "2026-10-30T11:55:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "report-2",
    tenant_id: "tenant-1",
    name: "Compliance Monthly",
    kind: "compliance",
    status: "generating",
    period_start: "2026-09-30T12:00:00Z",
    period_end: "2026-10-30T12:00:00Z",
    params: {},
    size_bytes: null,
    checksum_sha256: null,
    error: null,
    generated_at: null,
    created_by: "user-1",
    download_url: null,
    created_at: "2026-10-30T10:00:00Z",
    updated_at: "2026-10-30T10:00:00Z",
  },
];

async function renderReportsPage() {
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
          <MemoryRouter initialEntries={["/reports"]}>
            <ReportsPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(reportsListMock).toHaveBeenCalled());

  return { store };
}

describe("ReportsPage", () => {
  beforeEach(() => {
    reportsListMock.mockReset();
    reportsCreateMock.mockReset();
    reportsDownloadMock.mockReset();
    reportsRemoveMock.mockReset();

    reportsListMock.mockResolvedValue(MOCK_REPORTS);
  });

  it("renders the page header and reports table", async () => {
    await renderReportsPage();

    expect(await screen.findByRole("heading", { name: "Reports" })).toBeInTheDocument();
    expect(screen.getByText("Fleet Weekly Report")).toBeInTheDocument();
    expect(screen.getByText("Compliance Monthly")).toBeInTheDocument();
  });

  it("shows report kind labels", async () => {
    await renderReportsPage();

    // Kind labels appear in the table caption text (e.g., "Fleet summary · created ...")
    expect(screen.getByText(/Fleet summary/)).toBeInTheDocument();
    // The compliance kind label appears in a caption element - use getAllByText to handle duplicates
    expect(screen.getAllByText(/Compliance/)).toHaveLength(2);
  });

  it("shows status badges", async () => {
    await renderReportsPage();

    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Generating")).toBeInTheDocument();
  });

  it("renders new report button", async () => {
    await renderReportsPage();

    expect(screen.getByRole("button", { name: "New report" })).toBeInTheDocument();
  });

  it("shows reports count in header", async () => {
    await renderReportsPage();

    expect(screen.getByText("2 reports")).toBeInTheDocument();
  });

  it("shows file size for ready reports", async () => {
    await renderReportsPage();

    expect(screen.getByText("100 KB")).toBeInTheDocument();
  });
});