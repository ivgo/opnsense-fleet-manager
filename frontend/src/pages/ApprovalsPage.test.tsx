import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, ChangeRequest, Environment } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const { listMock, approveMock, rejectMock, cancelMock, createMock } = vi.hoisted(() => ({
  listMock: vi.fn(),
  approveMock: vi.fn(),
  rejectMock: vi.fn(),
  cancelMock: vi.fn(),
  createMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  changesApi: {
    list: listMock,
    approve: approveMock,
    reject: rejectMock,
    cancel: cancelMock,
    create: createMock,
  },
}));

import ApprovalsPage from "@/pages/ApprovalsPage";

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

const MOCK_CHANGES: ChangeRequest[] = [
  {
    id: "1",
    tenant_id: "tenant-1",
    title: "Add WAN firewall rule",
    description: "Allow HTTP from internet to web server",
    type: "firewall_rule",
    priority: "high",
    status: "pending",
    environment: "production" as Environment,
    payload: { action: "pass", source: "any", destination: "10.0.0.10" },
    requested_by: "8f0d3a7e-6b1c-4a5d-9c2e-7f3b1a0d6e4c",
    required_approvals: 2,
    approvals: [
      { user_id: "user-1", decision: "approved", comment: "LGTM", at: "2026-01-01T10:00:00Z" },
    ],
    created_at: "2026-01-01T09:00:00Z",
    updated_at: "2026-01-01T10:00:00Z",
    expires_at: "2026-01-04T09:00:00Z",
    applied_at: null,
  },
  {
    id: "2",
    tenant_id: "tenant-1",
    title: "Update NAT port forward",
    description: "Change external port from 8080 to 80",
    type: "nat",
    priority: "medium",
    status: "approved",
    environment: "production" as Environment,
    payload: { external_port: 80, internal_ip: "10.0.0.10", internal_port: 80 },
    requested_by: "another-user",
    required_approvals: 1,
    approvals: [
      { user_id: "user-1", decision: "approved", comment: "Approved", at: "2026-01-02T10:00:00Z" },
    ],
    created_at: "2026-01-02T09:00:00Z",
    updated_at: "2026-01-02T10:00:00Z",
    expires_at: "2026-01-05T09:00:00Z",
    applied_at: "2026-01-02T10:30:00Z",
  },
];

async function renderApprovalsPage() {
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
          <MemoryRouter initialEntries={["/approvals"]}>
            <ApprovalsPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  // Wait for the query to resolve
  await waitFor(() => expect(listMock).toHaveBeenCalled());

  return { store };
}

describe("ApprovalsPage", () => {
  beforeEach(() => {
    listMock.mockReset();
    approveMock.mockReset();
    rejectMock.mockReset();
    cancelMock.mockReset();
    createMock.mockReset();
    listMock.mockResolvedValue({ items: MOCK_CHANGES, meta: { total: 2, page: 1, size: 25 } });
  });

  it("renders the page header and change requests", async () => {
    await renderApprovalsPage();

    expect(await screen.findByRole("heading", { name: "Approvals" })).toBeInTheDocument();
    expect(screen.getByText("Add WAN firewall rule")).toBeInTheDocument();
    expect(screen.getByText("Update NAT port forward")).toBeInTheDocument();
  });

  it("shows approval progress for pending changes", async () => {
    await renderApprovalsPage();

    // First change has 1 of 2 approvals
    expect(await screen.findByText("1/2")).toBeInTheDocument();
    // Second change has 1 of 1 approvals (approved)
    expect(await screen.findByText("1/1")).toBeInTheDocument();
  });

  it("renders status filter select", async () => {
    await renderApprovalsPage();

    expect(screen.getByLabelText("Status")).toBeInTheDocument();
  });

  it("renders search input", async () => {
    await renderApprovalsPage();

    expect(screen.getByPlaceholderText("Search change requests")).toBeInTheDocument();
  });

  it("renders create change request button", async () => {
    await renderApprovalsPage();

    expect(screen.getByRole("button", { name: "New change request" })).toBeInTheDocument();
  });

  it("shows pagination info", async () => {
    await renderApprovalsPage();

    expect(screen.getByText("2 change requests")).toBeInTheDocument();
  });
});