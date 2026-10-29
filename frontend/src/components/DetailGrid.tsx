import type { ReactNode } from "react";
import { Box, Paper, Stack, Typography } from "@mui/material";

export interface DetailItem {
  label: string;
  value: ReactNode;
  span?: 1 | 2 | 3;
}

export interface DetailGridProps {
  items: DetailItem[];
  columns?: 1 | 2 | 3;
  dense?: boolean;
}

export function DetailGrid({ items, columns = 2, dense = false }: DetailGridProps) {
  return (
    <Box
      sx={{
        display: "grid",
        gap: dense ? 1.25 : 2,
        gridTemplateColumns: {
          xs: "1fr",
          sm: `repeat(${Math.min(columns, 2)}, minmax(0, 1fr))`,
          md: `repeat(${columns}, minmax(0, 1fr))`,
        },
      }}
    >
      {items.map((item, index) => (
        <Box
          key={`${item.label}-${index}`}
          sx={{ gridColumn: item.span && item.span > 1 ? { md: `span ${item.span}` } : undefined, minWidth: 0 }}
        >
          <Typography variant="overline" color="text.secondary" component="div">
            {item.label}
          </Typography>
          <Box sx={{ mt: 0.25, typography: "body2", wordBreak: "break-word" }}>{item.value}</Box>
        </Box>
      ))}
    </Box>
  );
}

export interface SectionCardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  padded?: boolean;
  sx?: object;
}

export function SectionCard({ title, subtitle, actions, children, padded = true, sx }: SectionCardProps) {
  return (
    <Paper variant="outlined" sx={{ overflow: "hidden", ...sx }}>
      {(title || actions) && (
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1}
          alignItems={{ xs: "flex-start", sm: "center" }}
          justifyContent="space-between"
          sx={{ px: padded ? 2.25 : 1.5, py: 1.5, borderBottom: 1, borderColor: "divider" }}
        >
          <Box>
            {title && (
              <Typography variant="h5" component="h2">
                {title}
              </Typography>
            )}
            {subtitle && (
              <Typography variant="caption" color="text.secondary">
                {subtitle}
              </Typography>
            )}
          </Box>
          {actions && (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {actions}
            </Stack>
          )}
        </Stack>
      )}
      <Box sx={{ p: padded ? 2.25 : 0 }}>{children}</Box>
    </Paper>
  );
}

export default DetailGrid;
