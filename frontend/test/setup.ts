import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Ensure DOM is cleaned between tests so `screen.getByText` does not match
// elements rendered by previous tests. Some vitest 3.x + RTL combinations
// do not pick up the auto-cleanup side-effect reliably, so register it
// explicitly here.
afterEach(() => {
  cleanup();
});
