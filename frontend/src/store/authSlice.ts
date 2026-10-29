import { createAsyncThunk, createSlice, type PayloadAction } from "@reduxjs/toolkit";

import { authApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from "@/api/tokenStore";
import type { AuthUser, LoginPayload, LoginResponse, MfaVerifyPayload } from "@/api/types";

export type AuthStatus = "idle" | "loading" | "authenticated" | "anonymous";

export interface AuthState {
  user: AuthUser | null;
  status: AuthStatus;
  hydrated: boolean;
  error: string | null;
  mfaRequired: boolean;
  challengeToken: string | null;
  mfaMethods: string[];
}

const initialState: AuthState = {
  user: null,
  status: "idle",
  hydrated: false,
  error: null,
  mfaRequired: false,
  challengeToken: null,
  mfaMethods: [],
};

function applySession(state: AuthState, response: LoginResponse): void {
  if (response.mfa_required) {
    state.mfaRequired = true;
    state.challengeToken = response.challenge_token;
    state.mfaMethods = response.methods ?? [];
    state.status = "anonymous";
    return;
  }
  state.mfaRequired = false;
  state.challengeToken = null;
  state.mfaMethods = [];
  state.user = response.user ?? state.user;
  state.status = "authenticated";
  state.error = null;
}

export const bootstrapSession = createAsyncThunk<
  AuthUser | null,
  void,
  { rejectValue: string }
>("auth/bootstrap", async (_arg, { rejectWithValue }) => {
  if (!getAccessToken() && !getRefreshToken()) return null;
  try {
    return await authApi.me();
  } catch (error) {
    const apiError = toApiError(error);
    if (apiError.isUnauthorized) {
      clearTokens();
      return null;
    }
    return rejectWithValue(apiError.message);
  }
});

export const login = createAsyncThunk<
  LoginResponse,
  LoginPayload,
  { rejectValue: string }
>("auth/login", async (payload, { rejectWithValue }) => {
  try {
    const response = await authApi.login(payload);
    if (!response.mfa_required) {
      setTokens(response.access_token, response.refresh_token, response.expires_in);
    }
    return response;
  } catch (error) {
    return rejectWithValue(toApiError(error).message);
  }
});

export const ldapLogin = createAsyncThunk<
  LoginResponse,
  LoginPayload,
  { rejectValue: string }
>("auth/ldapLogin", async (payload, { rejectWithValue }) => {
  try {
    const response = await authApi.ldapLogin(payload);
    if (!response.mfa_required) {
      setTokens(response.access_token, response.refresh_token, response.expires_in);
    }
    return response;
  } catch (error) {
    return rejectWithValue(toApiError(error).message);
  }
});

export const verifyMfa = createAsyncThunk<
  LoginResponse,
  MfaVerifyPayload,
  { rejectValue: string }
>("auth/verifyMfa", async (payload, { rejectWithValue }) => {
  try {
    const response = await authApi.verifyMfa(payload);
    setTokens(response.access_token, response.refresh_token, response.expires_in);
    return response;
  } catch (error) {
    return rejectWithValue(toApiError(error).message);
  }
});

export const logout = createAsyncThunk<void, { allSessions?: boolean } | void>(
  "auth/logout",
  async (arg) => {
    const refreshToken = getRefreshToken();
    try {
      if (getAccessToken()) {
        await authApi.logout(refreshToken, Boolean(arg && arg.allSessions));
      }
    } catch {
      /* tokens are cleared client-side regardless */
    } finally {
      clearTokens();
    }
  },
);

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    setUser(state, action: PayloadAction<AuthUser>) {
      state.user = action.payload;
      state.status = "authenticated";
      state.hydrated = true;
      state.error = null;
    },
    clearSession(state) {
      state.user = null;
      state.status = "anonymous";
      state.mfaRequired = false;
      state.challengeToken = null;
      state.mfaMethods = [];
      state.error = null;
      state.hydrated = true;
    },
    clearError(state) {
      state.error = null;
    },
    resetMfa(state) {
      state.mfaRequired = false;
      state.challengeToken = null;
      state.mfaMethods = [];
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(bootstrapSession.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(bootstrapSession.fulfilled, (state, action) => {
        state.hydrated = true;
        if (action.payload) {
          state.user = action.payload;
          state.status = "authenticated";
        } else {
          state.user = null;
          state.status = "anonymous";
        }
      })
      .addCase(bootstrapSession.rejected, (state, action) => {
        state.hydrated = true;
        state.status = "anonymous";
        state.user = null;
        state.error = action.payload ?? "Unable to restore the session";
      })
      .addCase(login.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(login.fulfilled, (state, action) => {
        state.hydrated = true;
        applySession(state, action.payload);
      })
      .addCase(login.rejected, (state, action) => {
        state.status = "anonymous";
        state.error = action.payload ?? "Login failed";
      })
      .addCase(ldapLogin.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(ldapLogin.fulfilled, (state, action) => {
        state.hydrated = true;
        applySession(state, action.payload);
      })
      .addCase(ldapLogin.rejected, (state, action) => {
        state.status = "anonymous";
        state.error = action.payload ?? "Directory login failed";
      })
      .addCase(verifyMfa.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(verifyMfa.fulfilled, (state, action) => {
        state.hydrated = true;
        applySession(state, action.payload);
      })
      .addCase(verifyMfa.rejected, (state, action) => {
        state.status = "anonymous";
        state.error = action.payload ?? "Verification failed";
      })
      .addCase(logout.fulfilled, (state) => {
        state.user = null;
        state.status = "anonymous";
        state.mfaRequired = false;
        state.challengeToken = null;
        state.mfaMethods = [];
      });
  },
});

export const { setUser, clearSession, clearError, resetMfa } = authSlice.actions;
export const authReducer = authSlice.reducer;
export default authSlice.reducer;
