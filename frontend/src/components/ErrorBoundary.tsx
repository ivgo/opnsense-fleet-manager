import { Component, type ErrorInfo, type ReactNode } from "react";
import { Alert, AlertTitle, Box, Button, Stack, Typography } from "@mui/material";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
  info: string | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, info: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error, info: null };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.setState({ error, info: info.componentStack ?? null });
    // The API access log receives client errors through the browser console only;
    // no telemetry payload is sent from the console itself.
    console.error("Unhandled UI error", error, info);
  }

  private reload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <Box sx={{ p: 4, maxWidth: 900, mx: "auto" }}>
        <Alert severity="error">
          <AlertTitle>Something went wrong</AlertTitle>
          <Typography variant="body2" sx={{ mb: 2 }}>
            The console hit an unexpected error. Your session is intact; reloading usually resolves it.
          </Typography>
          <Stack spacing={1}>
            <Typography variant="caption" component="pre" sx={{ whiteSpace: "pre-wrap", m: 0 }}>
              {error.message}
            </Typography>
            {info && (
              <Typography
                variant="caption"
                component="pre"
                color="text.secondary"
                sx={{ whiteSpace: "pre-wrap", m: 0, maxHeight: 220, overflow: "auto" }}
              >
                {info}
              </Typography>
            )}
            <Box>
              <Button variant="contained" onClick={this.reload}>
                Reload console
              </Button>
            </Box>
          </Stack>
        </Alert>
      </Box>
    );
  }
}

export default ErrorBoundary;
