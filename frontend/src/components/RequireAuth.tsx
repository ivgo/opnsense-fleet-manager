import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import LoadingScreen from "@/components/LoadingScreen";
import { useAppSelector } from "@/store/hooks";

export interface RequireAuthProps {
  children: ReactNode;
}

export function RequireAuth({ children }: RequireAuthProps) {
  const { status, hydrated, user } = useAppSelector((state) => state.auth);
  const location = useLocation();

  if (!hydrated || status === "loading" || status === "idle") {
    return <LoadingScreen label="Restoring your session…" minHeight="100vh" />;
  }
  if (status !== "authenticated" || !user) {
    return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  }
  return <>{children}</>;
}

export interface PermissionGateProps {
  permission?: string;
  permissions?: string[];
  mode?: "any" | "all";
  fallback?: ReactNode;
  children: ReactNode;
}

export function PermissionGate({
  permission,
  permissions,
  mode = "any",
  fallback = null,
  children,
}: PermissionGateProps) {
  const user = useAppSelector((state) => state.auth.user);
  if (!user) return <>{fallback}</>;
  if (user.is_superadmin) return <>{children}</>;

  const granted = new Set(user.permissions);
  const required = permissions ?? (permission ? [permission] : []);
  if (required.length === 0) return <>{children}</>;

  const allowed =
    mode === "all" ? required.every((item) => granted.has(item)) : required.some((item) => granted.has(item));

  return <>{allowed ? children : fallback}</>;
}

export default RequireAuth;
