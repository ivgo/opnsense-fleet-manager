import { Alert, AlertTitle, Box, Button, Stack } from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";

export interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  compact?: boolean;
}

export function ErrorState({ title = "Unable to load data", message, onRetry, compact }: ErrorStateProps) {
  return (
    <Box sx={{ py: compact ? 2 : 4 }}>
      <Alert
        severity="error"
        action={
          onRetry ? (
            <Button color="inherit" size="small" startIcon={<RefreshIcon />} onClick={onRetry}>
              Retry
            </Button>
          ) : undefined
        }
      >
        <AlertTitle>{title}</AlertTitle>
        <Stack spacing={0.5}>
          <Box component="span">{message ?? "The request failed. Try again in a moment."}</Box>
        </Stack>
      </Alert>
    </Box>
  );
}

export default ErrorState;
