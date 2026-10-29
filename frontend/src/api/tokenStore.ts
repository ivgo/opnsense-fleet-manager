/**
 * Persistence for credentials and the tenant context.
 *
 * Tokens are now stored in HttpOnly Secure SameSite cookies set by the backend.
 * This module provides in-memory caching for token expiry tracking and tenant context.
 * The actual tokens are read from cookies by axios interceptors automatically.
 */

const TENANT_KEY = "ofme.tenant_id";
const EXPIRES_KEY = "ofme.access_expires_at";

export interface StoredTokens {
  accessToken: string;
  refreshToken: string;
  /** Epoch milliseconds at which the access token expires (best effort). */
  expiresAt: number;
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function read(key: string): string | null {
  try {
    return storage()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    storage()?.setItem(key, value);
  } catch {
    /* private mode / quota - keep the in-memory copy working */
  }
}

function remove(key: string): void {
  try {
    storage()?.removeItem(key);
  } catch {
    /* ignore */
  }
}

let memoryTokens: StoredTokens | null = null;

export function decodeJwtExpiry(token: string): number {
  try {
    const payload = token.split(".")[1];
    if (!payload) return 0;
    const normalised = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalised.padEnd(Math.ceil(normalised.length / 4) * 4, "=");
    const json = JSON.parse(window.atob(padded)) as { exp?: number };
    return typeof json.exp === "number" ? json.exp * 1000 : 0;
  } catch {
    return 0;
  }
}

export function setTokens(accessToken: string, refreshToken: string, expiresInSeconds = 0): void {
  // Tokens are now stored in HttpOnly cookies set by the backend
  // We only store the expiry in memory/localStorage for client-side logic
  const expiresAt = expiresInSeconds > 0 ? Date.now() + expiresInSeconds * 1000 : decodeJwtExpiry(accessToken);
  memoryTokens = { accessToken, refreshToken, expiresAt };
  write(EXPIRES_KEY, String(expiresAt));
}

export function getTokens(): StoredTokens | null {
  if (memoryTokens) return memoryTokens;
  // For cookie-based auth, we don't have direct access to tokens from JS
  // Return a placeholder with expiry info - actual tokens are sent via cookies
  const expiresAt = Number(read(EXPIRES_KEY) ?? "0");
  if (!expiresAt) return null;
  memoryTokens = { accessToken: "cookie", refreshToken: "cookie", expiresAt };
  return memoryTokens;
}

export function getAccessToken(): string | null {
  // Returns "cookie" to indicate cookie-based auth, or null if not authenticated
  const tokens = getTokens();
  return tokens ? "cookie" : null;
}

export function getRefreshToken(): string | null {
  // Returns "cookie" to indicate cookie-based auth, or null if not authenticated
  const tokens = getTokens();
  return tokens ? "cookie" : null;
}

export function clearTokens(): void {
  memoryTokens = null;
  remove(EXPIRES_KEY);
  // Note: Actual cookie clearing happens on backend via /auth/logout
}

export function accessTokenExpired(leewaySeconds = 30): boolean {
  const tokens = getTokens();
  if (!tokens) return true;
  if (!tokens.expiresAt) return false;
  return tokens.expiresAt - leewaySeconds * 1000 <= Date.now();
}

export function setTenantId(tenantId: string | null): void {
  if (tenantId) write(TENANT_KEY, tenantId);
  else remove(TENANT_KEY);
}

export function getTenantId(): string | null {
  return read(TENANT_KEY);
}

export const SESSION_EXPIRED_EVENT = "ofme:session-expired";

export function emitSessionExpired(): void {
  try {
    window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
  } catch {
    /* non-browser environment */
  }
}

export function resetStoreForTests(): void {
  memoryTokens = null;
}
