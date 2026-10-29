import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  FormControlLabel,
  InputAdornment,
  Link,
  Paper,
  Stack,
  TextField,
  Typography,
  alpha,
} from "@mui/material";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import PersonOutlineIcon from "@mui/icons-material/PersonOutline";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import VisibilityOffOutlinedIcon from "@mui/icons-material/VisibilityOffOutlined";
import IconButton from "@mui/material/IconButton";
import ShieldOutlinedIcon from "@mui/icons-material/ShieldOutlined";
import VerifiedUserOutlinedIcon from "@mui/icons-material/VerifiedUserOutlined";
import PolicyOutlinedIcon from "@mui/icons-material/PolicyOutlined";
import BackupOutlinedIcon from "@mui/icons-material/BackupOutlined";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import { useQuery } from "@tanstack/react-query";

import { authApi } from "@/api/endpoints";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { clearError, ldapLogin, login, resetMfa, verifyMfa } from "@/store/authSlice";
import { brandGradient } from "@/theme";
import { safeRedirect } from "@/utils/redirect";

const FEATURES = [
  { icon: PolicyOutlinedIcon, text: "Policy-as-code with approvals, drift detection and GitOps" },
  { icon: VerifiedUserOutlinedIcon, text: "Immutable, hash-chained audit trail for every change" },
  { icon: BackupOutlinedIcon, text: "Signed, encrypted configuration backups with verified restores" },
  { icon: FactCheckOutlinedIcon, text: "CIS, ISO 27001, NIS2, PCI DSS and SOC 2 evidence on demand" },
];

export function LoginPage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  const { status, user, error, mfaRequired, challengeToken, mfaMethods, hydrated } = useAppSelector(
    (state) => state.auth,
  );

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [tenant, setTenant] = useState("");
  const [useLdap, setUseLdap] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const providers = useQuery({
    queryKey: ["auth", "providers"],
    queryFn: () => authApi.providers(),
    staleTime: 300_000,
    retry: 1,
  });

  const redirectTo = safeRedirect((location.state as { from?: string } | null)?.from);

  useEffect(() => {
    dispatch(clearError());
    return () => {
      dispatch(clearError());
    };
  }, [dispatch]);

  if (hydrated && status === "authenticated" && user) {
    return <Navigate to={redirectTo} replace />;
  }

  const submitCredentials = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      const credentials = {
        username: username.trim(),
        password,
        tenant: tenant.trim() || null,
      };
      if (useLdap) {
        await dispatch(ldapLogin(credentials)).unwrap();
      } else {
        await dispatch(login(credentials)).unwrap();
      }
    } catch {
      /* the slice surfaces the error */
    } finally {
      setSubmitting(false);
    }
  };

  const submitMfa = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await dispatch(verifyMfa({ code: code.trim(), challenge_token: challengeToken })).unwrap();
      navigate(redirectTo, { replace: true });
    } catch {
      /* the slice surfaces the error */
    } finally {
      setSubmitting(false);
    }
  };

  const startOidc = async () => {
    try {
      const result = await authApi.oidcAuthorize(tenant.trim() || undefined, false);
      window.location.assign(result.authorization_url);
    } catch {
      /* surfaced by the API error toast on the next request; keep the form usable */
    }
  };

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", bgcolor: "background.default" }}>
      <Box
        sx={{
          display: { xs: "none", lg: "flex" },
          flexDirection: "column",
          justifyContent: "space-between",
          width: "46%",
          maxWidth: 720,
          p: 6,
          color: "#fff",
          background: brandGradient,
          position: "relative",
          overflow: "hidden",
          "&::after": {
            content: '""',
            position: "absolute",
            inset: 0,
            background:
              "radial-gradient(700px 380px at 88% 8%, rgba(255,255,255,0.18), transparent 60%), radial-gradient(600px 400px at 5% 95%, rgba(14,165,183,0.45), transparent 65%)",
            pointerEvents: "none",
          },
        }}
      >
        <Stack direction="row" spacing={1.5} alignItems="center" sx={{ position: "relative", zIndex: 1 }}>
          <Box
            sx={{
              width: 44,
              height: 44,
              borderRadius: 2.5,
              display: "grid",
              placeItems: "center",
              bgcolor: "rgba(255,255,255,0.16)",
              border: "1px solid rgba(255,255,255,0.24)",
            }}
          >
            <ShieldOutlinedIcon />
          </Box>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 800, letterSpacing: "0.04em" }}>
              OFME
            </Typography>
            <Typography variant="caption" sx={{ opacity: 0.8 }}>
              OPNsense Fleet Manager Enterprise
            </Typography>
          </Box>
        </Stack>

        <Box sx={{ position: "relative", zIndex: 1, maxWidth: 520, my: 6 }}>
          <Typography variant="h1" sx={{ fontSize: { lg: "2.4rem" }, lineHeight: 1.15, mb: 2 }}>
            One control plane for every firewall you run.
          </Typography>
          <Typography variant="body1" sx={{ opacity: 0.86, mb: 4 }}>
            Inventory, configuration, SD-WAN, zero-touch provisioning, compliance and audit for ten to
            ten thousand OPNsense appliances.
          </Typography>
          <Stack spacing={2}>
            {FEATURES.map(({ icon: Icon, text }) => (
              <Stack key={text} direction="row" spacing={1.5} alignItems="flex-start">
                <Box
                  sx={{
                    width: 32,
                    height: 32,
                    borderRadius: 1.5,
                    display: "grid",
                    placeItems: "center",
                    bgcolor: "rgba(255,255,255,0.14)",
                    flexShrink: 0,
                  }}
                >
                  <Icon fontSize="small" />
                </Box>
                <Typography variant="body2" sx={{ opacity: 0.92, pt: 0.4 }}>
                  {text}
                </Typography>
              </Stack>
            ))}
          </Stack>
        </Box>

        <Stack direction="row" spacing={2} sx={{ position: "relative", zIndex: 1, opacity: 0.7 }}>
          <Typography variant="caption">OFME v1.0.0</Typography>
          <Typography variant="caption">API v1</Typography>
          <Typography variant="caption">TLS Â· MFA Â· RBAC</Typography>
        </Stack>
      </Box>

      <Box
        sx={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          p: { xs: 2.5, sm: 5 },
        }}
      >
        <Box sx={{ width: "100%", maxWidth: 440 }}>
          <Stack
            direction="row"
            spacing={1.25}
            alignItems="center"
            sx={{ display: { lg: "none" }, mb: 4 }}
          >
            <Box
              sx={{
                width: 38,
                height: 38,
                borderRadius: 2,
                display: "grid",
                placeItems: "center",
                color: "#fff",
                background: brandGradient,
              }}
            >
              <ShieldOutlinedIcon fontSize="small" />
            </Box>
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
                OFME
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Fleet Manager Enterprise
              </Typography>
            </Box>
          </Stack>

          <Typography variant="h1" sx={{ mb: 0.5 }}>
            {mfaRequired ? "Two-factor verification" : "Sign in"}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            {mfaRequired
              ? "Enter the six-digit code from your authenticator app to finish signing in."
              : "Use your platform credentials. All sessions are audited and expire automatically."}
          </Typography>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => dispatch(clearError())}>
              {error}
            </Alert>
          )}

          {mfaRequired ? (
            <Paper variant="outlined" sx={{ p: 3 }}>
              <Stack component="form" spacing={2.25} onSubmit={submitMfa}>
                <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                  {(mfaMethods.length ? mfaMethods : ["totp"]).map((method) => (
                    <Chip key={method} size="small" label={method.toUpperCase()} color="primary" variant="outlined" />
                  ))}
                </Stack>
                <TextField
                  label="Authentication code"
                  value={code}
                  onChange={(event) => setCode(event.target.value.replace(/\s+/g, "").slice(0, 12))}
                  autoFocus
                  required
                  inputProps={{ inputMode: "numeric", pattern: "[0-9]*", maxLength: 12 }}
                  helperText="TOTP codes rotate every 30 seconds."
                />
                <Button
                  type="submit"
                  variant="contained"
                  size="large"
                  disabled={submitting || code.trim().length < 6}
                  startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : undefined}
                >
                  Verify and continue
                </Button>
                <Button
                  type="button"
                  color="inherit"
                  onClick={() => {
                    setCode("");
                    dispatch(resetMfa());
                  }}
                >
                  Back to credentials
                </Button>
              </Stack>
            </Paper>
          ) : (
            <Paper variant="outlined" sx={{ p: 3 }}>
              <Stack component="form" spacing={2.25} onSubmit={submitCredentials}>
                <TextField
                  label="Username or e-mail"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  autoFocus
                  required
                  InputProps={{
                    startAdornment: (
                      <InputAdornment position="start">
                        <PersonOutlineIcon fontSize="small" />
                      </InputAdornment>
                    ),
                  }}
                />
                <TextField
                  label="Password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  required
                  InputProps={{
                    startAdornment: (
                      <InputAdornment position="start">
                        <LockOutlinedIcon fontSize="small" />
                      </InputAdornment>
                    ),
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton
                          size="small"
                          onClick={() => setShowPassword((value) => !value)}
                          aria-label={showPassword ? "Hide password" : "Show password"}
                          edge="end"
                        >
                          {showPassword ? (
                            <VisibilityOffOutlinedIcon fontSize="small" />
                          ) : (
                            <VisibilityOutlinedIcon fontSize="small" />
                          )}
                        </IconButton>
                      </InputAdornment>
                    ),
                  }}
                />
                <TextField
                  label="Tenant slug"
                  value={tenant}
                  onChange={(event) => setTenant(event.target.value)}
                  helperText="Optional. Leave blank when your account belongs to the default tenant."
                  autoComplete="organization"
                />
                {providers.data?.ldap && (
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={useLdap}
                        onChange={(event) => setUseLdap(event.target.checked)}
                        size="small"
                      />
                    }
                    label={
                      <Typography variant="body2">
                        Authenticate against LDAP / Active Directory
                      </Typography>
                    }
                  />
                )}
                <Button
                  type="submit"
                  variant="contained"
                  size="large"
                  disabled={submitting || !username.trim() || !password}
                  startIcon={submitting ? <CircularProgress size={18} color="inherit" /> : undefined}
                >
                  Sign in
                </Button>

                {(providers.data?.oidc || providers.data?.entra_id) && (
                  <>
                    <Divider sx={{ my: 0.5 }}>or</Divider>
                    <Button
                      type="button"
                      variant="outlined"
                      size="large"
                      onClick={startOidc}
                      startIcon={<VerifiedUserOutlinedIcon />}
                    >
                      Continue with single sign-on
                    </Button>
                  </>
                )}
              </Stack>
            </Paper>
          )}

          <Box sx={{ mt: 2.5, textAlign: "center" }}>
            <Typography variant="caption" color="text.secondary">
              Protected by login lockout, MFA and an immutable audit trail.{" "}
              <Link href="/docs" underline="hover" target="_blank" rel="noreferrer">
                API documentation
              </Link>
            </Typography>
          </Box>

          <Box
            sx={{
              mt: 4,
              p: 2,
              borderRadius: 2,
              border: 1,
              borderColor: "divider",
              bgcolor: (theme) => alpha(theme.palette.primary.main, 0.04),
            }}
          >
            <Typography variant="caption" color="text.secondary" component="div">
              <strong>Sessions expire after the configured access-token lifetime.</strong> A refresh token is
              rotated on every renewal; revoking all sessions is available from Settings â†’ Security.
            </Typography>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}

export default LoginPage;
