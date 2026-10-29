import { describe, expect, it } from "vitest";

import type { AuthUser, LoginResponse } from "@/api/types";
import authReducer, {
  clearSession,
  login,
  logout,
  setUser,
  verifyMfa,
} from "@/store/authSlice";

const USER: AuthUser = {
  id: "3f1b6f9e-5f0a-4a3e-9d34-3f4e2c1d9a77",
  tenant_id: "5a0d4c8e-1f2b-4c3d-8e9f-0a1b2c3d4e5f",
  username: "admin",
  email: "admin@example.com",
  full_name: "Platform Admin",
  roles: ["TenantAdmin"],
  permissions: ["user:read", "user:write"],
  is_superadmin: false,
  mfa_enabled: false,
  auth_provider: "local",
  last_login_at: null,
};

function response(overrides: Partial<LoginResponse> = {}): LoginResponse {
  return {
    access_token: "access",
    refresh_token: "refresh",
    token_type: "bearer",
    expires_in: 3600,
    mfa_required: false,
    challenge_token: null,
    methods: [],
    user: USER,
    ...overrides,
  };
}

const credentials = { username: "admin", password: "correct-horse-battery" };

describe("authSlice", () => {
  it("hydrates an authenticated session from a login result", () => {
    const state = authReducer(undefined, login.fulfilled(response(), "req-1", credentials));

    expect(state.status).toBe("authenticated");
    expect(state.hydrated).toBe(true);
    expect(state.user?.username).toBe("admin");
    expect(state.error).toBeNull();
  });

  it("enters the MFA challenge state without an authenticated user", () => {
    const state = authReducer(
      undefined,
      login.fulfilled(
        response({
          access_token: "",
          refresh_token: "",
          mfa_required: true,
          challenge_token: "challenge",
          methods: ["totp"],
          user: null,
        }),
        "req-2",
        credentials,
      ),
    );

    expect(state.status).toBe("anonymous");
    expect(state.mfaRequired).toBe(true);
    expect(state.challengeToken).toBe("challenge");
    expect(state.mfaMethods).toEqual(["totp"]);
  });

  it("records a rejected login", () => {
    const state = authReducer(
      undefined,
      login.rejected(new Error("bad"), "req-3", credentials, "Invalid credentials"),
    );

    expect(state.status).toBe("anonymous");
    expect(state.error).toBe("Invalid credentials");
  });

  it("accepts an MFA verification result", () => {
    const state = authReducer(
      undefined,
      verifyMfa.fulfilled(response(), "req-4", { code: "123456", challenge_token: "challenge" }),
    );

    expect(state.status).toBe("authenticated");
    expect(state.mfaRequired).toBe(false);
  });

  it("clears identity on logout and explicit session reset", () => {
    const authenticated = authReducer(undefined, setUser(USER));
    const loggedOut = authReducer(authenticated, logout.fulfilled(undefined, "req-5", undefined));
    expect(loggedOut.user).toBeNull();
    expect(loggedOut.status).toBe("anonymous");

    const reset = authReducer(authenticated, clearSession());
    expect(reset.user).toBeNull();
    expect(reset.hydrated).toBe(true);
  });
});
