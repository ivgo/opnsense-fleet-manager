import { NavLink, useLocation } from "react-router-dom";
import {
  Box,
  Divider,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import DnsOutlinedIcon from "@mui/icons-material/DnsOutlined";
import LanOutlinedIcon from "@mui/icons-material/LanOutlined";
import PublicOutlinedIcon from "@mui/icons-material/PublicOutlined";
import LocationCityOutlinedIcon from "@mui/icons-material/LocationCityOutlined";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import PolicyOutlinedIcon from "@mui/icons-material/PolicyOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import HubOutlinedIcon from "@mui/icons-material/HubOutlined";
import VerifiedUserOutlinedIcon from "@mui/icons-material/VerifiedUserOutlined";
import BackupOutlinedIcon from "@mui/icons-material/BackupOutlined";
import WorkHistoryOutlinedIcon from "@mui/icons-material/WorkHistoryOutlined";
import HistoryOutlinedIcon from "@mui/icons-material/HistoryOutlined";
import PeopleOutlinedIcon from "@mui/icons-material/PeopleOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import ShieldOutlinedIcon from "@mui/icons-material/ShieldOutlined";
import ApprovalOutlinedIcon from "@mui/icons-material/ApprovalOutlined";
import NotificationsNoneOutlinedIcon from "@mui/icons-material/NotificationsNoneOutlined";
import SyncAltOutlinedIcon from "@mui/icons-material/SyncAltOutlined";
import GppGoodOutlinedIcon from "@mui/icons-material/GppGoodOutlined";
import SwapHorizOutlinedIcon from "@mui/icons-material/SwapHorizOutlined";
import LabelOutlinedIcon from "@mui/icons-material/LabelOutlined";
import RocketLaunchOutlinedIcon from "@mui/icons-material/RocketLaunchOutlined";
import CommitOutlinedIcon from "@mui/icons-material/CommitOutlined";
import EventBusyOutlinedIcon from "@mui/icons-material/EventBusyOutlined";
import SummarizeOutlinedIcon from "@mui/icons-material/SummarizeOutlined";
import type { SvgIconComponent } from "@mui/icons-material";

import { usePermissions } from "@/hooks/usePermissions";

interface NavItem {
  label: string;
  path: string;
  icon: SvgIconComponent;
  permission?: string;
  exact?: boolean;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [{ label: "Dashboard", path: "/dashboard", icon: DashboardOutlinedIcon, exact: true }],
  },
  {
    label: "Inventory",
    items: [
      { label: "Devices", path: "/devices", icon: DnsOutlinedIcon, permission: "device:read" },
      { label: "Sites", path: "/sites", icon: LocationCityOutlinedIcon, permission: "site:read" },
      { label: "Groups", path: "/groups", icon: AccountTreeOutlinedIcon, permission: "group:read" },
    ],
  },
  {
    label: "Network",
    items: [
      { label: "DHCP", path: "/dhcp", icon: LanOutlinedIcon, permission: "dhcp:read" },
      { label: "DNS", path: "/dns", icon: PublicOutlinedIcon, permission: "dns:read" },
      { label: "Firewall rules", path: "/rules", icon: GppGoodOutlinedIcon, permission: "rule:read" },
      { label: "NAT", path: "/nat", icon: SwapHorizOutlinedIcon, permission: "nat:read" },
      { label: "Aliases", path: "/aliases", icon: LabelOutlinedIcon, permission: "alias:read" },
      { label: "High availability", path: "/ha", icon: SyncAltOutlinedIcon, permission: "ha:read" },
    ],
  },
  {
    label: "Automation",
    items: [
      { label: "Policies", path: "/policies", icon: PolicyOutlinedIcon, permission: "policy:read" },
      { label: "Templates", path: "/templates", icon: DescriptionOutlinedIcon, permission: "template:read" },
      { label: "SD-WAN", path: "/sdwan", icon: HubOutlinedIcon, permission: "sdwan:read" },
      { label: "ZTP", path: "/ztp", icon: RocketLaunchOutlinedIcon, permission: "ztp:read" },
      { label: "Git repositories", path: "/git", icon: CommitOutlinedIcon, permission: "git:read" },
    ],
  },
  {
    label: "Governance",
    items: [
      {
        label: "Compliance",
        path: "/compliance",
        icon: VerifiedUserOutlinedIcon,
        permission: "compliance:read",
      },
      { label: "Approvals", path: "/approvals", icon: ApprovalOutlinedIcon, permission: "change:read" },
      {
        label: "Notifications",
        path: "/notifications",
        icon: NotificationsNoneOutlinedIcon,
        permission: "alert:read",
      },
      { label: "Backups", path: "/backups", icon: BackupOutlinedIcon, permission: "backup:read" },
      {
        label: "Maintenance",
        path: "/maintenance",
        icon: EventBusyOutlinedIcon,
        permission: "alert:read",
      },
      {
        label: "Reports",
        path: "/reports",
        icon: SummarizeOutlinedIcon,
        permission: "report:read",
      },
      { label: "Jobs", path: "/jobs", icon: WorkHistoryOutlinedIcon, permission: "job:read" },
      { label: "Audit", path: "/audit", icon: HistoryOutlinedIcon, permission: "audit:read" },
    ],
  },
  {
    label: "Platform",
    items: [
      { label: "Users & access", path: "/users", icon: PeopleOutlinedIcon, permission: "user:read" },
      { label: "Settings", path: "/settings", icon: SettingsOutlinedIcon },
    ],
  },
];

export interface SidebarProps {
  collapsed?: boolean;
  onNavigate?: () => void;
}

export function Sidebar({ collapsed = false, onNavigate }: SidebarProps) {
  const location = useLocation();
  const { can } = usePermissions();

  const isActive = (item: NavItem) =>
    item.exact ? location.pathname === item.path : location.pathname.startsWith(item.path);

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <Stack
        direction="row"
        alignItems="center"
        spacing={1.25}
        sx={{ px: collapsed ? 1.5 : 2.25, py: 2, minHeight: 64 }}
      >
        <Box
          sx={(theme) => ({
            width: 36,
            height: 36,
            borderRadius: 2,
            display: "grid",
            placeItems: "center",
            color: "#fff",
            background: "linear-gradient(140deg, #0b3d6b 0%, #2f81f7 65%, #0ea5b7 100%)",
            boxShadow: `0 6px 16px ${alpha(theme.palette.primary.main, 0.35)}`,
            flexShrink: 0,
          })}
        >
          <ShieldOutlinedIcon fontSize="small" />
        </Box>
        {!collapsed && (
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 800, letterSpacing: "0.02em" }} noWrap>
              OFME
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap component="div">
              Fleet Manager Enterprise
            </Typography>
          </Box>
        )}
      </Stack>
      <Divider />

      <Box sx={{ flex: 1, overflowY: "auto", py: 1 }}>
        {NAV_GROUPS.map((group) => {
          const items = group.items.filter((item) => !item.permission || can(item.permission));
          if (items.length === 0) return null;
          return (
            <Box key={group.label} sx={{ mb: 0.5 }}>
              {!collapsed && (
                <Typography
                  variant="overline"
                  color="text.disabled"
                  sx={{ display: "block", px: 2.5, pt: 1.25, pb: 0.25, fontSize: "0.62rem" }}
                >
                  {group.label}
                </Typography>
              )}
              <List disablePadding sx={{ py: 0.25 }}>
                {items.map((item) => {
                  const active = isActive(item);
                  const Icon = item.icon;
                  const button = (
                    <ListItemButton
                      key={item.path}
                      component={NavLink}
                      to={item.path}
                      onClick={onNavigate}
                      selected={active}
                      sx={{
                        minHeight: 40,
                        justifyContent: collapsed ? "center" : "flex-start",
                        px: collapsed ? 1.25 : 1.75,
                        mx: collapsed ? 1 : 1.25,
                        "&.Mui-selected": {
                          bgcolor: (theme) => alpha(theme.palette.primary.main, 0.12),
                          color: "primary.main",
                          "&:hover": { bgcolor: (theme) => alpha(theme.palette.primary.main, 0.18) },
                          "& .MuiListItemIcon-root": { color: "primary.main" },
                        },
                      }}
                    >
                      <ListItemIcon
                        sx={{
                          minWidth: collapsed ? 0 : 34,
                          justifyContent: "center",
                          color: active ? "primary.main" : "text.secondary",
                        }}
                      >
                        <Icon fontSize="small" />
                      </ListItemIcon>
                      {!collapsed && (
                        <ListItemText
                          primary={item.label}
                          primaryTypographyProps={{ variant: "body2", fontWeight: active ? 700 : 500 }}
                        />
                      )}
                    </ListItemButton>
                  );
                  return collapsed ? (
                    <Tooltip key={item.path} title={item.label} placement="right">
                      {button}
                    </Tooltip>
                  ) : (
                    button
                  );
                })}
              </List>
            </Box>
          );
        })}
      </Box>

      <Divider />
      <Box sx={{ px: collapsed ? 1 : 2, py: 1.5 }}>
        {collapsed ? (
          <Tooltip title="OFME v1.0.0" placement="right">
            <Typography variant="caption" color="text.disabled" align="center" display="block">
              v1
            </Typography>
          </Tooltip>
        ) : (
          <Stack spacing={0.25}>
            <Typography variant="caption" color="text.secondary">
              OFME v1.0.0 · API v1
            </Typography>
            <Typography variant="caption" color="text.disabled">
              Policy-as-code · SD-WAN · ZTP
            </Typography>
          </Stack>
        )}
      </Box>
    </Box>
  );
}

export default Sidebar;
