import { describe, expect, it } from "vitest";

import { safeRedirect } from "./redirect";

describe("safeRedirect", () => {
  it("keeps same-origin application paths", () => {
    expect(safeRedirect("/devices")).toBe("/devices");
    expect(safeRedirect("/devices?new=1")).toBe("/devices?new=1");
    expect(safeRedirect("/audit?page=2&size=50")).toBe("/audit?page=2&size=50");
  });

  it("falls back for absolute and protocol-relative URLs", () => {
    expect(safeRedirect("https://evil.example/login")).toBe("/dashboard");
    expect(safeRedirect("//evil.example")).toBe("/dashboard");
    expect(safeRedirect("/\\evil.example")).toBe("/dashboard");
    expect(safeRedirect("\\\\evil.example")).toBe("/dashboard");
    expect(safeRedirect("javascript:alert(1)")).toBe("/dashboard");
  });

  it("falls back for empty and control-character values", () => {
    expect(safeRedirect(undefined)).toBe("/dashboard");
    expect(safeRedirect(null)).toBe("/dashboard");
    expect(safeRedirect("")).toBe("/dashboard");
    expect(safeRedirect("/dash\u0000board")).toBe("/dashboard");
  });

  it("uses a caller-provided fallback", () => {
    expect(safeRedirect("https://evil.example", "/alerts")).toBe("/alerts");
  });
});
