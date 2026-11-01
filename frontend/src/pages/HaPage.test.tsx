import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, HaCluster, Device, Site } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  haClustersMock,
  devicesListMock,
  sitesListMock,
} = vi.hoisted(() => ({
  haClustersMock: vi.fn(),
  devicesListMock: vi.fn(),
  sitesListMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  haApi: {
    clusters: haClustersMock,
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    refresh: vi.fn(),
    failover: vi.fn(),
  },
  devicesApi: {
    list: devicesListMock,
  },
  sitesApi: {
    list: sitesListMock,
  },
}));

import { HaPage } from "@/pages/HaPage";

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
    name: "fw-primary-01",
    hostname: "fw-primary-01.example.com",
    description: "Primary firewall",
    ip_address: "10.0.0.1",
    api_port: 443,
    site_id: "site-1",
    group_id: "group-1",
    serial_number: "FW123456",
    model: "OPNsense",
    is_ha: true,
    ha_role: "primary",
    tags: ["ha", "primary"],
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
    name: "fw-secondary-01",
    hostname: "fw-secondary-01.example.com",
    description: "Secondary firewall",
    ip_address: "10.0.0.2",
    api_port: 443,
    site_id: "site-1",
    group_id: "group-1",
    serial_number: "FW789012",
    model: "OPNsense",
    is_ha: true,
    ha_role: "secondary",
    tags: ["ha", "secondary"],
    status: "online",
    connection_status: "connected",
    firmware_version: "25.7.1",
    last_seen_at: "2026-10-30T12:00:00Z",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

const MOCK_SITES: Site[] = [
  {
    id: "site-1",
    tenant_id: "tenant-1",
    name: "Headquarters",
    description: "Main office",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

const MOCK_CLUSTERS: HaCluster[] = [
  {
    id: "ha-1",
    tenant_id: "tenant-1",
    name: "HQ-CARP-Cluster",
    description: "Headquarters high availability cluster",
    site_id: "site-1",
    virtual_ip: "10.0.0.254",
    interface: "lan",
    vhid: 1,
    advbase: 1,
    enabled: true,
    sync_status: "in_sync",
    last_sync_at: "2026-10-30T11:55:00Z",
    nodes: [
      {
        id: "node-1",
        device_id: "device-1",
        role: "primary",
        advskew: 0,
      },
      {
        id: "node-2",
        device_id: "device-2",
        role: "secondary",
        advskew: 100,
      },
    ],
    created_at: "2026-01-15T08:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "ha-2",
    tenant_id: "tenant-1",
    name: "Branch-CARP-Cluster",
    description: null,
    site_id: null,
    virtual_ip: "192.168.1.254",
    interface: "wan",
    vhid: 2,
    advbase: 2,
    enabled: false,
    sync_status: "out_of_sync",
    last_sync_at: "2026-10-29T10:00:00Z",
    nodes: [
      {
        id: "node-3",
        device_id: "device-1",
        role: "primary",
        advskew: 0,
      },
    ],
    created_at: "2026-01-16T09:00:00Z",
    updated_at: "2026-10-29T12:00:00Z",
  },
];

async function renderHaPage() {
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
          <MemoryRouter initialEntries={["/ha"]}>
            <HaPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(haClustersMock).toHaveBeenCalled());

  return { store };
}

describe("HaPage", () => {
  beforeEach(() => {
    haClustersMock.mockReset();
    devicesListMock.mockReset();
    sitesListMock.mockReset();

    haClustersMock.mockResolvedValue({ items: MOCK_CLUSTERS, meta: { total: 2, page: 1, size: 25 } });
    devicesListMock.mockResolvedValue({ items: MOCK_DEVICES, meta: { total: 2, page: 1, size: 200 } });
    sitesListMock.mockResolvedValue({ items: MOCK_SITES, meta: { total: 1, page: 1, size: 200 } });
  });

  it("renders the page header and HA clusters table", async () => {
    await renderHaPage();

    expect(await screen.findByRole("heading", { name: "High availability" })).toBeInTheDocument();
    expect(screen.getByText("HQ-CARP-Cluster")).toBeInTheDocument();
    expect(screen.getByText("Branch-CARP-Cluster")).toBeInTheDocument();
  });

  it("shows virtual IP addresses", async () => {
    await renderHaPage();

    expect(screen.getByText("10.0.0.254")).toBeInTheDocument();
    expect(screen.getByText("192.168.1.254")).toBeInTheDocument();
  });

  it("shows device names in nodes", async () => {
    await renderHaPage();

    expect(screen.getAllByText("fw-primary-01").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("fw-secondary-01").length).toBeGreaterThanOrEqual(1);
  });

  it("shows enabled/disabled state", async () => {
    await renderHaPage();

    expect(screen.getAllByText("Enabled").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Disabled").length).toBeGreaterThanOrEqual(1);
  });

  it("renders search input", async () => {
    await renderHaPage();

    expect(screen.getByPlaceholderText("Search clusters")).toBeInTheDocument();
  });

  it("renders new cluster button", async () => {
    await renderHaPage();

    expect(screen.getByRole("button", { name: "New cluster" })).toBeInTheDocument();
  });

  it("shows clusters count in header", async () => {
    await renderHaPage();

    expect(screen.getAllByText(/clusters/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows enabled count chip", async () => {
    await renderHaPage();

    expect(screen.getByText("1 enabled")).toBeInTheDocument();
  });

  it("opens create cluster dialog", async () => {
    await renderHaPage();

    await screen.findByRole("button", { name: "New cluster" }).then(btn => btn.click());

    expect(await screen.findByText("New CARP cluster")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Create cluster" })).toBeInTheDocument();
  });
});