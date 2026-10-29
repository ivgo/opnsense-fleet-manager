import { Box, CircularProgress, Stack, Typography } from "@mui/material";

export interface LoadingScreenProps {
  label?: string;
  minHeight?: number | string;
}

export function LoadingScreen({ label = "Loading…", minHeight = "60vh" }: LoadingScreenProps) {
  return (
    <Stack alignItems="center" justifyContent="center" spacing={2} sx={{ minHeight }}>
      <Box sx={{ position: "relative", display: "inline-flex" }}>
        <CircularProgress size={44} thickness={3.4} />
      </Box>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
    </Stack>
  );
}

export default LoadingScreen;
