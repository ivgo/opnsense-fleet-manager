/**
 * Persistence for credentials and the tenant context.
 *
 * Tokens live in localStorage because the console is a pure SPA served from the
 * same origin as the API. The store deliberately exposes no React dependency so
 * that the axios interceptors can use it outside of components.
 */

const ACCESS_KEY = "ofme.access_token";
const REFRESH_KEY = "ofme.refresh_token";
const EXPIRES_KEY = "ofme.access_expires_at";
const TENANT_KEY = "ofme.tenant_id";

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
  const expiresAt = expiresInSeconds > 0 ? Date.now() + expiresInSeconds * 1000 : decodeJwtExpiry(accessToken);
  memoryTokens = { accessToken, refreshToken, expiresAt };
  write(ACCESS_KEY, accessToken);
  write(REFRESH_KEY, refreshToken);
  write(EXPIRES_KEY, String(expiresAt));
}

export function getTokens(): StoredTokens | null {
  if (memoryTokens) return memoryTokens;
  const accessToken = read(ACCESS_KEY);
  const refreshToken = read(REFRESH_KEY);
  if (!accessToken || !refreshToken) return null;
  const expiresAt = Number(read(EXPIRES_KEY) ?? "0") || decodeJwtExpiry(accessToken);
  memoryTokens = { accessToken, refreshToken, expiresAt };
  return memoryTokens;
}

export function getAccessToken(): string | null {
  return getTokens()?.accessToken ?? null;
}

export function getRefreshToken(): string | null {
  return getTokens()?.refreshToken ?? null;
}

export function clearTokens(): void {
  memoryTokens = null;
  remove(ACCESS_KEY);
  remove(REFRESH_KEY);
  remove(EXPIRES_KEY);
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
