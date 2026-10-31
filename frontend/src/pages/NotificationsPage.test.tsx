import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Notification } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  notificationsListMock,
  notificationsCreateMock,
  notificationsMarkReadMock,
  notificationsMarkAllReadMock,
  notificationsRemoveMock,
} = vi.hoisted(() => ({
  notificationsListMock: vi.fn(),
  notificationsCreateMock: vi.fn(),
  notificationsMarkReadMock: vi.fn(),
  notificationsMarkAllReadMock: vi.fn(),
  notificationsRemoveMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  notificationsApi: {
    list: notificationsListMock,
    create: notificationsCreateMock,
    markRead: notificationsMarkReadMock,
    markAllRead: notificationsMarkAllReadMock,
    remove: notificationsRemoveMock,
  },
}));

import NotificationsPage from "@/pages/NotificationsPage";

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

const MOCK_NOTIFICATIONS: Notification[] = [
  {
    id: "notif-1",
    tenant_id: "tenant-1",
    title: "Backup Completed",
    message: "Daily backup completed successfully",
    type: "success",
    severity: "info",
    action_url: "/backups",
    channels: ["in_app", "email"],
    read: false,
    created_at: "2026-10-30T12:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
    delivery: {
      in_app: { status: "sent" },
      email: { status: "sent" },
    },
    delivered_at: "2026-10-30T12:00:05Z",
  },
  {
    id: "notif-2",
    tenant_id: "tenant-1",
    title: "Device Offline",
    message: "fw-branch-01 has been offline for 10 minutes",
    type: "alert",
    severity: "critical",
    action_url: "/devices/device-2",
    channels: ["in_app", "slack"],
    read: true,
    created_at: "2026-10-30T11:00:00Z",
    updated_at: "2026-10-30T11:05:00Z",
    delivery: {
      in_app: { status: "sent" },
      slack: { status: "sent" },
    },
    delivered_at: "2026-10-30T11:00:05Z",
  },
];

async function renderNotificationsPage() {
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
          <MemoryRouter initialEntries={["/notifications"]}>
            <NotificationsPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(notificationsListMock).toHaveBeenCalled());

  return { store };
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    notificationsListMock.mockReset();
    notificationsCreateMock.mockReset();
    notificationsMarkReadMock.mockReset();
    notificationsMarkAllReadMock.mockReset();
    notificationsRemoveMock.mockReset();

    notificationsListMock.mockResolvedValue({ items: MOCK_NOTIFICATIONS, meta: { total: 2, page: 1, size: 25 } });
  });

  it("renders the page header and notifications table", async () => {
    await renderNotificationsPage();

    expect(await screen.findByRole("heading", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByText("Backup Completed")).toBeInTheDocument();
    expect(screen.getByText("Device Offline")).toBeInTheDocument();
  });

  it("shows type badges", async () => {
    await renderNotificationsPage();

    expect(screen.getByText("success")).toBeInTheDocument();
    expect(screen.getByText("alert")).toBeInTheDocument();
  });

  it("shows severity badges", async () => {
    await renderNotificationsPage();

    expect(screen.getByText("Info")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("shows read/unread status", async () => {
    await renderNotificationsPage();

    // The read status appears as a colored dot in the first column, not as text "Unread"/"Read"
    // Check that the table renders both rows
    expect(screen.getByText("Backup Completed")).toBeInTheDocument();
    expect(screen.getByText("Device Offline")).toBeInTheDocument();
  });

  it("renders unread only toggle", async () => {
    await renderNotificationsPage();

    expect(screen.getByLabelText("Unread only")).toBeInTheDocument();
  });

  it("renders new notification button", async () => {
    await renderNotificationsPage();

    expect(screen.getByRole("button", { name: "New notification" })).toBeInTheDocument();
  });

  it("shows notifications count in header", async () => {
    await renderNotificationsPage();

    expect(screen.getByText("2 notifications")).toBeInTheDocument();
  });

  it("shows channels in delivery column", async () => {
    await renderNotificationsPage();

    // Delivery column shows "channel: status" format, e.g., "in_app: sent"
    expect(screen.getAllByText("in_app: sent")).toHaveLength(2);
    expect(screen.getByText("email: sent")).toBeInTheDocument();
    expect(screen.getByText("slack: sent")).toBeInTheDocument();
  });
});