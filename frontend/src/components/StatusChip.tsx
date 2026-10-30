import { Box, Chip, type ChipProps } from "@mui/material";

import { titleCase } from "@/utils/format";
import {
  ALERT_STATUS_LABELS,
  BACKUP_TYPE_LABELS,
  CONNECTION_STATUS_LABELS,
  DEVICE_STATUS_LABELS,
  JOB_STATUS_LABELS,
  POLICY_STATUS_LABELS,
  REPORT_STATUS_LABELS,
  TUNNEL_STATUS_LABELS,
} from "@/utils/constants";

type ChipColor = ChipProps["color"];

const LABELS: Record<string, string> = {
  ...DEVICE_STATUS_LABELS,
  ...CONNECTION_STATUS_LABELS,
  ...ALERT_STATUS_LABELS,
  ...POLICY_STATUS_LABELS,
  ...JOB_STATUS_LABELS,
  ...BACKUP_TYPE_LABELS,
  ...TUNNEL_STATUS_LABELS,
  ...REPORT_STATUS_LABELS,
  ...{
    active: "Active",
    inactive: "Inactive",
    locked: "Locked",
    trial: "Trial",
    suspended: "Suspended",
    cancelled: "Cancelled",
    enabled: "Enabled",
    disabled: "Disabled",
    healthy: "Healthy",
    degraded: "Degraded",
    unhealthy: "Unhealthy",
    open: "Open",
    acknowledged: "Acknowledged",
    remediated: "Remediated",
    ignored: "Ignored",
    approved: "Approved",
    rejected: "Rejected",
    applied: "Applied",
    expired: "Expired",
    validated: "Validated",
    review: "In review",
    draft: "Draft",
    deployed: "Deployed",
    archived: "Archived",
    connected: "Connected",
    disconnected: "Disconnected",
    unknown: "Unknown",
    pending: "Pending",
    provisioning: "Provisioning",
    running: "Running",
    completed: "Completed",
    failed: "Failed",
    ok: "OK",
    error: "Error",
    online: "Online",
    offline: "Offline",
    maintenance: "Maintenance",
    unregistered: "Unregistered",
    registered: "Registered",
    down: "Down",
    revoked: "Revoked",
    expired_cert: "Expired",
    in_sync: "In sync",
    failover_requested: "Failover requested",
  },
};

const COLORS: Record<string, ChipColor> = {
  online: "success",
  active: "success",
  connected: "success",
  completed: "success",
  deployed: "success",
  healthy: "success",
  approved: "success",
  validated: "success",
  enabled: "success",
  applied: "success",
  ok: "success",
  registered: "info",
  pending: "warning",
  provisioning: "warning",
  maintenance: "warning",
  warning: "warning",
  review: "warning",
  degraded: "warning",
  trial: "warning",
  draft: "default",
  archived: "default",
  ignored: "default",
  inactive: "default",
  unknown: "default",
  unregistered: "default",
  disconnected: "error",
  offline: "error",
  error: "error",
  failed: "error",
  down: "error",
  unhealthy: "error",
  locked: "error",
  suspended: "error",
  rejected: "error",
  cancelled: "error",
  revoked: "error",
  expired: "error",
  in_sync: "success",
  failover_requested: "warning",
  ready: "success",
  generating: "warning",
  skipped: "default",
};

export interface StatusChipProps {
  status?: string | null;
  label?: string;
  size?: ChipProps["size"];
  variant?: ChipProps["variant"];
}

export function StatusChip({ status, label, size = "small", variant = "outlined" }: StatusChipProps) {
  const key = (status ?? "unknown").toLowerCase();
  const text = label ?? LABELS[key] ?? titleCase(key);
  const color = COLORS[key] ?? "default";
  const dotColor = color === "default" ? "text.disabled" : `${color}.main`;

  return (
    <Chip
      size={size}
      variant={variant}
      color={color}
      label={text}
      icon={
        <Box
          component="span"
          sx={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            backgroundColor: dotColor,
            ml: 1.25,
            mr: -1,
          }}
        />
      }
      sx={{ "& .MuiChip-icon": { order: -1 } }}
    />
  );
}

export default StatusChip;
