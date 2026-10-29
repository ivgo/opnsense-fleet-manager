import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AppBar,
  Autocomplete,
  Avatar,
  Badge,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  InputAdornment,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Stack,
  TextField,
  Toolbar,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import MenuOpenIcon from "@mui/icons-material/MenuOpen";
import SearchIcon from "@mui/icons-material/Search";
import NotificationsOutlinedIcon from "@mui/icons-material/NotificationsOutlined";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import LogoutIcon from "@mui/icons-material/Logout";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import BusinessOutlinedIcon from "@mui/icons-material/BusinessOutlined";
import CheckIcon from "@mui/icons-material/Check";
import DnsOutlinedIcon from "@mui/icons-material/DnsOutlined";
import { useQuery } from "@tanstack/react-query";

import { alertsApi, devicesApi, tenantsApi } from "@/api/endpoints";
import { qk } from "@/api/queryKeys";
import type { DeviceSearchResult } from "@/api/types";
import { useDebounce } from "@/hooks/useDebounce";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { logout } from "@/store/authSlice";
import { setThemeMode, switchTenant, toggleSidebarCollapsed } from "@/store/uiSlice";
import { initials } from "@/utils/format";

export interface TopbarProps {
  onOpenMobile: () => void;
  collapsed: boolean;
}

export function Topbar({ onOpenMobile, collapsed }: TopbarProps) {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const themeMode = useAppSelector((state) => state.ui.themeMode);
  const selectedTenantId = useAppSelector((state) => state.ui.selectedTenantId);

  const [searchTerm, setSearchTerm] = useState("");
  const [userMenu, setUserMenu] = useState<HTMLElement | null>(null);
  const [alertMenu, setAlertMenu] = useState<HTMLElement | null>(null);
  const [tenantMenu, setTenantMenu] = useState<HTMLElement | null>(null);
  const debouncedTerm = useDebounce(searchTerm.trim(), 350);

  const searchQuery = useQuery({
    queryKey: qk.devices.search(debouncedTerm),
    queryFn: () => devicesApi.search(debouncedTerm, 8),
    enabled: debouncedTerm.length >= 2,
    staleTime: 15_000,
  });

  const alertCounts = useQuery({
    queryKey: qk.alerts.counts,
    queryFn: () => alertsApi.counts(),
    refetchInterval: 45_000,
  });

  const tenantQuery = useQuery({
    queryKey: qk.tenants.list({ size: 100 }),
    queryFn: () => tenantsApi.list({ size: 100 }),
    enabled: Boolean(user?.is_superadmin),
    staleTime: 120_000,
  });

  const options = useMemo<DeviceSearchResult[]>(() => searchQuery.data ?? [], [searchQuery.data]);
  const openAlerts = Number(alertCounts.data?.open ?? alertCounts.data?.firing ?? 0);
  const criticalAlerts = Number(alertCounts.data?.critical ?? 0);

  const handleSelectDevice = (value: DeviceSearchResult | null) => {
    if (!value) return;
    navigate(`/devices/${value.id}`);
    setSearchTerm("");
  };

  const handleTenant = async (tenantId: string | null) => {
    setTenantMenu(null);
    await dispatch(switchTenant(tenantId));
    // Every cached query is tenant-scoped; reloading guarantees a clean slate.
    window.location.reload();
  };

  const handleSignOut = async () => {
    setUserMenu(null);
    await dispatch(logout());
    navigate("/login", { replace: true });
  };

  return (
    <AppBar
      position="sticky"
      color="transparent"
      elevation={0}
      sx={{
        backdropFilter: "blur(10px)",
        backgroundColor: (theme) => alpha(theme.palette.background.default, 0.82),
        borderBottom: 1,
        borderColor: "divider",
        zIndex: (theme) => theme.zIndex.drawer - 1,
      }}
    >
      <Toolbar sx={{ minHeight: 64, gap: 1 }}>
        <IconButton
          edge="start"
          onClick={onOpenMobile}
          sx={{ display: { md: "none" } }}
          aria-label="Open navigation"
        >
          <MenuIcon />
        </IconButton>
        <Tooltip title={collapsed ? "Expand navigation" : "Collapse navigation"}>
          <IconButton
            onClick={() => dispatch(toggleSidebarCollapsed())}
            sx={{ display: { xs: "none", md: "inline-flex" } }}
            aria-label="Toggle navigation width"
          >
            {collapsed ? <MenuIcon /> : <MenuOpenIcon />}
          </IconButton>
        </Tooltip>

        <Autocomplete<DeviceSearchResult, false, true, false>
          options={options}
          value={undefined}
          onChange={(_event, value) => handleSelectDevice(value)}
          inputValue={searchTerm}
          onInputChange={(_event, value) => setSearchTerm(value)}
          filterOptions={(items) => items}
          getOptionLabel={(option) => option.name}
          isOptionEqualToValue={(option, value) => option.id === value.id}
          loading={searchQuery.isFetching}
          noOptionsText={debouncedTerm.length < 2 ? "Type at least 2 characters" : "No devices found"}
          sx={{ width: { xs: "100%", sm: 320 }, maxWidth: 420 }}
          renderOption={(props, option) => (
            <Box component="li" {...props} key={option.id}>
              <ListItemIcon sx={{ minWidth: 32 }}>
                <DnsOutlinedIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText
                primary={option.name}
                secondary={option.ip_address ?? option.hostname ?? option.status}
                primaryTypographyProps={{ variant: "body2" }}
                secondaryTypographyProps={{ variant: "caption" }}
              />
            </Box>
          )}
          renderInput={(params) => (
            <TextField
              {...params}
              placeholder="Search devices…"
              size="small"
              InputProps={{
                ...params.InputProps,
                startAdornment: (
                  <>
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" />
                    </InputAdornment>
                    {params.InputProps.startAdornment}
                  </>
                ),
                endAdornment: (
                  <>
                    {searchQuery.isFetching ? <CircularProgress color="inherit" size={16} /> : null}
                    {params.InputProps.endAdornment}
                  </>
                ),
              }}
            />
          )}
        />

        <Box sx={{ flex: 1 }} />

        {user?.is_superadmin && (
          <>
            <Button
              size="small"
              variant="outlined"
              color="inherit"
              startIcon={<BusinessOutlinedIcon />}
              onClick={(event) => setTenantMenu(event.currentTarget)}
              sx={{ display: { xs: "none", lg: "inline-flex" }, textTransform: "none" }}
            >
              {selectedTenantId
                ? tenantQuery.data?.items.find((tenant) => tenant.id === selectedTenantId)?.name ??
                  "Selected tenant"
                : "All tenants"}
            </Button>
            <Menu
              anchorEl={tenantMenu}
              open={Boolean(tenantMenu)}
              onClose={() => setTenantMenu(null)}
              anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
              transformOrigin={{ vertical: "top", horizontal: "right" }}
            >
              <MenuItem selected={selectedTenantId === null} onClick={() => handleTenant(null)}>
                <ListItemIcon>{selectedTenantId === null && <CheckIcon fontSize="small" />}</ListItemIcon>
                <ListItemText primary="All tenants" secondary="Platform-wide view" />
              </MenuItem>
              <Divider />
              {(tenantQuery.data?.items ?? []).map((tenant) => (
                <MenuItem
                  key={tenant.id}
                  selected={selectedTenantId === tenant.id}
                  onClick={() => handleTenant(tenant.id)}
                >
                  <ListItemIcon>
                    {selectedTenantId === tenant.id && <CheckIcon fontSize="small" />}
                  </ListItemIcon>
                  <ListItemText
                    primary={tenant.name}
                    secondary={`${tenant.slug} · ${tenant.device_count} devices`}
                  />
                </MenuItem>
              ))}
            </Menu>
          </>
        )}

        <Tooltip title="Alerts">
          <IconButton onClick={(event) => setAlertMenu(event.currentTarget)} aria-label="Alerts">
            <Badge badgeContent={openAlerts} color={criticalAlerts > 0 ? "error" : "warning"} max={99}>
              <NotificationsOutlinedIcon />
            </Badge>
          </IconButton>
        </Tooltip>
        <Menu
          anchorEl={alertMenu}
          open={Boolean(alertMenu)}
          onClose={() => setAlertMenu(null)}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          transformOrigin={{ vertical: "top", horizontal: "right" }}
          slotProps={{ paper: { sx: { width: 280 } } }}
        >
          <Box sx={{ px: 2, pt: 1.5, pb: 1 }}>
            <Typography variant="subtitle2">Open alerts</Typography>
            <Typography variant="caption" color="text.secondary">
              Live counters from the alert engine
            </Typography>
          </Box>
          <Divider />
          <MenuItem onClick={() => {
            setAlertMenu(null);
            navigate("/dashboard?focus=alerts");
          }}>
            <ListItemText
              primary={`${openAlerts} open alert${openAlerts === 1 ? "" : "s"}`}
              secondary={criticalAlerts > 0 ? `${criticalAlerts} critical` : "No critical alerts"}
            />
            {criticalAlerts > 0 && <Chip size="small" color="error" label="critical" />}
          </MenuItem>
          <MenuItem
            onClick={() => {
              setAlertMenu(null);
              navigate("/settings?tab=alerts");
            }}
          >
            <ListItemText primary="Manage alert rules" secondary="Thresholds, channels and tests" />
          </MenuItem>
          <MenuItem
            onClick={() => {
              setAlertMenu(null);
              navigate("/notifications");
            }}
          >
            <ListItemText primary="Notification inbox" secondary="Delivery history and channel status" />
          </MenuItem>
        </Menu>

        <Tooltip title={themeMode === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
          <IconButton
            onClick={() => dispatch(setThemeMode(themeMode === "dark" ? "light" : "dark"))}
            aria-label="Toggle color mode"
          >
            {themeMode === "dark" ? <LightModeOutlinedIcon /> : <DarkModeOutlinedIcon />}
          </IconButton>
        </Tooltip>

        <IconButton onClick={(event) => setUserMenu(event.currentTarget)} aria-label="Account menu" sx={{ p: 0.5 }}>
          <Avatar
            sx={{
              width: 34,
              height: 34,
              bgcolor: "primary.main",
              fontSize: 13,
              fontWeight: 700,
            }}
          >
            {initials(user?.full_name ?? user?.username)}
          </Avatar>
        </IconButton>
        <Menu
          anchorEl={userMenu}
          open={Boolean(userMenu)}
          onClose={() => setUserMenu(null)}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          transformOrigin={{ vertical: "top", horizontal: "right" }}
          slotProps={{ paper: { sx: { width: 300 } } }}
        >
          <Box sx={{ px: 2, py: 1.5 }}>
            <Typography variant="subtitle2" noWrap>
              {user?.full_name ?? user?.username}
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" noWrap>
              {user?.email}
            </Typography>
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
              {(user?.roles ?? []).map((role) => (
                <Chip key={role} size="small" label={role} variant="outlined" />
              ))}
              {user?.mfa_enabled && <Chip size="small" label="MFA" color="success" variant="outlined" />}
            </Stack>
          </Box>
          <Divider />
          <MenuItem
            onClick={() => {
              setUserMenu(null);
              navigate("/settings");
            }}
          >
            <ListItemIcon>
              <SettingsOutlinedIcon fontSize="small" />
            </ListItemIcon>
            Settings
          </MenuItem>
          <MenuItem onClick={handleSignOut}>
            <ListItemIcon>
              <LogoutIcon fontSize="small" />
            </ListItemIcon>
            Sign out
          </MenuItem>
        </Menu>
      </Toolbar>
    </AppBar>
  );
}

export default Topbar;
