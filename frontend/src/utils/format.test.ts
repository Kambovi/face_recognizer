import { describe, expect, it } from "vitest";
import {
  formatDate,
  formatDateTime,
  formatHours,
  formatPercent,
  formatSimilarity,
  formatTime,
  localDateTimeToIso,
} from "./format";

describe("formatDateTime / formatTime / formatDate", () => {
  it("converts a UTC ISO string to Asia/Kolkata (+05:30)", () => {
    // 2024-01-15T00:00:00Z -> 05:30 IST the same calendar day.
    expect(formatDateTime("2024-01-15T00:00:00Z")).toBe("15 Jan 2024, 05:30:00");
    expect(formatTime("2024-01-15T00:00:00Z")).toBe("05:30:00");
    expect(formatDate("2024-01-15T00:00:00Z")).toBe("15 Jan 2024");
  });

  it("rolls over to the next IST calendar day near midnight UTC", () => {
    // 2024-01-15T19:00:00Z -> 2024-01-16T00:30:00 IST.
    expect(formatDate("2024-01-15T19:00:00Z")).toBe("16 Jan 2024");
  });

  it("returns a placeholder for null/undefined/empty input", () => {
    expect(formatDateTime(null)).toBe("--");
    expect(formatDateTime(undefined)).toBe("--");
    expect(formatTime("")).toBe("--");
  });

  it("falls back to the raw string on an unparseable value rather than throwing", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });
});

describe("formatHours", () => {
  it("formats whole and fractional hours as Xh YYm", () => {
    expect(formatHours(8)).toBe("8h 00m");
    expect(formatHours(7.5)).toBe("7h 30m");
    expect(formatHours(0.25)).toBe("0h 15m");
  });

  it("returns a placeholder for null/undefined/NaN", () => {
    expect(formatHours(null)).toBe("--");
    expect(formatHours(undefined)).toBe("--");
    expect(formatHours(Number.NaN)).toBe("--");
  });
});

describe("formatPercent / formatSimilarity", () => {
  it("formats a percentage to one decimal place", () => {
    expect(formatPercent(93.456)).toBe("93.5%");
    expect(formatPercent(null)).toBe("--");
  });

  it("formats a 0..1 similarity score as a percentage", () => {
    expect(formatSimilarity(0.874)).toBe("87.4%");
    expect(formatSimilarity(null)).toBe("--");
    expect(formatSimilarity(undefined)).toBe("--");
  });
});

describe("localDateTimeToIso", () => {
  it("treats the wall-clock time as India time", () => {
    expect(localDateTimeToIso("2026-09-25", "09:30")).toBe("2026-09-25T04:00:00.000Z");
  });
});
