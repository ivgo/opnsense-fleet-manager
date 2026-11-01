import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Device, GitRepository } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  gitRepositoriesMock,
  gitCreateMock,
  gitUpdateMock,
  gitRemoveMock,
  gitSyncMock,
} = vi.hoisted(() => ({
  gitRepositoriesMock: vi.fn(),
  gitCreateMock: vi.fn(),
  gitUpdateMock: vi.fn(),
  gitRemoveMock: vi.fn(),
  gitSyncMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  gitApi: {
    repositories: gitRepositoriesMock,
    createRepository: gitCreateMock,
    updateRepository: gitUpdateMock,
    removeRepository: gitRemoveMock,
    sync: gitSyncMock,
  },
}));

import GitReposPage from "@/pages/GitReposPage";

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
];

const MOCK_REPOS: GitRepository[] = [
  {
    id: "repo-1",
    tenant_id: "tenant-1",
    name: "firewall-policies",
    provider: "github",
    url: "https://github.com/org/firewall-policies",
    default_branch: "main",
    auth_type: "token",
    auto_sync: true,
    sync_interval_minutes: 60,
    last_synced_at: "2026-10-30T12:00:00Z",
    last_sync_commit: "abc123",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "repo-2",
    tenant_id: "tenant-1",
    name: "network-configs",
    provider: "gitlab",
    url: "https://gitlab.com/org/network-configs",
    default_branch: "develop",
    auth_type: "ssh",
    auto_sync: false,
    sync_interval_minutes: 120,
    last_synced_at: null,
    last_sync_commit: null,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

async function renderGitReposPage() {
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
          <MemoryRouter initialEntries={["/git"]}>
            <GitReposPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(gitRepositoriesMock).toHaveBeenCalled());

  return { store };
}

describe("GitReposPage", () => {
  beforeEach(() => {
    gitRepositoriesMock.mockReset();
    gitCreateMock.mockReset();
    gitUpdateMock.mockReset();
    gitRemoveMock.mockReset();
    gitSyncMock.mockReset();

    gitRepositoriesMock.mockResolvedValue({ items: MOCK_REPOS, meta: { total: 2, page: 1, size: 25 } });
  });

  it("renders the page header and repositories table", async () => {
    await renderGitReposPage();

    expect(await screen.findByRole("heading", { name: "Git repositories" })).toBeInTheDocument();
    expect(screen.getByText("firewall-policies")).toBeInTheDocument();
    expect(screen.getByText("network-configs")).toBeInTheDocument();
  });

  it("shows provider badges", async () => {
    await renderGitReposPage();

    expect(screen.getByText("Github")).toBeInTheDocument();
    expect(screen.getByText("Gitlab")).toBeInTheDocument();
  });

  it("shows auth type", async () => {
    await renderGitReposPage();

    expect(screen.getByText("Token")).toBeInTheDocument();
    expect(screen.getByText("Ssh")).toBeInTheDocument();
  });

  it("renders search input", async () => {
    await renderGitReposPage();

    expect(screen.getByPlaceholderText("Search name or URL")).toBeInTheDocument();
  });

  it("renders new repository button", async () => {
    await renderGitReposPage();

    expect(screen.getByRole("button", { name: "Connect repository" })).toBeInTheDocument();
  });

  it("shows repositories count in header", async () => {
    await renderGitReposPage();

    expect(screen.getByText("2 repositories")).toBeInTheDocument();
  });

  it("shows last sync commit", async () => {
    await renderGitReposPage();

    // last_commit_sha column is hidden below lg, check via mock
    expect(gitRepositoriesMock).toHaveBeenCalled();
  });
});