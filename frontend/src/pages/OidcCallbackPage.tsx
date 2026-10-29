import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Box, Button, Stack, Typography } from "@mui/material";

import { authApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { setTokens } from "@/api/tokenStore";
import LoadingScreen from "@/components/LoadingScreen";
import { useAppDispatch } from "@/store/hooks";
import { setUser } from "@/store/authSlice";
import { brandGradient } from "@/theme";

export function OidcCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const code = params.get("code");
  const state = params.get("state");

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    if (!code || !state) {
      setError("The identity provider did not return an authorization code and state.");
      return;
    }

    authApi
      .oidcCallback(code, state)
      .then((response) => {
        setTokens(response.access_token, response.refresh_token, response.expires_in);
        if (response.user) {
          dispatch(setUser(response.user));
          navigate("/dashboard", { replace: true });
        } else {
          navigate("/login", { replace: true });
        }
      })
      .catch((cause) => setError(toApiError(cause).message));
  }, [code, state, dispatch, navigate]);

  if (!error) return <LoadingScreen label="Completing single sign-on…" minHeight="100vh" />;

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        p: 3,
        background: brandGradient,
      }}
    >
      <Box sx={{ width: "100%", maxWidth: 520, bgcolor: "background.paper", borderRadius: 3, p: 4 }}>
        <Stack spacing={2}>
          <Typography variant="h2">Single sign-on failed</Typography>
          <Alert severity="error">{error}</Alert>
          <Button variant="contained" onClick={() => navigate("/login", { replace: true })}>
            Return to sign in
          </Button>
        </Stack>
      </Box>
    </Box>
  );
}

export default OidcCallbackPage;
