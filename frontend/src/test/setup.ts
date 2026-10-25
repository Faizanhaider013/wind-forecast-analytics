import "@testing-library/jest-dom";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { cloneElement, isValidElement } from "react";

afterEach(() => {
  cleanup();
});

// Recharts' ResponsiveContainer measures the DOM, which jsdom cannot do, so it
// would render charts at 0x0 and emit warnings. Replace it with a passthrough
// that injects a fixed size, letting charts render deterministically in tests.
vi.mock("recharts", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: unknown }) =>
      isValidElement(children)
        ? cloneElement(children as never, { width: 800, height: 320 })
        : (children as never),
  };
});
