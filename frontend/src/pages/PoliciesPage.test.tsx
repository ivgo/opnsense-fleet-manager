import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Policy, Deployment, DriftReport } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  policiesListMock,
  driftListMock,
  deploymentsListMock,
} = vi.hoisted(() => ({
  policiesListMock: vi.fn(),
  driftListMock: vi.fn(),
  deploymentsListMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  policiesApi: {
    list: policiesListMock,
    validate: vi.fn(),
    deploy: vi.fn(),
    diff: vi.fn(),
    simulate: vi.fn(),
    promote: vi.fn(),
  },
  driftApi: {
    list: driftListMock,
    scan: vi.fn(),
    resolve: vi.fn(),
  },
  deploymentsApi: {
    list: deploymentsListMock,
    rollback: vi.fn(),
  },
}));

import PoliciesPage from "@/pages/PoliciesPage";

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

const MOCK_POLICIES: Policy[] = [
  {
    id: "policy-1",
    tenant_id: "tenant-1",
    name: "Allow HTTP from Internet",
    kind: "firewall",
    environment: "production",
    description: "Allow HTTP traffic to web server",
    content: "{\n  \"rules\": []\n}",
    target_selector: { all: true },
    status: "active",
    version: 3,
    path: "/firewall/allow_http.yaml",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "policy-2",
    tenant_id: "tenant-1",
    name: "Block Telnet",
    kind: "firewall",
    environment: "development",
    description: "Block insecure telnet everywhere",
    content: "{\n  \"rules\": []\n}",
    target_selector: { all: true },
    status: "draft",
    version: 1,
    path: "/firewall/block_telnet.yaml",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-29T12:00:00Z",
  },
];

const MOCK_DRIFT: DriftReport[] = [];
const MOCK_DEPLOYMENTS: Deployment[] = [];

async function renderPoliciesPage() {
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
          <MemoryRouter initialEntries={["/policies"]}>
            <PoliciesPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(policiesListMock).toHaveBeenCalled());

  return { store };
}

describe("PoliciesPage", () => {
  beforeEach(() => {
    policiesListMock.mockReset();
    driftListMock.mockReset();
    deploymentsListMock.mockReset();

    policiesListMock.mockResolvedValue({ items: MOCK_POLICIES, meta: { total: 2, page: 1, size: 25 } });
    driftListMock.mockResolvedValue({ items: MOCK_DRIFT, meta: { total: 0, page: 1, size: 25 } });
    deploymentsListMock.mockResolvedValue({ items: MOCK_DEPLOYMENTS, meta: { total: 0, page: 1, size: 25 } });
  });

  it("renders the page header and policy table", async () => {
    await renderPoliciesPage();

    expect(await screen.findByRole("heading", { name: "Policies" })).toBeInTheDocument();
    expect(screen.getByText("Allow HTTP from Internet")).toBeInTheDocument();
    expect(screen.getByText("Block Telnet")).toBeInTheDocument();
  });

  it("shows policy kind chips", async () => {
    await renderPoliciesPage();

    expect(screen.getAllByText("firewall").length).toBeGreaterThan(0);
  });

  it("shows environment chips", async () => {
    await renderPoliciesPage();

    expect(screen.getAllByText("production").length).toBeGreaterThan(0);
    expect(screen.getAllByText("development").length).toBeGreaterThan(0);
  });

  it("renders search input", async () => {
    await renderPoliciesPage();

    expect(screen.getByPlaceholderText("Search policies")).toBeInTheDocument();
  });

  it("renders kind filter select", async () => {
    await renderPoliciesPage();

    expect(screen.getByLabelText("Kind")).toBeInTheDocument();
  });

  it("renders environment filter select", async () => {
    await renderPoliciesPage();

    expect(screen.getByLabelText("Environment")).toBeInTheDocument();
  });

  it("renders status filter select", async () => {
    await renderPoliciesPage();

    expect(screen.getByLabelText("Status")).toBeInTheDocument();
  });

  it("renders new policy button", async () => {
    await renderPoliciesPage();

    expect(screen.getByRole("button", { name: "New policy" })).toBeInTheDocument();
  });

  it("renders scan drift button", async () => {
    await renderPoliciesPage();

    expect(screen.getByRole("button", { name: "Scan drift" })).toBeInTheDocument();
  });

  it("shows policies count in header", async () => {
    await renderPoliciesPage();

    expect(screen.getAllByText(/2 policies/).length).toBeGreaterThanOrEqual(1);
  });

  it("renders tabs for policies, drift and deployments", async () => {
    await renderPoliciesPage();

    expect(screen.getAllByText("Policies").length).toBeGreaterThan(0);
    expect(screen.getByText("Drift")).toBeInTheDocument();
    expect(screen.getByText("Deployments")).toBeInTheDocument();
  });
});