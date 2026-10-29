import type { ReactNode } from "react";
import { Box, Stack, Typography } from "@mui/material";
import InboxOutlinedIcon from "@mui/icons-material/InboxOutlined";

export interface EmptyStateProps {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}

export function EmptyState({ title, description, icon, action, compact = false }: EmptyStateProps) {
  return (
    <Stack
      alignItems="center"
      justifyContent="center"
      spacing={1}
      sx={{ py: compact ? 4 : 7, px: 2, textAlign: "center" }}
    >
      <Box sx={{ color: "text.disabled", "& svg": { fontSize: 40 } }}>
        {icon ?? <InboxOutlinedIcon fontSize="large" />}
      </Box>
      <Typography variant="h6" component="div">
        {title}
      </Typography>
      {description && (
        <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 460 }}>
          {description}
        </Typography>
      )}
      {action && <Box sx={{ pt: 1 }}>{action}</Box>}
    </Stack>
  );
}

export default EmptyState;
