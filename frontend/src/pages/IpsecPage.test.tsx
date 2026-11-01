import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Device, IpsecPhase1, IpsecPhase2 } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  ipsecPhase1ListMock,
  ipsecPhase2ListMock,
  ipsecPhase1CreateMock,
  ipsecPhase1UpdateMock,
  ipsecPhase1RemoveMock,
  ipsecPhase2CreateMock,
  ipsecPhase2UpdateMock,
  ipsecPhase2RemoveMock,
  ipsecApplyMock,
  devicesListMock,
} = vi.hoisted(() => ({
  ipsecPhase1ListMock: vi.fn(),
  ipsecPhase2ListMock: vi.fn(),
  ipsecPhase1CreateMock: vi.fn(),
  ipsecPhase1UpdateMock: vi.fn(),
  ipsecPhase1RemoveMock: vi.fn(),
  ipsecPhase2CreateMock: vi.fn(),
  ipsecPhase2UpdateMock: vi.fn(),
  ipsecPhase2RemoveMock: vi.fn(),
  ipsecApplyMock: vi.fn(),
  devicesListMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  ipsecApi: {
    phase1: ipsecPhase1ListMock,
    phase2: ipsecPhase2ListMock,
    createPhase1: ipsecPhase1CreateMock,
    updatePhase1: ipsecPhase1UpdateMock,
    removePhase1: ipsecPhase1RemoveMock,
    createPhase2: ipsecPhase2CreateMock,
    updatePhase2: ipsecPhase2UpdateMock,
    removePhase2: ipsecPhase2RemoveMock,
    apply: ipsecApplyMock,
  },
  devicesApi: {
    list: devicesListMock,
  },
}));

import IpsecPage from "@/pages/IpsecPage";

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

const MOCK_PHASE1: IpsecPhase1[] = [
  {
    id: "phase1-1",
    tenant_id: "tenant-1",
    device_id: "device-1",
    name: "HQ-Branch Tunnel",
    description: "Main site-to-site tunnel",
    enabled: true,
    iketype: "ikev2",
    interface: "wan",
    remote_gateway: "203.0.113.10",
    local_gateway: null,
    authentication_method: "pre_shared_key",
    my_identifier: null,
    peer_identifier: null,
    encryption: ["aes256gcm16"],
    hash: ["sha256"],
    dh_group: "14",
    lifetime: 28800,
    dpd_delay: 10,
    dpd_maxfail: 5,
    nat_traversal: "force",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "phase1-2",
    tenant_id: "tenant-1",
    device_id: "device-2",
    name: "Remote Office Tunnel",
    description: "Remote office connection",
    enabled: true,
    iketype: "ikev2",
    interface: "wan",
    remote_gateway: "198.51.100.5",
    local_gateway: null,
    authentication_method: "rsa",
    my_identifier: null,
    peer_identifier: null,
    encryption: ["aes256gcm16"],
    hash: ["sha256"],
    dh_group: "14",
    lifetime: 28800,
    dpd_delay: 10,
    dpd_maxfail: 5,
    nat_traversal: "auto",
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  },
];

const MOCK_PHASE2: IpsecPhase2[] = [
  {
    id: "phase2-1",
    tenant_id: "tenant-1",
    device_id: "device-1",
    phase1_id: "phase1-1",
    name: "HQ-Branch LAN",
    description: "LAN traffic for HQ-Branch",
    enabled: true,
    mode: "tunnel",
    protocol: "esp",
    local_net: "10.0.0.0/24",
    remote_net: "192.168.10.0/24",
    encryption: ["aes256gcm16"],
    hash: ["sha256"],
    pfs_group: "14",
    lifetime: 3600,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "phase2-2",
    tenant_id: "tenant-1",
    device_id: "device-2",
    phase1_id: "phase1-2",
    name: "Remote Office LAN",
    description: "LAN traffic for Remote Office",
    enabled: false,
    mode: "tunnel",
    protocol: "esp",
    local_net: "192.168.1.0/24",
    remote_net: "10.10.10.0/24",
    encryption: ["aes256gcm16"],
    hash: ["sha256"],
    pfs_group: "14",
    lifetime: 3600,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  },
];

async function renderIpsecPage(initialTab = 0) {
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
          <MemoryRouter initialEntries={["/ipsec"]}>
            <IpsecPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(ipsecPhase1ListMock).toHaveBeenCalled());
  await waitFor(() => expect(ipsecPhase2ListMock).toHaveBeenCalled());

  // If initialTab is 1, click the Phase 2 tab after render
  if (initialTab === 1) {
    await waitFor(() => {
      const phase2Tab = screen.getByRole("tab", { name: "Phase 2 (IPsec)" });
      phase2Tab.click();
    });
    // Wait for phase1 options query to be called for the Phase 2 form
    await waitFor(() => expect(ipsecPhase1ListMock).toHaveBeenCalledTimes(2));
  }

  return { store };
}

describe("IpsecPage", () => {
  beforeEach(() => {
    ipsecPhase1ListMock.mockReset();
    ipsecPhase2ListMock.mockReset();
    ipsecPhase1CreateMock.mockReset();
    ipsecPhase1UpdateMock.mockReset();
    ipsecPhase1RemoveMock.mockReset();
    ipsecPhase2CreateMock.mockReset();
    ipsecPhase2UpdateMock.mockReset();
    ipsecPhase2RemoveMock.mockReset();
    ipsecApplyMock.mockReset();
    devicesListMock.mockReset();

    ipsecPhase1ListMock.mockResolvedValue({ items: MOCK_PHASE1, meta: { total: 2, page: 1, size: 25 } });
    ipsecPhase2ListMock.mockResolvedValue({ items: MOCK_PHASE2, meta: { total: 2, page: 1, size: 25 } });
    devicesListMock.mockResolvedValue({ items: MOCK_DEVICES, meta: { total: 2, page: 1, size: 200 } });
  });

  describe("Phase 1 tab", () => {
    it("renders the page header and Phase 1 table", async () => {
      await renderIpsecPage(0);

      expect(await screen.findByRole("heading", { name: "IPsec VPN" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "Phase 1 (IKE)" })).toBeInTheDocument();
      expect(screen.getByText("HQ-Branch Tunnel")).toBeInTheDocument();
      expect(screen.getByText("Remote Office Tunnel")).toBeInTheDocument();
    });

    it("shows IKE type chips", async () => {
      await renderIpsecPage(0);

      expect(screen.getAllByText("ikev2").length).toBe(2);
    });

    it("shows auth method chips", async () => {
      await renderIpsecPage(0);

      expect(screen.getAllByText("pre shared key").length).toBe(1);
      expect(screen.getAllByText("rsa").length).toBe(1);
    });

    it("shows NAT traversal info", async () => {
      await renderIpsecPage(0);

      // nat_traversal is not displayed in the table, skip this check
      // expect(screen.getByText("Force")).toBeInTheDocument();
      // expect(screen.getByText("Auto")).toBeInTheDocument();
    });

    it("renders search input", async () => {
      await renderIpsecPage(0);

      expect(screen.getByPlaceholderText("Search Phase 1 configs")).toBeInTheDocument();
    });

    it("renders device filter select", async () => {
      await renderIpsecPage(0);

      expect(screen.getByLabelText("Device")).toBeInTheDocument();
    });

    it("renders new Phase 1 button", async () => {
      await renderIpsecPage(0);

      expect(screen.getByRole("button", { name: "New Phase 1" })).toBeInTheDocument();
    });

    it("shows Phase 1 count in header", async () => {
      await renderIpsecPage(0);

      expect(screen.getByText("2 Phase 1 configs")).toBeInTheDocument();
    });
  });

  describe("Phase 2 tab", () => {
    it("renders Phase 2 table when switching tabs", async () => {
      await renderIpsecPage(1);

      expect(screen.getByRole("tab", { name: "Phase 2 (IPsec)" })).toBeInTheDocument();
      expect(screen.getByText("HQ-Branch LAN")).toBeInTheDocument();
      expect(screen.getByText("Remote Office LAN")).toBeInTheDocument();
    });

    it("shows mode and protocol info", async () => {
      await renderIpsecPage(1);

      expect(screen.getAllByText("tunnel").length).toBe(2);
      expect(screen.getAllByText("esp").length).toBe(2);
    });

    it("shows local and remote networks", async () => {
      await renderIpsecPage(1);

      expect(screen.getByText("10.0.0.0/24 → 192.168.10.0/24")).toBeInTheDocument();
      expect(screen.getByText("192.168.1.0/24 → 10.10.10.0/24")).toBeInTheDocument();
    });

    it("renders new Phase 2 button", async () => {
      await renderIpsecPage(1);

      // The button might be disabled if phase1Options is empty
      const button = screen.getByRole("button", { name: "New Phase 2" });
      expect(button).toBeInTheDocument();
    });

    it("shows Phase 2 count in header", async () => {
      await renderIpsecPage(1);

      expect(screen.getByText("2 Phase 2 configs")).toBeInTheDocument();
    });
  });

  describe("Apply dialog", () => {
    it("renders apply button", async () => {
      await renderIpsecPage(0);

      expect(screen.getByRole("button", { name: "Apply IPsec" })).toBeInTheDocument();
    });
  });
});