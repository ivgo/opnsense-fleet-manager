import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Device, DeviceGroup, Site } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  devicesListMock,
  devicesSummaryMock,
  sitesListMock,
  groupsListMock,
  devicesCreateMock,
  devicesUpdateMock,
  devicesRemoveMock,
  devicesMaintenanceMock,
  devicesDiscoverMock,
  bulkDevicesMock,
  bulkImportCsvMock,
  bulkExportCsvMock,
} = vi.hoisted(() => ({
  devicesListMock: vi.fn(),
  devicesSummaryMock: vi.fn(),
  sitesListMock: vi.fn(),
  groupsListMock: vi.fn(),
  devicesCreateMock: vi.fn(),
  devicesUpdateMock: vi.fn(),
  devicesRemoveMock: vi.fn(),
  devicesMaintenanceMock: vi.fn(),
  devicesDiscoverMock: vi.fn(),
  bulkDevicesMock: vi.fn(),
  bulkImportCsvMock: vi.fn(),
  bulkExportCsvMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  devicesApi: {
    list: devicesListMock,
    summary: devicesSummaryMock,
    create: devicesCreateMock,
    update: devicesUpdateMock,
    remove: devicesRemoveMock,
    maintenance: devicesMaintenanceMock,
    discover: devicesDiscoverMock,
  },
  sitesApi: {
    list: sitesListMock,
  },
  groupsApi: {
    list: groupsListMock,
  },
  bulkApi: {
    devices: bulkDevicesMock,
    importCsv: bulkImportCsvMock,
    exportCsv: bulkExportCsvMock,
  },
}));

import DevicesPage from "@/pages/DevicesPage";

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
    id: "1",
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
    id: "2",
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
    status: "offline",
    connection_status: "disconnected",
    firmware_version: "25.7.0",
    last_seen_at: "2026-10-29T12:00:00Z",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-29T12:00:00Z",
  },
];

const MOCK_SITES: Site[] = [
  { id: "site-1", tenant_id: "tenant-1", name: "Headquarters", description: "Main office", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  { id: "site-2", tenant_id: "tenant-1", name: "Branch Office", description: "Remote office", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
];

const MOCK_GROUPS: DeviceGroup[] = [
  { id: "group-1", tenant_id: "tenant-1", name: "Firewalls", description: "All firewalls", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  { id: "group-2", tenant_id: "tenant-1", name: "Switches", description: "All switches", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
];

const MOCK_SUMMARY = {
  total: 2,
  online: 1,
  offline: 1,
  error: 0,
  maintenance: 0,
  unregistered: 0,
};

async function renderDevicesPage() {
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
          <MemoryRouter initialEntries={["/devices"]}>
            <DevicesPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(devicesListMock).toHaveBeenCalled());

  return { store };
}

describe("DevicesPage", () => {
  beforeEach(() => {
    devicesListMock.mockReset();
    devicesSummaryMock.mockReset();
    sitesListMock.mockReset();
    groupsListMock.mockReset();
    devicesCreateMock.mockReset();
    devicesUpdateMock.mockReset();
    devicesRemoveMock.mockReset();
    devicesMaintenanceMock.mockReset();
    devicesDiscoverMock.mockReset();
    bulkDevicesMock.mockReset();
    bulkImportCsvMock.mockReset();
    bulkExportCsvMock.mockReset();

    devicesListMock.mockResolvedValue({ items: MOCK_DEVICES, meta: { total: 2, page: 1, size: 25 } });
    devicesSummaryMock.mockResolvedValue(MOCK_SUMMARY);
    sitesListMock.mockResolvedValue({ items: MOCK_SITES, meta: { total: 2, page: 1, size: 200 } });
    groupsListMock.mockResolvedValue({ items: MOCK_GROUPS, meta: { total: 2, page: 1, size: 200 } });
  });

  it("renders the page header and device table", async () => {
    await renderDevicesPage();

    expect(await screen.findByRole("heading", { name: "Devices" })).toBeInTheDocument();
    expect(screen.getByText("fw-edge-01")).toBeInTheDocument();
    expect(screen.getByText("fw-branch-01")).toBeInTheDocument();
  });

  it("shows device status chips", async () => {
    await renderDevicesPage();

    expect(await screen.findByText("Online")).toBeInTheDocument();
    expect(await screen.findByText("Offline")).toBeInTheDocument();
  });

  it("renders summary chips in page header", async () => {
    await renderDevicesPage();

    expect(await screen.findByText("2 total")).toBeInTheDocument();
    expect(await screen.findByText("1 online")).toBeInTheDocument();
    expect(await screen.findByText("1 offline")).toBeInTheDocument();
  });

  it("renders search input", async () => {
    await renderDevicesPage();

    expect(screen.getByPlaceholderText("Search name, host, IP or serial")).toBeInTheDocument();
  });

  it("renders status filter select", async () => {
    await renderDevicesPage();

    expect(screen.getByLabelText("Status")).toBeInTheDocument();
  });

  it("renders site filter select", async () => {
    await renderDevicesPage();

    expect(screen.getByLabelText("Site")).toBeInTheDocument();
  });

  it("renders group filter select", async () => {
    await renderDevicesPage();

    expect(screen.getByLabelText("Group")).toBeInTheDocument();
  });

  it("renders register device button", async () => {
    await renderDevicesPage();

    expect(screen.getByRole("button", { name: "Register device" })).toBeInTheDocument();
  });

  it("renders export/import/discover buttons", async () => {
    await renderDevicesPage();

    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import CSV" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discover" })).toBeInTheDocument();
  });

  it("shows pagination info", async () => {
    await renderDevicesPage();

    expect(screen.getByText("2 devices")).toBeInTheDocument();
  });
});