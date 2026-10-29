import { useNavigate } from "react-router-dom";
import { Box, Button, Stack, Typography } from "@mui/material";
import SearchOffOutlinedIcon from "@mui/icons-material/SearchOffOutlined";

export function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <Stack alignItems="center" justifyContent="center" spacing={2} sx={{ minHeight: "60vh", textAlign: "center" }}>
      <Box sx={{ color: "text.disabled" }}>
        <SearchOffOutlinedIcon sx={{ fontSize: 64 }} />
      </Box>
      <Typography variant="h1">404</Typography>
      <Typography variant="h4" component="h2">
        This page does not exist
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 460 }}>
        The link may be outdated, or you may not have access to the requested resource. Use the navigation to
        return to a section you can access.
      </Typography>
      <Stack direction="row" spacing={1.5}>
        <Button variant="contained" onClick={() => navigate("/dashboard")}>
          Go to dashboard
        </Button>
        <Button variant="outlined" onClick={() => navigate(-1)}>
          Go back
        </Button>
      </Stack>
    </Stack>
  );
}

export default NotFoundPage;
