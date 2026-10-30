import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, AuditEntry } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  auditListMock,
  auditIntegrityMock,
  auditActionsMock,
} = vi.hoisted(() => ({
  auditListMock: vi.fn(),
  auditIntegrityMock: vi.fn(),
  auditActionsMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  auditApi: {
    list: auditListMock,
    integrity: auditIntegrityMock,
    actions: auditActionsMock,
    events: vi.fn(),
    export: vi.fn(),
  },
}));

import AuditPage from "@/pages/AuditPage";

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
  last_login_at: "2026-10-30T10:00:00Z",
};

const MOCK_AUDIT: AuditEntry[] = [
  {
    id: 1001,
    tenant_id: "tenant-1",
    user_id: "user-1",
    actor: "admin",
    action: "create",
    resource_type: "device",
    resource_id: "device-1",
    result: "success",
    ip_address: "192.168.1.100",
    request_id: "req-abc123",
    method: "POST",
    path: "/api/v1/devices",
    status_code: 201,
    before: null,
    after: { name: "fw-new-01", ip_address: "10.0.0.10" },
    error: null,
    created_at: "2026-10-30T10:00:00Z",
  },
  {
    id: 1002,
    tenant_id: "tenant-1",
    user_id: "user-2",
    actor: "jane.smith",
    action: "update",
    resource_type: "policy",
    resource_id: "policy-1",
    result: "failure",
    ip_address: "10.0.0.50",
    request_id: "req-def456",
    method: "PUT",
    path: "/api/v1/policies/policy-1",
    status_code: 400,
    before: { name: "old policy" },
    after: { name: "new policy" },
    error: "Validation failed",
    created_at: "2026-10-30T09:30:00Z",
  },
];

const MOCK_INTEGRITY = {
  checked: 1001,
  valid: true,
  first_broken_id: null,
  last_hash: "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
};

const MOCK_ACTIONS = [
  { action: "create", resource_type: "device" },
  { action: "update", resource_type: "policy" },
  { action: "delete", resource_type: "user" },
];

async function renderAuditPage() {
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
          <MemoryRouter initialEntries={["/audit"]}>
            <AuditPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(auditListMock).toHaveBeenCalled());

  return { store };
}

describe("AuditPage", () => {
  beforeEach(() => {
    auditListMock.mockReset();
    auditIntegrityMock.mockReset();
    auditActionsMock.mockReset();

    auditListMock.mockResolvedValue({ items: MOCK_AUDIT, meta: { total: 2, page: 1, size: 25 } });
    auditIntegrityMock.mockResolvedValue(MOCK_INTEGRITY);
    auditActionsMock.mockResolvedValue(MOCK_ACTIONS);
  });

  it("renders the page header", async () => {
    await renderAuditPage();

    expect(await screen.findByRole("heading", { name: "Audit trail" })).toBeInTheDocument();
  });

  it("shows audit entry count chip", async () => {
    await renderAuditPage();

    expect(screen.getAllByText(/entries/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows chain verified chip", async () => {
    await renderAuditPage();

    expect(screen.getByText("chain verified")).toBeInTheDocument();
  });

  it("renders audit table with entries", async () => {
    await renderAuditPage();

    expect(await screen.findByText("#1001")).toBeInTheDocument();
    expect(await screen.findByText("#1002")).toBeInTheDocument();
  });

  it("shows actor names", async () => {
    await renderAuditPage();

    expect(screen.getByText("admin")).toBeInTheDocument();
    expect(screen.getByText("jane.smith")).toBeInTheDocument();
  });

  it("shows action and resource type", async () => {
    await renderAuditPage();

    // Action column shows "create", "update" - use regex for partial matches
    expect(screen.getAllByText(/create/i).length).toBeGreaterThanOrEqual(1);
    // Resource type appears in table and filter dropdown
    expect(screen.getAllByText(/device/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/update/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/policy/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows result chips (success/failure)", async () => {
    await renderAuditPage();

    expect(screen.getAllByText("success").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("failure").length).toBeGreaterThanOrEqual(1);
  });

  it("renders filter dropdowns", async () => {
    await renderAuditPage();

    expect(screen.getByLabelText("Action")).toBeInTheDocument();
    expect(screen.getByLabelText("Resource")).toBeInTheDocument();
    expect(screen.getByLabelText("Result")).toBeInTheDocument();
  });

  it("renders time window button", async () => {
    await renderAuditPage();

    expect(screen.getByRole("button", { name: "Time window" })).toBeInTheDocument();
  });

  it("opens time window dialog", async () => {
    await renderAuditPage();

    await screen.findByRole("button", { name: "Time window" }).then(btn => btn.click());

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(screen.getByText("Filter by time window")).toBeInTheDocument();
    expect(screen.getByLabelText("From")).toBeInTheDocument();
    expect(screen.getByLabelText("To")).toBeInTheDocument();
  });

  it("opens detail dialog on row click", async () => {
    await renderAuditPage();

    // Click on first row
    const rows = await screen.findAllByRole("row");
    // Skip header row, click first data row
    if (rows.length > 1) {
      await waitFor(() => rows[1].click());
    }

    // Wait for detail dialog
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(await screen.findByText("Audit entry #1001")).toBeInTheDocument();
  });
});