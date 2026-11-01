import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Template } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  templatesListMock,
  templatesCreateMock,
  templatesUpdateMock,
  templatesRemoveMock,
  templatesRenderMock,
} = vi.hoisted(() => ({
  templatesListMock: vi.fn(),
  templatesCreateMock: vi.fn(),
  templatesUpdateMock: vi.fn(),
  templatesRemoveMock: vi.fn(),
  templatesRenderMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  templatesApi: {
    list: templatesListMock,
    create: templatesCreateMock,
    update: templatesUpdateMock,
    remove: templatesRemoveMock,
    render: templatesRenderMock,
  },
}));

import TemplatesPage from "@/pages/TemplatesPage";

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

const MOCK_TEMPLATES: Template[] = [
  {
    id: "tpl-1",
    tenant_id: "tenant-1",
    name: "Firewall Config",
    description: "Base firewall configuration",
    kind: "config",
    parent_id: null,
    body: { system: { hostname: "{{ hostname }}", domain: "{{ domain }}" } },
    variables: { hostname: "", domain: "example.internal" },
    is_active: true,
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
  {
    id: "tpl-2",
    tenant_id: "tenant-1",
    name: "NAT Policy",
    description: "Standard NAT rules",
    kind: "policy",
    parent_id: "tpl-1",
    body: { nat: { rules: [] } },
    variables: {},
    is_active: true,
    version: 2,
    created_at: "2026-01-02T00:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
  },
];

async function renderTemplatesPage() {
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
          <MemoryRouter initialEntries={["/templates"]}>
            <TemplatesPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(templatesListMock).toHaveBeenCalled());

  return { store };
}

describe("TemplatesPage", () => {
  beforeEach(() => {
    templatesListMock.mockReset();
    templatesCreateMock.mockReset();
    templatesUpdateMock.mockReset();
    templatesRemoveMock.mockReset();
    templatesRenderMock.mockReset();

    templatesListMock.mockResolvedValue({ items: MOCK_TEMPLATES, meta: { total: 2, page: 1, size: 25 } });
  });

  it("renders the page header and templates table", async () => {
    await renderTemplatesPage();

    expect(await screen.findByRole("heading", { name: "Templates" })).toBeInTheDocument();
    expect(screen.getByText("Firewall Config")).toBeInTheDocument();
    expect(screen.getByText("NAT Policy")).toBeInTheDocument();
  });

  it("shows kind badges", async () => {
    await renderTemplatesPage();

    expect(screen.getByText("Configuration")).toBeInTheDocument();
    expect(screen.getByText("Policy")).toBeInTheDocument();
  });

  it("shows active status", async () => {
    await renderTemplatesPage();

    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("renders search input", async () => {
    await renderTemplatesPage();

    expect(screen.getByPlaceholderText("Search templates")).toBeInTheDocument();
  });

  it("renders kind filter", async () => {
    await renderTemplatesPage();

    expect(screen.getByLabelText("Kind")).toBeInTheDocument();
  });

  it("renders new template button", async () => {
    await renderTemplatesPage();

    expect(screen.getByRole("button", { name: "New template" })).toBeInTheDocument();
  });

  it("shows templates count in header", async () => {
    await renderTemplatesPage();

    expect(screen.getAllByText("2 templates").length).toBeGreaterThanOrEqual(1);
  });

  it("shows parent relationship badge", async () => {
    await renderTemplatesPage();

    expect(screen.getByText("inherits")).toBeInTheDocument();
  });

  it("opens create template dialog", async () => {
    await renderTemplatesPage();

    await screen.findByRole("button", { name: "New template" }).then((btn) => btn.click());

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(await screen.findByRole("heading", { name: "New template" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create template" })).toBeInTheDocument();
  });

  it("renders variables count column", async () => {
    await renderTemplatesPage();

    expect(screen.getByText("Variables")).toBeInTheDocument();
    // Variables column renders the count: first template has 2 variables (hostname, domain), second has 0
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("shows version column", async () => {
    await renderTemplatesPage();

    expect(screen.getByText("Version")).toBeInTheDocument();
    expect(screen.getAllByText("v1").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("v2").length).toBeGreaterThanOrEqual(1);
  });

  it("shows description column", async () => {
    await renderTemplatesPage();

    expect(screen.getByText("Base firewall configuration")).toBeInTheDocument();
    expect(screen.getByText("Standard NAT rules")).toBeInTheDocument();
  });

  it("opens render dialog from row action", async () => {
    await renderTemplatesPage();

    const renderButtons = await screen.findAllByRole("button", { name: /Render with variables/ });
    await waitFor(() => renderButtons[0].click());

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(await screen.findByRole("heading", { name: /Render/ })).toBeInTheDocument();
  });

  it("shows effective preview action", async () => {
    await renderTemplatesPage();

    const previewButtons = await screen.findAllByRole("button", { name: /View effective configuration/ });
    expect(previewButtons.length).toBeGreaterThanOrEqual(1);
  });
});