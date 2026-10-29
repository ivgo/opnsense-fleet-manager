import type { ReactNode } from "react";
import { Box, Card, CardContent, Stack, Typography, alpha, useTheme } from "@mui/material";
import type { SvgIconComponent } from "@mui/icons-material";

export type StatTone = "primary" | "success" | "warning" | "error" | "info" | "neutral";

const TONE_COLORS: Record<StatTone, string> = {
  primary: "#2f81f7",
  success: "#16a34a",
  warning: "#d97706",
  error: "#dc2626",
  info: "#0891b2",
  neutral: "#64748b",
};

export interface StatCardProps {
  label: string;
  value: ReactNode;
  icon?: SvgIconComponent;
  tone?: StatTone;
  hint?: ReactNode;
  onClick?: () => void;
}

export function StatCard({ label, value, icon: Icon, tone = "primary", hint, onClick }: StatCardProps) {
  const theme = useTheme();
  const color = TONE_COLORS[tone];

  return (
    <Card
      onClick={onClick}
      sx={{
        height: "100%",
        cursor: onClick ? "pointer" : "default",
        transition: "transform 120ms ease, box-shadow 120ms ease",
        "&:hover": onClick ? { transform: "translateY(-1px)", boxShadow: theme.shadows[4] } : undefined,
      }}
    >
      <CardContent sx={{ py: 2, px: 2.25, "&:last-child": { pb: 2 } }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="overline" color="text.secondary" noWrap>
              {label}
            </Typography>
            <Typography variant="h2" sx={{ fontSize: "1.9rem", lineHeight: 1.15, mt: 0.25 }}>
              {value}
            </Typography>
            {hint && (
              <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
                {hint}
              </Typography>
            )}
          </Box>
          {Icon && (
            <Box
              sx={{
                width: 42,
                height: 42,
                borderRadius: 2,
                display: "grid",
                placeItems: "center",
                color,
                backgroundColor: alpha(color, theme.palette.mode === "dark" ? 0.2 : 0.1),
                flexShrink: 0,
              }}
            >
              <Icon fontSize="small" />
            </Box>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}

export default StatCard;
