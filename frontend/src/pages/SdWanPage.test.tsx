import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Device, Topology } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  sdwanTopologiesMock,
  sdwanCreateTopologyMock,
  sdwanUpdateTopologyMock,
  sdwanRemoveTopologyMock,
  sdwanDeployMock,
  devicesListMock,
} = vi.hoisted(() => ({
  sdwanTopologiesMock: vi.fn(),
  sdwanCreateTopologyMock: vi.fn(),
  sdwanUpdateTopologyMock: vi.fn(),
  sdwanRemoveTopologyMock: vi.fn(),
  sdwanDeployMock: vi.fn(),
  devicesListMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  sdwanApi: {
    topologies: sdwanTopologiesMock,
    createTopology: sdwanCreateTopologyMock,
    updateTopology: sdwanUpdateTopologyMock,
    removeTopology: sdwanRemoveTopologyMock,
    deploy: sdwanDeployMock,
  },
  devicesApi: {
    list: devicesListMock,
  },
}));

import SdWanPage from "@/pages/SdWanPage";

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
    name: "fw-hq-01",
    hostname: "fw-hq-01.example.com",
    description: "HQ firewall",
    ip_address: "10.0.0.1",
    api_port: 443,
    site_id: "site-1",
    group_id: "group-1",
    serial_number: "FW123456",
    model: "OPNsense",
    is_ha: false,
    ha_role: null,
    tags: ["hq"],
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
    firmware_version: "25.7.1",
    last_seen_at: "2026-10-30T12:00:00Z",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

const MOCK_TOPOLOGIES: Topology[] = [
  {
    id: "topo-1",
    tenant_id: "tenant-1",
    name: "Hub-Spoke VPN",
    description: "Main hub-spoke topology",
    topology_type: "hub_spoke",
    hub_device_ids: ["device-1"],
    spoke_device_ids: ["device-2"],
    routing_config: '{"protocol": "ospf", "area": "0.0.0.0"}',
    status: "deployed",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "topo-2",
    tenant_id: "tenant-1",
    name: "Full Mesh Backup",
    description: "Full mesh for redundancy",
    topology_type: "full_mesh",
    hub_device_ids: [],
    spoke_device_ids: ["device-1", "device-2"],
    routing_config: '{"protocol": "bgp"}',
    status: "draft",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

async function renderSdWanPage() {
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
          <MemoryRouter initialEntries={["/sdwan"]}>
            <SdWanPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(sdwanTopologiesMock).toHaveBeenCalled());
  await waitFor(() => expect(devicesListMock).toHaveBeenCalled());

  return { store };
}

describe("SdWanPage", () => {
  beforeEach(() => {
    sdwanTopologiesMock.mockReset();
    sdwanCreateTopologyMock.mockReset();
    sdwanUpdateTopologyMock.mockReset();
    sdwanRemoveTopologyMock.mockReset();
    sdwanDeployMock.mockReset();
    devicesListMock.mockReset();

    sdwanTopologiesMock.mockResolvedValue({ items: MOCK_TOPOLOGIES, meta: { total: 2, page: 1, size: 25 } });
    devicesListMock.mockResolvedValue({ items: MOCK_DEVICES, meta: { total: 2, page: 1, size: 200 } });
  });

  it("renders the page header and topologies table", async () => {
    await renderSdWanPage();

    expect(await screen.findByRole("heading", { name: "SD-WAN" })).toBeInTheDocument();
    expect(screen.getAllByText("Hub-Spoke VPN").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Full Mesh Backup")).toBeInTheDocument();
  });

  it("shows topology type badges", async () => {
    await renderSdWanPage();

    expect(screen.getByText("hub_spoke")).toBeInTheDocument();
    expect(screen.getByText("full_mesh")).toBeInTheDocument();
  });

  it("shows status badges", async () => {
    await renderSdWanPage();

    expect(screen.getAllByText("Deployed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("renders new topology button", async () => {
    await renderSdWanPage();

    expect(screen.getByRole("button", { name: "New topology" })).toBeInTheDocument();
  });

  it("shows topologies count in header", async () => {
    await renderSdWanPage();

    expect(screen.getAllByText("2 topologies").length).toBeGreaterThanOrEqual(1);
  });
});