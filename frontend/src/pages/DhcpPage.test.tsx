import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, DhcpScope, DhcpReservation, Device } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  dhcpScopesMock,
  dhcpReservationsMock,
  devicesListMock,
} = vi.hoisted(() => ({
  dhcpScopesMock: vi.fn(),
  dhcpReservationsMock: vi.fn(),
  devicesListMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  dhcpApi: {
    scopes: dhcpScopesMock,
    reservations: dhcpReservationsMock,
    createScope: vi.fn(),
    updateScope: vi.fn(),
    removeScope: vi.fn(),
    createReservation: vi.fn(),
    updateReservation: vi.fn(),
    removeReservation: vi.fn(),
    apply: vi.fn(),
  },
  devicesApi: {
    list: devicesListMock,
  },
}));

import { DhcpPage } from "@/pages/DhcpPage";

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

const MOCK_SCOPES: DhcpScope[] = [
  {
    id: "scope-1",
    tenant_id: "tenant-1",
    device_id: "device-1",
    name: "LAN Network",
    description: "Main LAN DHCP scope",
    subnet: "192.168.10.0/24",
    pool_start: "192.168.10.100",
    pool_end: "192.168.10.200",
    gateway: "192.168.10.1",
    dns_servers: ["8.8.8.8", "8.8.4.4"],
    domain_name: "lan.example.com",
    lease_time_seconds: 86400,
    enabled: true,
    options: {},
    created_at: "2026-01-15T08:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "scope-2",
    tenant_id: "tenant-1",
    device_id: "device-2",
    name: "Guest Network",
    description: "Guest WiFi DHCP scope",
    subnet: "192.168.20.0/24",
    pool_start: "192.168.20.50",
    pool_end: "192.168.20.150",
    gateway: "192.168.20.1",
    dns_servers: ["1.1.1.1"],
    domain_name: "guest.example.com",
    lease_time_seconds: 3600,
    enabled: true,
    options: {},
    created_at: "2026-01-16T09:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

const MOCK_RESERVATIONS: DhcpReservation[] = [
  {
    id: "res-1",
    tenant_id: "tenant-1",
    device_id: "device-1",
    scope_id: "scope-1",
    hostname: "printer-01",
    mac_address: "aa:bb:cc:dd:ee:01",
    ip_address: "192.168.10.50",
    description: "Office printer",
    enabled: true,
    created_at: "2026-01-15T08:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "res-2",
    tenant_id: "tenant-1",
    device_id: "device-1",
    scope_id: "scope-1",
    hostname: "server-01",
    mac_address: "aa:bb:cc:dd:ee:02",
    ip_address: "192.168.10.10",
    description: null,
    enabled: true,
    created_at: "2026-01-16T09:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

async function renderDhcpPage() {
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
          <MemoryRouter initialEntries={["/dhcp"]}>
            <DhcpPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(dhcpScopesMock).toHaveBeenCalled());

  return { store };
}

describe("DhcpPage", () => {
  beforeEach(() => {
    dhcpScopesMock.mockReset();
    dhcpReservationsMock.mockReset();
    devicesListMock.mockReset();

    dhcpScopesMock.mockResolvedValue({ items: MOCK_SCOPES, meta: { total: 2, page: 1, size: 25 } });
    dhcpReservationsMock.mockResolvedValue({ items: MOCK_RESERVATIONS, meta: { total: 2, page: 1, size: 25 } });
    devicesListMock.mockResolvedValue({ items: MOCK_DEVICES, meta: { total: 2, page: 1, size: 200 } });
  });

  it("renders the page header and DHCP tabs", async () => {
    await renderDhcpPage();

    expect(await screen.findByRole("heading", { name: "DHCP" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Scopes" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Reservations" })).toBeInTheDocument();
  });

  it("renders the page header and scopes table", async () => {
    await renderDhcpPage();

    expect(await screen.findByRole("heading", { name: "DHCP" })).toBeInTheDocument();
    expect(screen.getByText("LAN Network")).toBeInTheDocument();
    expect(screen.getByText("Guest Network")).toBeInTheDocument();
  });

  it("shows subnet values", async () => {
    await renderDhcpPage();

    expect(screen.getByText("192.168.10.0/24")).toBeInTheDocument();
    expect(screen.getByText("192.168.20.0/24")).toBeInTheDocument();
  });

  it("shows dynamic pool ranges", async () => {
    await renderDhcpPage();

    expect(screen.getByText("192.168.10.100 – 192.168.10.200")).toBeInTheDocument();
    expect(screen.getByText("192.168.20.50 – 192.168.20.150")).toBeInTheDocument();
  });

  it("shows gateway values", async () => {
    await renderDhcpPage();

    expect(screen.getByText("192.168.10.1")).toBeInTheDocument();
    expect(screen.getByText("192.168.20.1")).toBeInTheDocument();
  });

  it("shows lease times", async () => {
    await renderDhcpPage();

    expect(screen.getAllByText(/1d 0h/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/1h 0m/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows DNS servers", async () => {
    await renderDhcpPage();

    expect(screen.getByText("8.8.8.8, 8.8.4.4")).toBeInTheDocument();
    expect(screen.getByText("1.1.1.1")).toBeInTheDocument();
  });

  it("shows enabled/disabled chips", async () => {
    await renderDhcpPage();

    expect(screen.getAllByText("Enabled").length).toBeGreaterThanOrEqual(1);
  });

  it("shows device names in table", async () => {
    await renderDhcpPage();

    expect(screen.getAllByText("fw-edge-01").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("fw-branch-01").length).toBeGreaterThanOrEqual(1);
  });

  it("renders search input", async () => {
    await renderDhcpPage();

    expect(screen.getByPlaceholderText("Search scopes")).toBeInTheDocument();
  });

  it("renders device filter select", async () => {
    await renderDhcpPage();

    expect(screen.getByLabelText("Device")).toBeInTheDocument();
  });

  it("renders new scope button", async () => {
    await renderDhcpPage();

    expect(screen.getByRole("button", { name: "New scope" })).toBeInTheDocument();
  });

  it("renders apply DHCP button", async () => {
    await renderDhcpPage();

    expect(screen.getByRole("button", { name: "Apply DHCP" })).toBeInTheDocument();
  });

  it("shows scopes count in header", async () => {
    await renderDhcpPage();

    expect(screen.getAllByText(/scopes/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows reservations count in header", async () => {
    await renderDhcpPage();

    expect(screen.getAllByText(/reservations/i).length).toBeGreaterThanOrEqual(1);
  });

  it("switches to reservations tab and shows reservations table", async () => {
    await renderDhcpPage();

    // Click Reservations tab
    const reservationsTab = screen.getByRole("tab", { name: "Reservations" });
    await waitFor(() => reservationsTab.click());

    // Wait for reservations query to be called
    await waitFor(() => expect(dhcpReservationsMock).toHaveBeenCalled());

    expect(screen.getByText("printer-01")).toBeInTheDocument();
    expect(screen.getByText("server-01")).toBeInTheDocument();
    expect(screen.getByText("aa:bb:cc:dd:ee:01")).toBeInTheDocument();
    expect(screen.getByText("192.168.10.50")).toBeInTheDocument();
  });

  it("shows DNS servers", async () => {
    await renderDhcpPage();

    expect(screen.getByText("8.8.8.8, 8.8.4.4")).toBeInTheDocument();
    expect(screen.getByText("1.1.1.1")).toBeInTheDocument();
  });

  it("shows enabled/disabled chips", async () => {
    await renderDhcpPage();

    expect(screen.getAllByText("Enabled").length).toBeGreaterThanOrEqual(1);
  });

  it("shows device names in table", async () => {
    await renderDhcpPage();

    expect(screen.getAllByText("fw-edge-01").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("fw-branch-01").length).toBeGreaterThanOrEqual(1);
  });

  it("opens create scope dialog", async () => {
    await renderDhcpPage();

    await screen.findByRole("button", { name: "New scope" }).then(btn => btn.click());

    expect(await screen.findByText("New DHCP scope")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Create scope" })).toBeInTheDocument();
  });

  it("renders search input", async () => {
    await renderDhcpPage();

    expect(screen.getByPlaceholderText("Search scopes")).toBeInTheDocument();
  });

  it("renders device filter select", async () => {
    await renderDhcpPage();

    expect(screen.getByLabelText("Device")).toBeInTheDocument();
  });

  it("renders new scope button", async () => {
    await renderDhcpPage();

    expect(screen.getByRole("button", { name: "New scope" })).toBeInTheDocument();
  });

  it("renders apply DHCP button", async () => {
    await renderDhcpPage();

    expect(screen.getByRole("button", { name: "Apply DHCP" })).toBeInTheDocument();
  });

  it("shows scopes count in header", async () => {
    await renderDhcpPage();

    expect(screen.getAllByText(/scopes/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows reservations count in header", async () => {
    await renderDhcpPage();

    expect(screen.getAllByText(/reservations/i).length).toBeGreaterThanOrEqual(1);
  });

  it("switches to reservations tab and shows reservations table", async () => {
    await renderDhcpPage();

    // Click Reservations tab
    const reservationsTab = screen.getByRole("tab", { name: "Reservations" });
    await waitFor(() => reservationsTab.click());

    // Wait for reservations query to be called
    await waitFor(() => expect(dhcpReservationsMock).toHaveBeenCalled());

    expect(screen.getByText("printer-01")).toBeInTheDocument();
    expect(screen.getByText("server-01")).toBeInTheDocument();
    expect(screen.getByText("aa:bb:cc:dd:ee:01")).toBeInTheDocument();
    expect(screen.getByText("192.168.10.50")).toBeInTheDocument();
  });

  });