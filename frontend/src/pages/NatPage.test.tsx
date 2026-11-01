import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Device, NatRule } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  natListMock,
  devicesListMock,
  natCreateMock,
  natUpdateMock,
  natRemoveMock,
  natApplyMock,
} = vi.hoisted(() => ({
  natListMock: vi.fn(),
  devicesListMock: vi.fn(),
  natCreateMock: vi.fn(),
  natUpdateMock: vi.fn(),
  natRemoveMock: vi.fn(),
  natApplyMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  natApi: {
    list: natListMock,
    create: natCreateMock,
    update: natUpdateMock,
    remove: natRemoveMock,
    apply: natApplyMock,
  },
  devicesApi: {
    list: devicesListMock,
  },
}));

import NatPage from "@/pages/NatPage";

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

const MOCK_NAT_RULES: NatRule[] = [
  {
    id: "nat-1",
    tenant_id: "tenant-1",
    device_id: "device-1",
    name: "Web Server Port Forward",
    description: "Forward HTTP/HTTPS to web server",
    type: "port_forward",
    interface: "wan",
    protocol: "tcp",
    source: "any",
    destination: "wan",
    destination_port: "80,443",
    target: "10.0.0.10",
    target_port: "80,443",
    enabled: true,
    order_index: 10,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "nat-2",
    tenant_id: "tenant-1",
    device_id: "device-1",
    name: "Outbound NAT",
    description: "Default outbound NAT for LAN",
    type: "outbound",
    interface: "wan",
    protocol: "any",
    source: "10.0.0.0/24",
    destination: "any",
    destination_port: "",
    target: "",
    target_port: "",
    enabled: true,
    order_index: 0,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  },
];

async function renderNatPage() {
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
          <MemoryRouter initialEntries={["/nat"]}>
            <NatPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(natListMock).toHaveBeenCalled());

  return { store };
}

describe("NatPage", () => {
  beforeEach(() => {
    natListMock.mockReset();
    devicesListMock.mockReset();
    natCreateMock.mockReset();
    natUpdateMock.mockReset();
    natRemoveMock.mockReset();
    natApplyMock.mockReset();

    natListMock.mockResolvedValue({ items: MOCK_NAT_RULES, meta: { total: 2, page: 1, size: 25 } });
    devicesListMock.mockResolvedValue({ items: MOCK_DEVICES, meta: { total: 2, page: 1, size: 200 } });
  });

  it("renders the page header and NAT table", async () => {
    await renderNatPage();

    expect(await screen.findByRole("heading", { name: "NAT" })).toBeInTheDocument();
    expect(screen.getByText("Web Server Port Forward")).toBeInTheDocument();
    expect(screen.getByText("Outbound NAT")).toBeInTheDocument();
  });

  it("shows NAT type chips", async () => {
    await renderNatPage();

    expect(screen.getByText("Port Forward")).toBeInTheDocument();
    expect(screen.getByText("Outbound")).toBeInTheDocument();
  });

  it("renders search input", async () => {
    await renderNatPage();

    expect(screen.getByPlaceholderText("Search rule name")).toBeInTheDocument();
  });

  it("renders type filter select", async () => {
    await renderNatPage();

    expect(screen.getByLabelText("Type")).toBeInTheDocument();
  });

  it("renders device filter select", async () => {
    await renderNatPage();

    expect(screen.getByLabelText("Device")).toBeInTheDocument();
  });

  it("renders new NAT rule button", async () => {
    await renderNatPage();

    expect(screen.getByRole("button", { name: "New NAT rule" })).toBeInTheDocument();
  });

  it("renders apply NAT button", async () => {
    await renderNatPage();

    expect(screen.getByRole("button", { name: "Apply NAT" })).toBeInTheDocument();
  });

  it("shows rules count in header", async () => {
    await renderNatPage();

    expect(screen.getByText("2 rules")).toBeInTheDocument();
  });

  it("shows devices count in header", async () => {
    await renderNatPage();

    expect(screen.getByText("2 devices")).toBeInTheDocument();
  });

  it("shows protocol and match info in table", async () => {
    await renderNatPage();

    expect(screen.getByText("tcp any → wan:80,443")).toBeInTheDocument();
    expect(screen.getByText("any 10.0.0.0/24 → any")).toBeInTheDocument();
  });
});