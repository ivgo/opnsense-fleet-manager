import { createAsyncThunk, createSlice, type PayloadAction } from "@reduxjs/toolkit";

import { getTenantId, setTenantId } from "@/api/tokenStore";

export type ThemeMode = "light" | "dark";
export type ToastSeverity = "success" | "info" | "warning" | "error";

export interface ToastState {
  open: boolean;
  message: string;
  severity: ToastSeverity;
}

export interface UiState {
  themeMode: ThemeMode;
  sidebarOpen: boolean;
  sidebarCollapsed: boolean;
  selectedTenantId: string | null;
  toast: ToastState;
}

const THEME_KEY = "ofme.theme";

export function readStoredTheme(): ThemeMode {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    if (value === "light" || value === "dark") return value;
  } catch {
    /* ignore */
  }
  return "light";
}

const initialState: UiState = {
  themeMode: readStoredTheme(),
  sidebarOpen: true,
  sidebarCollapsed: false,
  selectedTenantId: getTenantId(),
  toast: { open: false, message: "", severity: "info" },
};

export const switchTenant = createAsyncThunk<string | null, string | null>(
  "ui/switchTenant",
  async (tenantId) => {
    setTenantId(tenantId);
    return tenantId;
  },
);

const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    toggleSidebar(state) {
      state.sidebarOpen = !state.sidebarOpen;
    },
    setSidebarOpen(state, action: PayloadAction<boolean>) {
      state.sidebarOpen = action.payload;
    },
    toggleSidebarCollapsed(state) {
      state.sidebarCollapsed = !state.sidebarCollapsed;
    },
    setThemeMode(state, action: PayloadAction<ThemeMode>) {
      state.themeMode = action.payload;
      try {
        window.localStorage.setItem(THEME_KEY, action.payload);
      } catch {
        /* ignore */
      }
    },
    showToast(state, action: PayloadAction<{ message: string; severity?: ToastSeverity }>) {
      state.toast = {
        open: true,
        message: action.payload.message,
        severity: action.payload.severity ?? "info",
      };
    },
    hideToast(state) {
      state.toast.open = false;
    },
  },
  extraReducers: (builder) => {
    builder.addCase(switchTenant.fulfilled, (state, action) => {
      state.selectedTenantId = action.payload;
    });
  },
});

export const {
  toggleSidebar,
  setSidebarOpen,
  toggleSidebarCollapsed,
  setThemeMode,
  showToast,
  hideToast,
} = uiSlice.actions;

export const uiReducer = uiSlice.reducer;
export default uiSlice.reducer;
