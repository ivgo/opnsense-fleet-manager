import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, LoginResponse } from "@/api/types";
import { getAccessToken, resetStoreForTests } from "@/api/tokenStore";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const { providersMock, loginMock } = vi.hoisted(() => ({
  providersMock: vi.fn(),
  loginMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  authApi: {
    providers: providersMock,
    login: loginMock,
    ldapLogin: vi.fn(),
    verifyMfa: vi.fn(),
    oidcAuthorize: vi.fn(),
    logout: vi.fn(),
    me: vi.fn(),
  },
}));

import LoginPage from "@/pages/LoginPage";

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

const LOGIN_RESPONSE: LoginResponse = {
  access_token: "access-token",
  refresh_token: "refresh-token",
  token_type: "bearer",
  expires_in: 3600,
  mfa_required: false,
  challenge_token: null,
  methods: [],
  user: USER,
};

function renderLogin() {
  const store = configureStore({ reducer: { auth: authReducer, ui: uiReducer } });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  render(
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider theme={buildTheme("light")}>
          <MemoryRouter initialEntries={["/login"]}>
            <LoginPage />
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  return { store };
}

describe("LoginPage", () => {
  beforeEach(() => {
    resetStoreForTests();
    window.localStorage.clear();
    providersMock.mockReset();
    providersMock.mockResolvedValue({
      ldap: false,
      oidc: false,
      entra_id: false,
      mfa_enabled: true,
    });
    loginMock.mockReset();
  });

  it("renders the credential form", async () => {
    renderLogin();

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Username or e-mail/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Password/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeDisabled();
  });

  it("authenticates and stores the token pair", async () => {
    loginMock.mockResolvedValue(LOGIN_RESPONSE);
    const user = userEvent.setup();
    const { store } = renderLogin();

    await screen.findByRole("heading", { name: "Sign in" });
    await user.type(screen.getByLabelText(/Username or e-mail/), "admin");
    await user.type(screen.getByLabelText(/^Password/), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(store.getState().auth.status).toBe("authenticated"));
    expect(getAccessToken()).toBe("access-token");
    expect(store.getState().auth.user?.username).toBe("admin");
  });

  it("renders a failed login as an alert", async () => {
    loginMock.mockRejectedValue(new Error("Invalid credentials"));
    const user = userEvent.setup();
    renderLogin();

    await screen.findByRole("heading", { name: "Sign in" });
    await user.type(screen.getByLabelText(/Username or e-mail/), "admin");
    await user.type(screen.getByLabelText(/^Password/), "wrong-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
  });
});
