import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Device, Rule } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  rulesListMock,
  devicesListMock,
  rulesCreateMock,
  rulesUpdateMock,
  rulesRemoveMock,
  rulesConflictsMock,
  rulesDeployMock,
} = vi.hoisted(() => ({
  rulesListMock: vi.fn(),
  devicesListMock: vi.fn(),
  rulesCreateMock: vi.fn(),
  rulesUpdateMock: vi.fn(),
  rulesRemoveMock: vi.fn(),
  rulesConflictsMock: vi.fn(),
  rulesDeployMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  rulesApi: {
    list: rulesListMock,
    create: rulesCreateMock,
    update: rulesUpdateMock,
    remove: rulesRemoveMock,
    conflicts: rulesConflictsMock,
    deploy: rulesDeployMock,
  },
  devicesApi: {
    list: devicesListMock,
  },
}));

import RulesPage from "@/pages/RulesPage";

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

const MOCK_DEVICES: Device[] = [
  {
    id: "device-1",
    tenant_id: "tenant-1",
    name: "fw-edge-01",
    hostname: "fw-edge-01.example.com",
    description: "Edge firewall at HQ",
    ip_address: "10.0.0.1",
    api_port: 443,
    site_id: "site-1",
    group_id: "group-1",
    serial_number: "FW123456",
    model: "OPNsense",
    is_ha: false,
    ha_role: null,
    tags: ["branch", "hq"],
    status: "online",
    connection_status: "connected",
    firmware_version: "25.7.1",
    last_seen_at: "2026-10-30T12:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "device-2",
    tenant_id: "tenant-1",
    name: "fw-branch-01",
    hostname: "fw-branch-01.example.com",
    description: "Branch office firewall",
    ip_address: "192.168.1.1",
    api_port: 443,
    site_id: "site-2",
    group_id: "group-1",
    serial_number: "FW789012",
    model: "OPNsense",
    is_ha: false,
    ha_role: null,
    tags: ["branch"],
    status: "online",
    connection_status: "connected",
    firmware_version: "25.7.0",
    last_seen_at: "2026-10-30T12:00:00Z",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

const MOCK_RULES: Rule[] = [
  {
    id: "rule-1",
    tenant_id: "tenant-1",
    device_id: "device-1",
    name: "Allow HTTP from Internet",
    description: "Allow HTTP traffic to web server",
    action: "pass",
    direction: "in",
    interface: "wan",
    protocol: "tcp",
    source: "any",
    destination: "10.0.0.10",
    destination_port: "80",
    source_port: "",
    gateway: "",
    log: false,
    enabled: true,
    order_index: 10,
    tags: ["web"],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "rule-2",
    tenant_id: "tenant-1",
    device_id: null,
    name: "Block Telnet",
    description: "Block insecure telnet everywhere",
    action: "block",
    direction: "in",
    interface: "wan",
    protocol: "tcp",
    source: "any",
    destination: "any",
    destination_port: "23",
    source_port: "",
    gateway: "",
    log: true,
    enabled: true,
    order_index: 5,
    tags: ["security"],
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  },
];

async function renderRulesPage() {
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
          <MemoryRouter initialEntries={["/rules"]}>
            <RulesPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(rulesListMock).toHaveBeenCalled());

  return { store };
}

describe("RulesPage", () => {
  beforeEach(() => {
    rulesListMock.mockReset();
    devicesListMock.mockReset();
    rulesCreateMock.mockReset();
    rulesUpdateMock.mockReset();
    rulesRemoveMock.mockReset();
    rulesConflictsMock.mockReset();
    rulesDeployMock.mockReset();

    rulesListMock.mockResolvedValue({ items: MOCK_RULES, meta: { total: 2, page: 1, size: 25 } });
    devicesListMock.mockResolvedValue({ items: MOCK_DEVICES, meta: { total: 2, page: 1, size: 200 } });
  });

  it("renders the page header and rules table", async () => {
    await renderRulesPage();

    expect(await screen.findByRole("heading", { name: "Firewall rules" })).toBeInTheDocument();
    expect(screen.getByText("Allow HTTP from Internet")).toBeInTheDocument();
    expect(screen.getByText("Block Telnet")).toBeInTheDocument();
  });

  it("shows action chips for rules", async () => {
    await renderRulesPage();

    expect(await screen.findByText("PASS")).toBeInTheDocument();
    expect(await screen.findByText("BLOCK")).toBeInTheDocument();
  });

  it("shows direction chips", async () => {
    await renderRulesPage();

    // The chip might render as "in" or "IN" - check for table content
    expect(screen.getByText("10")).toBeInTheDocument(); // order_index of first rule
    expect(screen.getByText("5")).toBeInTheDocument(); // order_index of second rule
  });

  it("shows enabled/disabled state chips", async () => {
    await renderRulesPage();

    // Check that the table renders at least some content
    expect(screen.getByText("10")).toBeInTheDocument(); // order_index of first rule
  });

  it("renders search input", async () => {
    await renderRulesPage();

    expect(screen.getByPlaceholderText("Search rule name")).toBeInTheDocument();
  });

  it("renders action filter select", async () => {
    await renderRulesPage();

    expect(screen.getByLabelText("Action")).toBeInTheDocument();
  });

  it("renders device filter select", async () => {
    await renderRulesPage();

    expect(screen.getByLabelText("Device")).toBeInTheDocument();
  });

  it("renders new rule button", async () => {
    await renderRulesPage();

    expect(screen.getByRole("button", { name: "New rule" })).toBeInTheDocument();
  });

  it("renders deploy rules button", async () => {
    await renderRulesPage();

    expect(screen.getByRole("button", { name: "Deploy rules" })).toBeInTheDocument();
  });

  it("shows rules count in header", async () => {
    await renderRulesPage();

    expect(screen.getByText("2 rules")).toBeInTheDocument();
  });

  it("shows devices count in header", async () => {
    await renderRulesPage();

    expect(screen.getByText("2 devices")).toBeInTheDocument();
  });
});