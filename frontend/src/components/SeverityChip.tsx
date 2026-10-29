import { Chip, type ChipProps } from "@mui/material";

import { ALERT_SEVERITY_LABELS } from "@/utils/constants";

const COLORS: Record<string, ChipProps["color"]> = {
  info: "info",
  warning: "warning",
  critical: "error",
};

export interface SeverityChipProps {
  severity?: string | null;
  size?: ChipProps["size"];
  variant?: ChipProps["variant"];
}

export function SeverityChip({ severity, size = "small", variant = "filled" }: SeverityChipProps) {
  const key = (severity ?? "info").toLowerCase();
  return (
    <Chip
      size={size}
      variant={variant}
      color={COLORS[key] ?? "default"}
      label={ALERT_SEVERITY_LABELS[key] ?? key}
      sx={{ minWidth: 74 }}
    />
  );
}

export default SeverityChip;
