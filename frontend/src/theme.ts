import { createTheme, type Theme } from "@mui/material/styles";

import type { ThemeMode } from "@/store/uiSlice";

const BRAND_NAVY = "#0b3d6b";
const BRAND_BLUE = "#2f81f7";
const BRAND_CYAN = "#0ea5b7";

export function buildTheme(mode: ThemeMode): Theme {
  const dark = mode === "dark";

  return createTheme({
    palette: {
      mode,
      primary: {
        main: dark ? "#6aa9ff" : BRAND_BLUE,
        dark: dark ? "#2f81f7" : "#1c5fbf",
        light: dark ? "#9cc6ff" : "#6aa9ff",
        contrastText: dark ? "#06121f" : "#ffffff",
      },
      secondary: {
        main: dark ? "#3fd0c9" : BRAND_CYAN,
        dark: dark ? "#0ea5b7" : "#087f8c",
        contrastText: dark ? "#04191a" : "#ffffff",
      },
      success: { main: dark ? "#4ade80" : "#15803d" },
      warning: { main: dark ? "#fbbf24" : "#b45309" },
      error: { main: dark ? "#fb7185" : "#b91c1c" },
      info: { main: dark ? "#67e8f9" : "#0369a1" },
      background: {
        default: dark ? "#0b1220" : "#f6f8fb",
        paper: dark ? "#111a2b" : "#ffffff",
      },
      divider: dark ? "rgba(148, 163, 184, 0.22)" : "rgba(15, 23, 42, 0.1)",
      text: {
        primary: dark ? "#e5edf9" : "#0f172a",
        secondary: dark ? "#a9b6ca" : "#526071",
      },
    },
    shape: { borderRadius: 10 },
    typography: {
      fontFamily: [
        "Inter",
        "Segoe UI",
        "system-ui",
        "-apple-system",
        "BlinkMacSystemFont",
        "sans-serif",
      ].join(","),
      h1: { fontSize: "1.75rem", fontWeight: 700, letterSpacing: "-0.02em" },
      h2: { fontSize: "1.45rem", fontWeight: 700, letterSpacing: "-0.015em" },
      h3: { fontSize: "1.2rem", fontWeight: 650 },
      h4: { fontSize: "1.05rem", fontWeight: 650 },
      h5: { fontSize: "0.98rem", fontWeight: 650 },
      h6: { fontSize: "0.92rem", fontWeight: 650 },
      button: { textTransform: "none", fontWeight: 600 },
      overline: { letterSpacing: "0.08em", fontWeight: 700, fontSize: "0.7rem" },
      caption: { fontSize: "0.78rem" },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          body: {
            minHeight: "100vh",
            backgroundColor: dark ? "#0b1220" : "#f6f8fb",
            backgroundImage: dark
              ? "radial-gradient(1100px 500px at 15% -10%, rgba(47,129,247,0.12), transparent 60%)"
              : "radial-gradient(1100px 500px at 15% -10%, rgba(47,129,247,0.09), transparent 60%)",
            backgroundAttachment: "fixed",
          },
          "*::-webkit-scrollbar": { width: 10, height: 10 },
          "*::-webkit-scrollbar-thumb": {
            backgroundColor: dark ? "rgba(148,163,184,0.35)" : "rgba(15,23,42,0.18)",
            borderRadius: 8,
          },
          code: { fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace" },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: { root: { textTransform: "none", borderRadius: 8 } },
      },
      MuiPaper: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            backgroundImage: "none",
            border: `1px solid ${dark ? "rgba(148,163,184,0.18)" : "rgba(15,23,42,0.08)"}`,
          },
        },
      },
      MuiCard: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            border: `1px solid ${dark ? "rgba(148,163,184,0.18)" : "rgba(15,23,42,0.08)"}`,
            backgroundImage: "none",
          },
        },
      },
      MuiTextField: { defaultProps: { size: "small", fullWidth: true } },
      MuiSelect: { defaultProps: { size: "small" } },
      MuiTable: { defaultProps: { size: "small" } },
      MuiTableCell: {
        styleOverrides: {
          head: {
            fontWeight: 700,
            fontSize: "0.76rem",
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            color: dark ? "#a9b6ca" : "#526071",
            backgroundColor: dark ? "rgba(148,163,184,0.06)" : "rgba(15,23,42,0.03)",
            whiteSpace: "nowrap",
          },
        },
      },
      MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
      MuiListItemButton: { styleOverrides: { root: { borderRadius: 8, marginInline: 8 } } },
      MuiTooltip: { defaultProps: { arrow: true } },
      MuiDialog: { defaultProps: { maxWidth: "md", fullWidth: true } },
      MuiTabs: { styleOverrides: { root: { minHeight: 40 } } },
      MuiTab: { styleOverrides: { root: { minHeight: 40, textTransform: "none", fontWeight: 600 } } },
    },
  });
}

export const monoFont = "'JetBrains Mono', 'Cascadia Code', Consolas, monospace";
export const brandGradient = `linear-gradient(135deg, ${BRAND_NAVY} 0%, ${BRAND_BLUE} 60%, ${BRAND_CYAN} 100%)`;
