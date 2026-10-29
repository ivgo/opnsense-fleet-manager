import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { resetStoreForTests } from "@/api/tokenStore";

afterEach(() => {
  cleanup();
  resetStoreForTests();
  window.localStorage.clear();
});
