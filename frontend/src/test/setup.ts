import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { resetStoreForTests } from "@/api/tokenStore";

// Polyfill ResizeObserver for recharts
if (typeof global.ResizeObserver === "undefined") {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

afterEach(() => {
  cleanup();
  resetStoreForTests();
  window.localStorage.clear();
});
