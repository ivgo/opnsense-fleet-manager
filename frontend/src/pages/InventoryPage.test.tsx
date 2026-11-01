import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, ClientDevice } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  inventoryListMock,
} = vi.hoisted(() => ({
  inventoryListMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  inventoryApi: {
    list: inventoryListMock,
    block: vi.fn(),
    unblock: vi.fn(),
    pause: vi.fn(),
  },
}));

import { InventoryPage } from "@/pages/InventoryPage";

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

const MOCK_CLIENTS: ClientDevice[] = [
  {
    id: "client-1",
    tenant_id: "tenant-1",
    mac_address: "00:11:22:33:44:55",
    ip_address: "10.0.1.10",
    hostname: "sw-access-01",
    source: "arp",
    status: "active",
    vendor: "Cisco",
    model: "Catalyst 9200",
    first_seen_at: "2026-01-15T08:00:00Z",
    last_seen_at: "2026-10-30T12:00:00Z",
    created_at: "2026-01-15T08:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "client-2",
    tenant_id: "tenant-1",
    mac_address: "AA:BB:CC:DD:EE:FF",
    ip_address: "10.0.0.1",
    hostname: "rtr-edge-01",
    source: "dhcp",
    status: "active",
    vendor: "Juniper",
    model: "SRX300",
    first_seen_at: "2026-02-01T10:00:00Z",
    last_seen_at: "2026-10-30T11:00:00Z",
    created_at: "2026-02-01T10:00:00Z",
    updated_at: "2026-10-30T11:00:00Z",
  },
];

async function renderInventoryPage() {
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
          <MemoryRouter initialEntries={["/inventory"]}>
            <InventoryPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(inventoryListMock).toHaveBeenCalled());

  return { store };
}

describe("InventoryPage", () => {
  beforeEach(() => {
    inventoryListMock.mockReset();

    inventoryListMock.mockResolvedValue(MOCK_CLIENTS);
  });

  it("renders the page header and client table", async () => {
    await renderInventoryPage();

    expect(await screen.findByRole("heading", { name: "Client Inventory" })).toBeInTheDocument();
    expect(screen.getByText("sw-access-01")).toBeInTheDocument();
    expect(screen.getByText("rtr-edge-01")).toBeInTheDocument();
  });

  it("shows MAC addresses in table", async () => {
    await renderInventoryPage();

    expect(screen.getByText("00:11:22:33:44:55")).toBeInTheDocument();
    expect(screen.getByText("AA:BB:CC:DD:EE:FF")).toBeInTheDocument();
  });

  it("shows IP addresses", async () => {
    await renderInventoryPage();

    expect(screen.getByText("10.0.1.10")).toBeInTheDocument();
    expect(screen.getByText("10.0.0.1")).toBeInTheDocument();
  });

  it("shows hostnames in table", async () => {
    await renderInventoryPage();

    expect(screen.getByText("sw-access-01")).toBeInTheDocument();
    expect(screen.getByText("rtr-edge-01")).toBeInTheDocument();
  });

  it("shows source chips", async () => {
    await renderInventoryPage();

    expect(screen.getByText("ARP")).toBeInTheDocument();
    expect(screen.getByText("DHCP")).toBeInTheDocument();
  });

  it("shows status chips", async () => {
    await renderInventoryPage();

    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
  });

  it("renders search input", async () => {
    await renderInventoryPage();

    expect(screen.getByPlaceholderText("Search MAC, IP, hostname...")).toBeInTheDocument();
  });

  it("renders status filter select", async () => {
    await renderInventoryPage();

    expect(screen.getByPlaceholderText("Status")).toBeInTheDocument();
  });

  it("renders source filter select", async () => {
    await renderInventoryPage();

    expect(screen.getByPlaceholderText("Source")).toBeInTheDocument();
  });

  it("renders block selected button", async () => {
    await renderInventoryPage();

    expect(screen.getByRole("button", { name: "Block Selected" })).toBeInTheDocument();
  });
});