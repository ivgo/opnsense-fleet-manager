import { useMemo } from "react";

import type { AuthUser } from "@/api/types";
import { useAppSelector } from "@/store/hooks";

export interface PermissionsApi {
  user: AuthUser | null;
  can: (permission: string) => boolean;
  canAny: (...permissions: string[]) => boolean;
  canAll: (...permissions: string[]) => boolean;
  hasRole: (role: string) => boolean;
  isSuperadmin: boolean;
}

export function usePermissions(): PermissionsApi {
  const user = useAppSelector((state) => state.auth.user);

  return useMemo(() => {
    const granted = new Set(user?.permissions ?? []);
    const roles = new Set(user?.roles ?? []);
    const isSuperadmin = Boolean(user?.is_superadmin);
    const can = (permission: string) => isSuperadmin || granted.has(permission) || granted.has("*");
    return {
      user,
      can,
      canAny: (...permissions: string[]) => permissions.some(can),
      canAll: (...permissions: string[]) => permissions.every(can),
      hasRole: (role: string) => roles.has(role),
      isSuperadmin,
    };
  }, [user]);
}
