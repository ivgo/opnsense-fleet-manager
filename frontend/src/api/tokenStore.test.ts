import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  accessTokenExpired,
  clearTokens,
  decodeJwtExpiry,
  getAccessToken,
  getRefreshToken,
  getTenantId,
  getTokens,
  resetStoreForTests,
  SESSION_EXPIRED_EVENT,
  setTenantId,
  setTokens,
  emitSessionExpired,
} from "@/api/tokenStore";

function makeJwt(expSeconds: number): string {
  const payload = window
    .btoa(JSON.stringify({ exp: expSeconds }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `header.${payload}.signature`;
}

describe("tokenStore", () => {
  beforeEach(() => {
    resetStoreForTests();
    window.localStorage.clear();
  });

  it("persists and clears the token pair (cookie-based auth)", () => {
    setTokens("access-token", "refresh-token", 3600);

    // With cookie-based auth, getAccessToken returns "cookie" to indicate cookie-based session
    expect(getAccessToken()).toBe("cookie");
    expect(getRefreshToken()).toBe("cookie");
    expect(getTokens()?.expiresAt).toBeGreaterThan(Date.now());

    clearTokens();
    expect(getAccessToken()).toBeNull();
    expect(getRefreshToken()).toBeNull();
  });

  it("rehydrates tokens from localStorage after the memory cache is dropped", () => {
    setTokens("access-token", "refresh-token", 3600);
    resetStoreForTests();

    // After rehydration, tokens show as "cookie" (placeholder for cookie-based auth)
    expect(getTokens()).toEqual(
      expect.objectContaining({ accessToken: "cookie", refreshToken: "cookie" }),
    );
  });

  it("stores and clears the tenant override", () => {
    setTenantId("tenant-1");
    expect(getTenantId()).toBe("tenant-1");
    setTenantId(null);
    expect(getTenantId()).toBeNull();
  });

  it("enforces the expiry leeway", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    setTokens("access-token", "refresh-token", 60);

    expect(accessTokenExpired(30)).toBe(false);

    vi.advanceTimersByTime(31_000);
    expect(accessTokenExpired(30)).toBe(true);

    vi.useRealTimers();
  });

  it("decodes JWT expiry values defensively", () => {
    expect(decodeJwtExpiry(makeJwt(1_700_000_000))).toBe(1_700_000_000_000);
    expect(decodeJwtExpiry("not-a-jwt")).toBe(0);
    expect(decodeJwtExpiry("")).toBe(0);
  });

  it("emits a session-expired event", () => {
    const listener = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, listener);

    emitSessionExpired();
    expect(listener).toHaveBeenCalledTimes(1);

    window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
  });
});
