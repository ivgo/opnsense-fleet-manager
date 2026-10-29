import type { ReactNode } from "react";
import { Box, Breadcrumbs, Link as MuiLink, Stack, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";

export interface Breadcrumb {
  label: string;
  to?: string;
}

export interface PageHeaderProps {
  title: string;
  subtitle?: ReactNode;
  breadcrumbs?: Breadcrumb[];
  actions?: ReactNode;
  meta?: ReactNode;
}

export function PageHeader({ title, subtitle, breadcrumbs, actions, meta }: PageHeaderProps) {
  return (
    <Stack
      direction={{ xs: "column", md: "row" }}
      justifyContent="space-between"
      alignItems={{ xs: "flex-start", md: "center" }}
      spacing={2}
      sx={{ mb: 3 }}
    >
      <Box sx={{ minWidth: 0 }}>
        {breadcrumbs && breadcrumbs.length > 0 && (
          <Breadcrumbs sx={{ mb: 0.75, "& .MuiBreadcrumbs-separator": { mx: 0.75 } }}>
            {breadcrumbs.map((crumb, index) =>
              crumb.to && index < breadcrumbs.length - 1 ? (
                <MuiLink
                  key={`${crumb.label}-${index}`}
                  component={RouterLink}
                  to={crumb.to}
                  underline="hover"
                  color="text.secondary"
                  variant="body2"
                >
                  {crumb.label}
                </MuiLink>
              ) : (
                <Typography key={`${crumb.label}-${index}`} variant="body2" color="text.secondary">
                  {crumb.label}
                </Typography>
              ),
            )}
          </Breadcrumbs>
        )}
        <Typography variant="h1" component="h1" sx={{ lineHeight: 1.2 }}>
          {title}
        </Typography>
        {subtitle && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 900 }}>
            {subtitle}
          </Typography>
        )}
        {meta}
      </Box>
      {actions && (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
          {actions}
        </Stack>
      )}
    </Stack>
  );
}

export default PageHeader;
