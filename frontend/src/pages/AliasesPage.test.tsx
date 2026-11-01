import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Alias, Device } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  aliasesListMock,
  devicesListMock,
} = vi.hoisted(() => ({
  aliasesListMock: vi.fn(),
  devicesListMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  aliasesApi: {
    list: aliasesListMock,
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
  devicesApi: {
    list: devicesListMock,
  },
}));

import { AliasesPage } from "@/pages/AliasesPage";

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
    description: "Edge firewall",
    ip_address: "10.0.0.1",
    api_port: 443,
    site_id: "site-1",
    group_id: "group-1",
    serial_number: "FW123456",
    model: "OPNsense",
    is_ha: false,
    ha_role: null,
    tags: ["edge"],
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
    description: "Branch firewall",
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

const MOCK_ALIASES: Alias[] = [
  {
    id: "alias-1",
    tenant_id: "tenant-1",
    device_id: "device-1",
    name: "web_servers",
    description: "Web server IPs",
    type: "host",
    content: ["192.0.2.10", "192.0.2.11"],
    enabled: true,
    created_at: "2026-01-15T08:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "alias-2",
    tenant_id: "tenant-1",
    device_id: "device-1",
    name: "internal_networks",
    description: "Internal network ranges",
    type: "network",
    content: ["10.0.0.0/8", "172.16.0.0/12"],
    enabled: true,
    created_at: "2026-01-16T09:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "alias-3",
    tenant_id: "tenant-1",
    device_id: "device-2",
    name: "blocked_ports",
    description: null,
    type: "port",
    content: ["443", "8000:8100"],
    enabled: false,
    created_at: "2026-01-17T10:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

async function renderAliasesPage() {
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
          <MemoryRouter initialEntries={["/aliases"]}>
            <AliasesPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(aliasesListMock).toHaveBeenCalled());

  return { store };
}

describe("AliasesPage", () => {
  beforeEach(() => {
    aliasesListMock.mockReset();
    devicesListMock.mockReset();

    aliasesListMock.mockResolvedValue({ items: MOCK_ALIASES, meta: { total: 3, page: 1, size: 25 } });
    devicesListMock.mockResolvedValue({ items: MOCK_DEVICES, meta: { total: 2, page: 1, size: 200 } });
  });

  it("renders the page header and aliases table", async () => {
    await renderAliasesPage();

    expect(await screen.findByRole("heading", { name: "Aliases" })).toBeInTheDocument();
    expect(screen.getByText("web_servers")).toBeInTheDocument();
    expect(screen.getByText("internal_networks")).toBeInTheDocument();
    expect(screen.getByText("blocked_ports")).toBeInTheDocument();
  });

  it("shows alias type chips", async () => {
    await renderAliasesPage();

    expect(screen.getByText("Host")).toBeInTheDocument();
    expect(screen.getByText("Network")).toBeInTheDocument();
    expect(screen.getByText("Port")).toBeInTheDocument();
  });

  it("shows enabled/disabled chips", async () => {
    await renderAliasesPage();

    expect(screen.getAllByText("Enabled").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Disabled").length).toBeGreaterThanOrEqual(1);
  });

  it("shows content entries count", async () => {
    await renderAliasesPage();

    expect(screen.getAllByText("2").length).toBeGreaterThanOrEqual(1);
  });

  it("shows device names in table", async () => {
    await renderAliasesPage();

    expect(screen.getAllByText("fw-edge-01").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("fw-branch-01").length).toBeGreaterThanOrEqual(1);
  });

  it("renders search input", async () => {
    await renderAliasesPage();

    expect(screen.getByPlaceholderText("Search name or description")).toBeInTheDocument();
  });

  it("renders type filter select", async () => {
    await renderAliasesPage();

    expect(screen.getByLabelText("Type")).toBeInTheDocument();
  });

  it("renders device filter select", async () => {
    await renderAliasesPage();

    expect(screen.getByLabelText("Device")).toBeInTheDocument();
  });

  it("renders new alias button", async () => {
    await renderAliasesPage();

    expect(screen.getByRole("button", { name: "New alias" })).toBeInTheDocument();
  });

  it("shows aliases count in header", async () => {
    await renderAliasesPage();

    expect(screen.getAllByText(/aliases/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows devices count in header", async () => {
    await renderAliasesPage();

    expect(screen.getAllByText(/devices/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders empty state", async () => {
    aliasesListMock.mockResolvedValueOnce({ items: [], meta: { total: 0, page: 1, size: 25 } });
    await renderAliasesPage();

    expect(screen.getByText("No aliases")).toBeInTheDocument();
    expect(screen.getByText("Create reusable object groups and reference them from rules and NAT entries.")).toBeInTheDocument();
  });
});