import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";

import type { ApiErrorBody, LoginResponse } from "./types";
import {
  clearTokens,
  emitSessionExpired,
  getAccessToken,
  getTenantId,
  setTokens,
} from "./tokenStore";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export const API_PREFIX = "/api/v1";

export const REFRESH_ENDPOINT = `${API_PREFIX}/auth/refresh`;

interface RetryableConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
  /** Set to true for endpoints that must never trigger a token refresh. */
  _skipRefresh?: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(message: string, options: { status?: number; code?: string; details?: unknown; requestId?: string | null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = options.status ?? 0;
    this.code = options.code ?? "network_error";
    this.details = options.details;
    this.requestId = options.requestId ?? null;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<ApiErrorBody>;
    const status = axiosError.response?.status ?? 0;
    const body = axiosError.response?.data;
    const envelope = body && typeof body === "object" ? body.error : undefined;
    if (envelope && typeof envelope.message === "string") {
      return new ApiError(envelope.message, {
        status,
        code: envelope.code,
        details: envelope.details,
        requestId: envelope.request_id,
      });
    }
    if (status === 0) {
      return new ApiError(
        axiosError.code === "ECONNABORTED"
          ? "The request timed out. The server did not respond in time."
          : "The backend is unreachable. Check your network connection.",
        { status: 0, code: axiosError.code ?? "network_error" },
      );
    }
    return new ApiError(axiosError.message || `Request failed with status ${status}`, { status });
  }
  if (error instanceof Error) return new ApiError(error.message);
  return new ApiError("An unexpected error occurred");
}

function applyAuthHeaders(config: InternalAxiosRequestConfig): void {
  // With HttpOnly cookies, the browser automatically sends them with same-origin requests.
  // We still set the Authorization header for API keys and explicit token usage.
  const token = getAccessToken();
  if (token && token !== "cookie") config.headers.set("Authorization", `Bearer ${token}`);
  const tenantId = getTenantId();
  if (tenantId) config.headers.set("X-Tenant-Id", tenantId);

  // CSRF token for state-changing operations (double-submit cookie pattern)
  const csrfCookie = document.cookie
    .split("; ")
    .find(row => row.startsWith("ofme_csrf_token="))
    ?.split("=")[1];
  if (csrfCookie) {
    config.headers.set("X-CSRF-Token", csrfCookie);
  }
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60_000,
  headers: { Accept: "application/json", "Content-Type": "application/json" },
  withCredentials: true, // Required for HttpOnly cookies
});

api.interceptors.request.use((config) => {
  applyAuthHeaders(config as InternalAxiosRequestConfig);
  return config;
});

let refreshPromise: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  // With HttpOnly cookies, the refresh token is sent automatically via cookie.
  // We don't need to pass it explicitly in the request body.
  if (!refreshPromise) {
    refreshPromise = axios
      .post<LoginResponse>(
        `${API_BASE_URL}${REFRESH_ENDPOINT}`,
        {}, // Refresh token comes from cookie
        { timeout: 30_000, withCredentials: true, headers: { Accept: "application/json", "Content-Type": "application/json" } },
      )
      .then((response) => {
        const pair = response.data;
        if (pair.mfa_required) {
          throw new ApiError("MFA is required; sign in again", { status: 401, code: "mfa_required" });
        }
        if (pair.access_token && pair.refresh_token) {
          setTokens(pair.access_token, pair.refresh_token, pair.expires_in);
        }
        return pair.access_token;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorBody>) => {
    const config = error.config as RetryableConfig | undefined;
    const status = error.response?.status;

    if (status === 401 && config && !config._retry && !config._skipRefresh) {
      config._retry = true;
      try {
        const token = await refreshAccessToken();
        config.headers.set("Authorization", `Bearer ${token}`);
        return api.request(config);
      } catch {
        clearTokens();
        emitSessionExpired();
        return Promise.reject(toApiError(error));
      }
    }

    if (status === 401) {
      clearTokens();
      emitSessionExpired();
    }
    return Promise.reject(toApiError(error));
  },
);

export interface RequestOptions {
  signal?: AbortSignal;
  timeout?: number;
  headers?: Record<string, string>;
  skipRefresh?: boolean;
  responseType?: "json" | "blob" | "text" | "arraybuffer";
}

function mergeOptions(options?: RequestOptions): AxiosRequestConfig {
  const config: AxiosRequestConfig & { _skipRefresh?: boolean } = {
    signal: options?.signal,
    timeout: options?.timeout,
    headers: options?.headers,
    responseType: options?.responseType,
  };
  if (options?.skipRefresh) config._skipRefresh = true;
  return config;
}

export async function get<T>(url: string, params?: Record<string, unknown>, options?: RequestOptions): Promise<T> {
  const response = await api.get<T>(url, { params, ...mergeOptions(options) });
  return response.data;
}

export async function post<T>(url: string, body?: unknown, options?: RequestOptions): Promise<T> {
  const response = await api.post<T>(url, body, mergeOptions(options));
  return response.data;
}

/** Fetch a binary response (config backups, evidence bundles) with auth applied. */
export async function getBlob(url: string, options?: RequestOptions): Promise<Blob> {
  const response = await api.get<Blob>(url, {
    ...mergeOptions(options),
    responseType: "blob",
  });
  return response.data;
}

/**
 * Upload a multipart form. Axios lets the browser set the boundary, so the
 * content type is only hinted here (CSV import).
 */
export async function postForm<T>(
  url: string,
  body: FormData,
  options?: RequestOptions,
): Promise<T> {
  const response = await api.post<T>(url, body, {
    ...mergeOptions(options),
    headers: { ...(options?.headers ?? {}), "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

export async function patch<T>(url: string, body?: unknown, options?: RequestOptions): Promise<T> {
  const response = await api.patch<T>(url, body, mergeOptions(options));
  return response.data;
}

export async function put<T>(url: string, body?: unknown, options?: RequestOptions): Promise<T> {
  const response = await api.put<T>(url, body, mergeOptions(options));
  return response.data;
}

export async function del<T>(url: string, options?: RequestOptions): Promise<T> {
  const response = await api.delete<T>(url, mergeOptions(options));
  return response.data;
}

/** Strip undefined/null values so query strings stay compact. */
export function cleanParams(params: Record<string, unknown> | undefined): Record<string, unknown> {
  if (!params) return {};
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ""),
  );
}

export { API_BASE_URL };
