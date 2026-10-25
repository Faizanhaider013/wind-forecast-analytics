import { describe, expect, it } from "vitest";

import { count, mw, mwh, percent, signedMw, ukTime } from "../utils/format";

describe("format helpers", () => {
  it("formats MW and MWh with units", () => {
    expect(mw(12345)).toBe("12,345 MW");
    expect(mwh(1000)).toBe("1,000 MWh");
  });

  it("renders an em dash for null/undefined/NaN values (never a fake number)", () => {
    expect(mw(null)).toBe("—");
    expect(mw(undefined)).toBe("—");
    expect(mwh(null)).toBe("—");
    expect(percent(null)).toBe("—");
    expect(count(null)).toBe("—");
    expect(signedMw(null)).toBe("—");
  });

  it("adds an explicit sign for bias/error values", () => {
    expect(signedMw(250)).toBe("+250 MW");
    expect(signedMw(-250)).toBe("-250 MW");
    expect(signedMw(0)).toBe("0 MW");
  });

  it("formats percentages already in percent units", () => {
    expect(percent(18.331)).toBe("18.3%");
  });

  it("renders UK local time for a January (GMT) UTC timestamp", () => {
    // January is GMT, so UTC midnight == 00:00 UK.
    expect(ukTime("2026-01-15T00:00:00Z")).toBe("00:00");
    expect(ukTime("2026-01-15T13:30:00Z")).toBe("13:30");
  });

  it("renders UK local time shifted for a summer (BST) timestamp", () => {
    // July is BST (UTC+1), so 12:00Z == 13:00 UK.
    expect(ukTime("2026-07-15T12:00:00Z")).toBe("13:00");
  });
});
