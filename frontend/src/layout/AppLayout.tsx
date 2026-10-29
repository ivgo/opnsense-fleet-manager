import { useCallback, useMemo, useState } from "react";
import { Outlet } from "react-router-dom";
import {
  Alert,
  Box,
  Drawer,
  Snackbar,
  Toolbar,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import { useQueryClient } from "@tanstack/react-query";

import { useWebSocket, type WebSocketEvent } from "@/hooks/useWebSocket";
import Sidebar from "@/layout/Sidebar";
import Topbar from "@/layout/Topbar";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { hideToast, showToast } from "@/store/uiSlice";
import { NAV_WIDTH, NAV_WIDTH_COLLAPSED } from "@/utils/constants";

function useRealtimeBridge() {
  const queryClient = useQueryClient();
  const dispatch = useAppDispatch();

  const handleEvent = useCallback(
    (event: WebSocketEvent) => {
      const invalidate = (prefix: string) => {
        void queryClient.invalidateQueries({ queryKey: [prefix] });
      };

      switch (event.topic) {
        case "devices":
          invalidate("devices");
          invalidate("dashboard");
          break;
        case "alerts":
          invalidate("alerts");
          invalidate("dashboard");
          if (event.event === "alert.raised" && String(event.data.severity ?? "") === "critical") {
            dispatch(
              showToast({
                message: `Critical alert: ${String(event.data.title ?? "device alert")}`,
                severity: "error",
              }),
            );
          }
          break;
        case "jobs":
          invalidate("jobs");
          invalidate("dashboard");
          break;
        case "deployments":
          invalidate("policies");
          invalidate("deployments");
          invalidate("drift");
          break;
        case "backups":
          invalidate("backups");
          break;
        case "compliance":
          invalidate("compliance");
          invalidate("dashboard");
          break;
        case "tunnels":
          invalidate("sdwan");
          invalidate("dashboard");
          break;
        default:
          invalidate("dashboard");
      }
    },
    [dispatch, queryClient],
  );

  const topics = useMemo(
    () => ["fleet", "devices", "alerts", "jobs", "deployments", "backups", "compliance", "tunnels"],
    [],
  );

  return useWebSocket(topics, { onEvent: handleEvent });
}

export function AppLayout() {
  const theme = useTheme();
  const desktop = useMediaQuery(theme.breakpoints.up("md"));
  const collapsed = useAppSelector((state) => state.ui.sidebarCollapsed);
  const toast = useAppSelector((state) => state.ui.toast);
  const dispatch = useAppDispatch();
  const [mobileOpen, setMobileOpen] = useState(false);

  useRealtimeBridge();

  const drawerWidth = collapsed ? NAV_WIDTH_COLLAPSED : NAV_WIDTH;

  return (
    <Box sx={{ display: "flex", minHeight: "100vh", bgcolor: "transparent" }}>
      <Drawer
        variant={desktop ? "permanent" : "temporary"}
        open={desktop ? true : mobileOpen}
        onClose={() => setMobileOpen(false)}
        ModalProps={{ keepMounted: true }}
        sx={{
          width: desktop ? drawerWidth : NAV_WIDTH,
          flexShrink: 0,
          "& .MuiDrawer-paper": {
            width: desktop ? drawerWidth : NAV_WIDTH,
            boxSizing: "border-box",
            borderRight: 1,
            borderColor: "divider",
            bgcolor: "background.paper",
            transition: theme.transitions.create("width", {
              duration: theme.transitions.duration.shorter,
            }),
            overflowX: "hidden",
          },
        }}
      >
        <Sidebar collapsed={desktop && collapsed} onNavigate={() => setMobileOpen(false)} />
      </Drawer>

      <Box sx={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <Topbar onOpenMobile={() => setMobileOpen(true)} collapsed={collapsed} />
        <Box
          component="main"
          sx={{
            flex: 1,
            px: { xs: 2, sm: 2.5, lg: 3.5 },
            py: { xs: 2.5, lg: 3 },
            width: "100%",
            maxWidth: 1680,
            mx: "auto",
          }}
        >
          <Toolbar sx={{ display: "none" }} />
          <Outlet />
        </Box>
      </Box>

      <Snackbar
        open={toast.open}
        autoHideDuration={toast.severity === "error" ? 9000 : 5000}
        onClose={() => dispatch(hideToast())}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
      >
        <Alert
          severity={toast.severity}
          variant="filled"
          onClose={() => dispatch(hideToast())}
          sx={{ alignItems: "center" }}
        >
          {toast.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}

export default AppLayout;
