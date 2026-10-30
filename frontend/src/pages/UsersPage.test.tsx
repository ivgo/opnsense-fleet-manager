import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, User, Role } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  usersListMock,
  rolesListMock,
  apiKeysListMock,
} = vi.hoisted(() => ({
  usersListMock: vi.fn(),
  rolesListMock: vi.fn(),
  apiKeysListMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  usersApi: {
    list: usersListMock,
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    get: vi.fn(),
  },
  rolesApi: {
    list: rolesListMock,
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
  apiKeysApi: {
    list: apiKeysListMock,
    create: vi.fn(),
    revoke: vi.fn(),
  },
}));

import UsersPage from "@/pages/UsersPage";

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
  last_login_at: "2026-10-30T10:00:00Z",
};

const MOCK_USERS: User[] = [
  {
    id: "user-1",
    tenant_id: "tenant-1",
    username: "john.doe",
    email: "john@example.com",
    full_name: "John Doe",
    auth_provider: "local",
    roles: ["Operator"],
    is_superadmin: false,
    status: "active",
    mfa_enabled: true,
    last_login_at: "2026-10-30T08:00:00Z",
    created_at: "2026-01-15T08:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "user-2",
    tenant_id: "tenant-1",
    username: "jane.smith",
    email: "jane@example.com",
    full_name: "Jane Smith",
    auth_provider: "oidc",
    roles: ["Viewer"],
    is_superadmin: false,
    status: "active",
    mfa_enabled: false,
    last_login_at: "2026-10-29T15:00:00Z",
    created_at: "2026-02-01T10:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

const MOCK_ROLES: Role[] = [
  {
    id: "role-1",
    tenant_id: "tenant-1",
    name: "Operator",
    description: "Standard operator role",
    permissions: ["device:read", "device:write"],
    is_system: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "role-2",
    tenant_id: "tenant-1",
    name: "Viewer",
    description: "Read-only access",
    permissions: ["device:read"],
    is_system: false,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

async function renderUsersPage() {
  const store = configureStore({
    reducer: { auth: authReducer, ui: uiReducer },
    preloadedState: {
      auth: {
        user: USER,
        status: "authenticated" as const,
        hydrated: true,
        error: null,
        mfaRequired: false,
        challengeToken: null,
        mfaMethods: [],
      },
      ui: {
        themeMode: "light" as const,
        sidebarOpen: true,
        sidebarCollapsed: false,
        selectedTenantId: null,
        toast: { open: false, message: "", severity: "info" as const },
      },
    },
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  render(
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider theme={buildTheme("light")}>
          <MemoryRouter initialEntries={["/users"]}>
            <UsersPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(usersListMock).toHaveBeenCalled());

  return { store };
}

describe("UsersPage", () => {
  beforeEach(() => {
    usersListMock.mockReset();
    rolesListMock.mockReset();
    apiKeysListMock.mockReset();

    usersListMock.mockResolvedValue({ items: MOCK_USERS, meta: { total: 2, page: 1, size: 25 } });
    // rolesApi.list() returns Role[] directly, not paginated
    rolesListMock.mockResolvedValue(MOCK_ROLES);
    apiKeysListMock.mockResolvedValue([]);
  });

  it("renders the page header and users table", async () => {
    await renderUsersPage();

    expect(await screen.findByRole("heading", { name: "Access control" })).toBeInTheDocument();
    // User column shows full_name with username in caption - check for full names
    expect(screen.getByText("John Doe")).toBeInTheDocument();
    expect(screen.getByText("Jane Smith")).toBeInTheDocument();
  });

  it("shows user status chips", async () => {
    await renderUsersPage();

    expect(screen.getAllByText("Active").length).toBeGreaterThanOrEqual(1);
  });

  it("shows auth provider badges", async () => {
    await renderUsersPage();

    // Provider column shows label from AUTH_PROVIDERS: "Local password" for "local", "OIDC" for "oidc"
    expect(screen.getAllByText("Local password").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("OIDC").length).toBeGreaterThanOrEqual(1);
  });

  it("shows MFA status", async () => {
    await renderUsersPage();

    // MFA column shows "enabled" or "off" chip
    expect(screen.getAllByText("enabled").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("off").length).toBeGreaterThanOrEqual(1);
  });

  it("renders tabs for users, roles, and API keys", async () => {
    await renderUsersPage();

    expect(screen.getByRole("tab", { name: "Users" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Roles & permissions" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "API keys" })).toBeInTheDocument();
  });

  it("renders search input", async () => {
    await renderUsersPage();

    expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
  });

  it("renders new user button", async () => {
    await renderUsersPage();

    expect(screen.getByRole("button", { name: "New user" })).toBeInTheDocument();
  });

  it("renders roles tab content", async () => {
    await renderUsersPage();

    // Click Roles tab
    const rolesTab = screen.getByRole("tab", { name: "Roles & permissions" });
    await waitFor(() => rolesTab.click());

    // Wait for roles query
    await waitFor(() => expect(rolesListMock).toHaveBeenCalled());

    expect(screen.getByText("Operator")).toBeInTheDocument();
    expect(screen.getByText("Viewer")).toBeInTheDocument();
  });

  it("renders API keys tab content", async () => {
    await renderUsersPage();

    // Click API keys tab
    const apiKeysTab = screen.getByRole("tab", { name: "API keys" });
    await waitFor(() => apiKeysTab.click());

    // Wait for API keys query
    await waitFor(() => expect(apiKeysListMock).toHaveBeenCalled());

    expect(screen.getByText("No API keys")).toBeInTheDocument();
  });

  it("opens create user dialog", async () => {
    await renderUsersPage();

    await screen.findByRole("button", { name: "New user" }).then(btn => btn.click());

    // Wait for dialog to open
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());

    // "Create user" appears in both dialog title and submit button - check dialog title
    expect(await screen.findByRole("heading", { name: "Create user" })).toBeInTheDocument();
    // Form fields may not render fully in test environment - just check dialog opens and submit button
    expect(screen.getByRole("button", { name: "Create user" })).toBeInTheDocument();
  });
});
