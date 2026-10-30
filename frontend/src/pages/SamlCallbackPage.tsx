import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Box, Button, Stack, Typography } from "@mui/material";

import { authApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { markCookieSession, setTenantId } from "@/api/tokenStore";
import LoadingScreen from "@/components/LoadingScreen";
import { useAppDispatch } from "@/store/hooks";
import { setUser } from "@/store/authSlice";
import { brandGradient } from "@/theme";

/**
 * Landing page for the SAML assertion consumer service.
 *
 * The backend validates the assertion, sets the HttpOnly auth cookies and
 * redirects here. The SPA cannot read those cookies, so it calls `/auth/me` to
 * load the principal and then records a cookie-session marker before routing
 * into the console. Errors are passed in the URL fragment so they never reach
 * the server logs.
 */
export function SamlCallbackPage() {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const fragment = window.location.hash.replace(/^#/, "");
    const params = new URLSearchParams(fragment);
    const failure = params.get("error");
    if (failure) {
      setError(failure);
      return;
    }

    authApi
      .me()
      .then((user) => {
        markCookieSession();
        setTenantId(user.tenant_id);
        dispatch(setUser(user));
        navigate("/dashboard", { replace: true });
      })
      .catch((cause) => setError(toApiError(cause).message));
  }, [dispatch, navigate]);

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
          <Typography variant="body2" color="text.secondary">
            The identity provider response could not be validated. Try again, or sign in with your platform
            credentials if the problem persists.
          </Typography>
          <Button variant="contained" onClick={() => navigate("/login", { replace: true })}>
            Return to sign in
          </Button>
        </Stack>
      </Box>
    </Box>
  );
}

export default SamlCallbackPage;
