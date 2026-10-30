import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Backup, Device } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  backupsListMock,
  backupsUsageMock,
  devicesListMock,
} = vi.hoisted(() => ({
  backupsListMock: vi.fn(),
  backupsUsageMock: vi.fn(),
  devicesListMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  backupsApi: {
    list: backupsListMock,
    storageUsage: backupsUsageMock,
    create: vi.fn(),
    verify: vi.fn(),
    download: vi.fn(),
    restore: vi.fn(),
    remove: vi.fn(),
    sweep: vi.fn(),
    retention: vi.fn(),
  },
  devicesApi: {
    list: devicesListMock,
  },
}));

import BackupsPage from "@/pages/BackupsPage";

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

const MOCK_BACKUPS: Backup[] = [
  {
    id: "backup-1",
    tenant_id: "tenant-1",
    device_id: "device-1",
    type: "manual",
    size_bytes: 1024 * 1024 * 5,
    storage_key: "s3://backups/device-1/backup-1.xml.gz",
    checksum_sha256: "a1b2c3d4e5f6789012345678901234567890abcdef",
    firmware_version: "25.7.1",
    is_encrypted: true,
    notes: "Pre-upgrade backup",
    created_at: "2026-10-30T10:00:00Z",
  },
  {
    id: "backup-2",
    tenant_id: "tenant-1",
    device_id: "device-2",
    type: "scheduled",
    size_bytes: 1024 * 1024 * 3,
    storage_key: "s3://backups/device-2/backup-2.xml.gz",
    checksum_sha256: "fedcba0987654321098765432109876543210zyxwv",
    firmware_version: "25.7.0",
    is_encrypted: true,
    notes: null,
    created_at: "2026-10-29T08:00:00Z",
  },
];

async function renderBackupsPage() {
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
          <MemoryRouter initialEntries={["/backups"]}>
            <BackupsPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(backupsListMock).toHaveBeenCalled());

  return { store };
}

describe("BackupsPage", () => {
  beforeEach(() => {
    backupsListMock.mockReset();
    backupsUsageMock.mockReset();
    devicesListMock.mockReset();

    backupsListMock.mockResolvedValue({ items: MOCK_BACKUPS, meta: { total: 2, page: 1, size: 25 } });
    backupsUsageMock.mockResolvedValue({ storage_bytes: 1024 * 1024 * 100 });
    devicesListMock.mockResolvedValue({ items: MOCK_DEVICES, meta: { total: 2, page: 1, size: 500 } });
  });

  it("renders the page header and backups table", async () => {
    await renderBackupsPage();

    expect(await screen.findByRole("heading", { name: "Backups" })).toBeInTheDocument();
    expect(screen.getByText("fw-edge-01")).toBeInTheDocument();
    expect(screen.getByText("fw-branch-01")).toBeInTheDocument();
  });

  it("shows backup type chips", async () => {
    await renderBackupsPage();

    expect(screen.getByText("Manual")).toBeInTheDocument();
    expect(screen.getByText("Scheduled")).toBeInTheDocument();
  });

  it("shows encrypted chips", async () => {
    await renderBackupsPage();

    expect(screen.getAllByText("encrypted").length).toBeGreaterThanOrEqual(1);
  });

  it("shows backup sizes", async () => {
    await renderBackupsPage();

    expect(screen.getByText("5.0 MB")).toBeInTheDocument();
    expect(screen.getByText("3.0 MB")).toBeInTheDocument();
  });

  it("renders storage usage card", async () => {
    await renderBackupsPage();

    expect(await screen.findByText("Object storage used")).toBeInTheDocument();
    expect(screen.getByText("100 MB")).toBeInTheDocument();
  });

  it("renders integrity model card", async () => {
    await renderBackupsPage();

    expect(screen.getByText("Integrity model")).toBeInTheDocument();
    expect(screen.getByText("SHA-256")).toBeInTheDocument();
  });

  it("renders retention card", async () => {
    await renderBackupsPage();

    expect(screen.getAllByText("Retention").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("30 / device")).toBeInTheDocument();
  });

  it("renders new backup button", async () => {
    await renderBackupsPage();

    expect(screen.getByRole("button", { name: "New backup" })).toBeInTheDocument();
  });

  it("renders retention button", async () => {
    await renderBackupsPage();

    expect(screen.getByRole("button", { name: "Retention" })).toBeInTheDocument();
  });

  it("renders back up fleet button", async () => {
    await renderBackupsPage();

    expect(screen.getByRole("button", { name: "Back up fleet" })).toBeInTheDocument();
  });

  it("shows backups count in header", async () => {
    await renderBackupsPage();

    expect(screen.getAllByText(/backups/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders device filter select", async () => {
    await renderBackupsPage();

    expect(screen.getByLabelText("Device")).toBeInTheDocument();
  });

  it("renders type filter select", async () => {
    await renderBackupsPage();

    expect(screen.getByLabelText("Type")).toBeInTheDocument();
  });

  it("opens create backup dialog", async () => {
    await renderBackupsPage();

    await screen.findByRole("button", { name: "New backup" }).then(btn => btn.click());

    expect(await screen.findByText("Create configuration backup")).toBeInTheDocument();
    expect(screen.getByLabelText("Device")).toBeInTheDocument();
    expect(screen.getByLabelText("Backup type")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create backup" })).toBeInTheDocument();
  });
});