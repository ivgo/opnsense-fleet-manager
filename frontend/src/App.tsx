import { useEffect, useMemo } from "react";
import { CssBaseline, ThemeProvider } from "@mui/material";
import { RouterProvider } from "react-router-dom";

import ErrorBoundary from "@/components/ErrorBoundary";
import { router } from "@/router";
import { SESSION_EXPIRED_EVENT } from "@/api/tokenStore";
import { bootstrapSession, clearSession } from "@/store/authSlice";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { buildTheme } from "@/theme";

/**
 * Application shell: restores the session once, wires the global session-expiry
 * signal and provides the MUI theme derived from the persisted UI preference.
 */
export function App() {
  const dispatch = useAppDispatch();
  const themeMode = useAppSelector((state) => state.ui.themeMode);
  const hydrated = useAppSelector((state) => state.auth.hydrated);

  const theme = useMemo(() => buildTheme(themeMode), [themeMode]);

  useEffect(() => {
    if (!hydrated) {
      void dispatch(bootstrapSession());
    }
  }, [dispatch, hydrated]);

  useEffect(() => {
    const handleExpiry = () => dispatch(clearSession());
    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpiry);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpiry);
  }, [dispatch]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline enableColorScheme />
      <ErrorBoundary>
        <RouterProvider router={router} />
      </ErrorBoundary>
    </ThemeProvider>
  );
}

export default App;
