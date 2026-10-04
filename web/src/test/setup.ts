import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { clearCsrf } from "../auth";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  clearCsrf();
  window.history.pushState({}, "", "/");
  document.cookie.split(";").forEach((part) => {
    const name = part.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  });
});
