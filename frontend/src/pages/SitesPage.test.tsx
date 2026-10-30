import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Site } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  sitesListMock,
  sitesMapMock,
} = vi.hoisted(() => ({
  sitesListMock: vi.fn(),
  sitesMapMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  sitesApi: {
    list: sitesListMock,
    map: sitesMapMock,
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}));

import SitesPage from "@/pages/SitesPage";

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

const MOCK_SITES: Site[] = [
  {
    id: "site-1",
    tenant_id: "tenant-1",
    name: "Headquarters",
    code: "HQ",
    description: "Main office building",
    address: "123 Main St",
    city: "Berlin",
    country: "DE",
    latitude: 52.52,
    longitude: 13.405,
    timezone: "Europe/Berlin",
    device_count: 5,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "site-2",
    tenant_id: "tenant-1",
    name: "Branch Office",
    code: "BR",
    description: "Remote branch",
    address: "456 Oak Ave",
    city: "Munich",
    country: "DE",
    latitude: 48.1374,
    longitude: 11.5755,
    timezone: "Europe/Berlin",
    device_count: 2,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

const MOCK_MAP = [
  {
    id: "site-1",
    name: "Headquarters",
    code: "HQ",
    city: "Berlin",
    country: "DE",
    latitude: 52.52,
    longitude: 13.405,
    devices_total: 5,
    devices_online: 4,
    devices_offline: 1,
    devices_error: 0,
    worst_severity: "warning",
  },
  {
    id: "site-2",
    name: "Branch Office",
    code: "BR",
    city: "Munich",
    country: "DE",
    latitude: 48.1374,
    longitude: 11.5755,
    devices_total: 2,
    devices_online: 2,
    devices_offline: 0,
    devices_error: 0,
    worst_severity: null,
  },
];

async function renderSitesPage() {
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
          <MemoryRouter initialEntries={["/sites"]}>
            <SitesPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(sitesListMock).toHaveBeenCalled());

  return { store };
}

describe("SitesPage", () => {
  beforeEach(() => {
    sitesListMock.mockReset();
    sitesMapMock.mockReset();

    sitesListMock.mockResolvedValue({ items: MOCK_SITES, meta: { total: 2, page: 1, size: 25 } });
    sitesMapMock.mockResolvedValue(MOCK_MAP);
  });

  it("renders the page header and sites table", async () => {
    await renderSitesPage();

    expect(await screen.findByRole("heading", { name: "Sites" })).toBeInTheDocument();
    expect(screen.getAllByText("Headquarters").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Branch Office").length).toBeGreaterThanOrEqual(1);
  });

  it("shows site codes", async () => {
    await renderSitesPage();

    expect(screen.getByText("HQ")).toBeInTheDocument();
    expect(screen.getByText("BR")).toBeInTheDocument();
  });

  it("shows coordinates in table", async () => {
    await renderSitesPage();

    expect(screen.getByText("52.5200, 13.4050")).toBeInTheDocument();
    expect(screen.getByText("48.1374, 11.5755")).toBeInTheDocument();
  });

  it("shows device count chips", async () => {
    await renderSitesPage();

    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders search input", async () => {
    await renderSitesPage();

    expect(screen.getByPlaceholderText("Search sites")).toBeInTheDocument();
  });

  it("renders new site button", async () => {
    await renderSitesPage();

    expect(screen.getByRole("button", { name: "New site" })).toBeInTheDocument();
  });

  it("shows sites count in header", async () => {
    await renderSitesPage();

    expect(screen.getAllByText(/sites/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows devices count in header", async () => {
    await renderSitesPage();

    expect(screen.getAllByText(/devices/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows online count in header", async () => {
    await renderSitesPage();

    expect(screen.getAllByText(/online/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows geographic distribution map section", async () => {
    await renderSitesPage();

    expect(await screen.findByText("Geographic distribution")).toBeInTheDocument();
  });
});