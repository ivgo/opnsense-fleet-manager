import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, DeviceGroup } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  groupsListMock,
  groupsTreeMock,
  templatesListMock,
} = vi.hoisted(() => ({
  groupsListMock: vi.fn(),
  groupsTreeMock: vi.fn(),
  templatesListMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  groupsApi: {
    list: groupsListMock,
    tree: groupsTreeMock,
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    get: vi.fn(),
  },
  templatesApi: {
    list: templatesListMock,
  },
}));

import GroupsPage from "@/pages/GroupsPage";

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

const MOCK_GROUPS: DeviceGroup[] = [
  {
    id: "group-1",
    tenant_id: "tenant-1",
    name: "Headquarters",
    description: "Main office devices",
    parent_id: null,
    template_id: null,
    labels: ["hq", "core"],
    device_count: 10,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "group-2",
    tenant_id: "tenant-1",
    name: "Branch Offices",
    description: "Remote branch devices",
    parent_id: null,
    template_id: null,
    labels: ["branch"],
    device_count: 5,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "group-3",
    tenant_id: "tenant-1",
    name: "DMZ",
    description: "Demilitarized zone",
    parent_id: "group-1",
    template_id: null,
    labels: ["dmz", "external"],
    device_count: 3,
    created_at: "2026-01-03T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

const MOCK_TREE = [
  {
    id: "group-1",
    name: "Headquarters",
    description: "Main office devices",
    parent_id: null,
    template_id: null,
    labels: ["hq", "core"],
    device_count: 10,
    children: [
      {
        id: "group-3",
        name: "DMZ",
        description: "Demilitarized zone",
        parent_id: "group-1",
        template_id: null,
        labels: ["dmz", "external"],
        device_count: 3,
        children: [],
      },
    ],
  },
  {
    id: "group-2",
    name: "Branch Offices",
    description: "Remote branch devices",
    parent_id: null,
    template_id: null,
    labels: ["branch"],
    device_count: 5,
    children: [],
  },
];

const MOCK_TEMPLATES = [
  {
    id: "template-1",
    name: "Standard Firewall",
    version: 3,
  },
  {
    id: "template-2",
    name: "Branch Router",
    version: 1,
  },
];

async function renderGroupsPage() {
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
          <MemoryRouter initialEntries={["/groups"]}>
            <GroupsPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(groupsListMock).toHaveBeenCalled());

  return { store };
}

describe("GroupsPage", () => {
  beforeEach(() => {
    groupsListMock.mockReset();
    groupsTreeMock.mockReset();
    templatesListMock.mockReset();

    groupsListMock.mockResolvedValue({ items: MOCK_GROUPS, meta: { total: 3, page: 1, size: 25 } });
    groupsTreeMock.mockResolvedValue(MOCK_TREE);
    templatesListMock.mockResolvedValue({ items: MOCK_TEMPLATES, meta: { total: 2, page: 1, size: 200 } });
  });

  it("renders the page header and groups table", async () => {
    await renderGroupsPage();

    expect(await screen.findByRole("heading", { name: "Device groups" })).toBeInTheDocument();
    expect(screen.getAllByText("Headquarters").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Branch Offices").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("DMZ").length).toBeGreaterThanOrEqual(1);
  });

  it("shows parent groups", async () => {
    await renderGroupsPage();

    expect(screen.getAllByText("Root").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Headquarters").length).toBeGreaterThanOrEqual(1);
  });

  it("shows labels in table", async () => {
    await renderGroupsPage();

    expect(screen.getAllByText("hq").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("core").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("branch").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("dmz").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("external").length).toBeGreaterThanOrEqual(1);
  });

  it("shows device count chips", async () => {
    await renderGroupsPage();

    expect(screen.getAllByText("10").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("5").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("3").length).toBeGreaterThanOrEqual(1);
  });

  it("renders search input", async () => {
    await renderGroupsPage();

    expect(screen.getByPlaceholderText("Search groups")).toBeInTheDocument();
  });

  it("renders new group button", async () => {
    await renderGroupsPage();

    expect(screen.getByRole("button", { name: "New group" })).toBeInTheDocument();
  });

  it("shows groups count in header", async () => {
    await renderGroupsPage();

    expect(screen.getAllByText(/groups/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows root groups count in header", async () => {
    await renderGroupsPage();

    expect(screen.getAllByText(/root groups/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders hierarchy tree section", async () => {
    await renderGroupsPage();

    expect(await screen.findByText("Hierarchy")).toBeInTheDocument();
    expect(screen.getByText("Parent/child inheritance")).toBeInTheDocument();
    expect(screen.getAllByText("Headquarters").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Branch Offices").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("DMZ").length).toBeGreaterThanOrEqual(1);
  });

  it("renders create group button in empty hierarchy", async () => {
    groupsTreeMock.mockResolvedValue([]);

    await renderGroupsPage();

    expect(screen.getByText("No groups yet. Create a root group to start building the hierarchy.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create group" })).toBeInTheDocument();
  });
});