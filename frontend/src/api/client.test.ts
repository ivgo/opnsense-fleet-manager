import { AxiosError, type AxiosResponse } from "axios";
import { describe, expect, it } from "vitest";

import { ApiError, cleanParams, toApiError } from "@/api/client";

describe("cleanParams", () => {
  it("drops empty values while keeping false and zero", () => {
    expect(
      cleanParams({
        page: 1,
        size: 0,
        enabled: false,
        search: "",
        status: null,
        sort: undefined,
      }),
    ).toEqual({ page: 1, size: 0, enabled: false });
  });

  it("returns an empty object when no params are supplied", () => {
    expect(cleanParams(undefined)).toEqual({});
  });
});

describe("ApiError", () => {
  it("exposes status helpers and defaults", () => {
    const unauthorized = new ApiError("Denied", { status: 401, code: "unauthenticated" });
    expect(unauthorized.isUnauthorized).toBe(true);
    expect(unauthorized.isForbidden).toBe(false);
    expect(unauthorized.code).toBe("unauthenticated");

    const fallback = new ApiError("Boom");
    expect(fallback.status).toBe(0);
    expect(fallback.code).toBe("network_error");
    expect(fallback.requestId).toBeNull();
  });
});

describe("toApiError", () => {
  it("unwraps the API error envelope", () => {
    const response = {
      data: {
        error: {
          code: "conflict",
          message: "Name already exists",
          details: { field: "name" },
          request_id: "req-1",
        },
      },
      status: 409,
      statusText: "Conflict",
      headers: {},
      config: {},
    } as AxiosResponse;
    const error = new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, response);

    const converted = toApiError(error);
    expect(converted).toBeInstanceOf(ApiError);
    expect(converted.status).toBe(409);
    expect(converted.code).toBe("conflict");
    expect(converted.message).toBe("Name already exists");
    expect(converted.requestId).toBe("req-1");
  });

  it("maps timeouts to a friendly network message", () => {
    const error = new AxiosError("timeout", "ECONNABORTED");
    const converted = toApiError(error);
    expect(converted.status).toBe(0);
    expect(converted.message).toContain("timed out");
  });

  it("passes through existing ApiError instances", () => {
    const original = new ApiError("Already normalised", { status: 500 });
    expect(toApiError(original)).toBe(original);
  });
});
