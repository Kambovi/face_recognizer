import { describe, expect, it } from "vitest";
import { analyticsExportCsvUrl, mediaUrl } from "./client";

describe("analyticsExportCsvUrl", () => {
  it("builds a URL with only the required period param by default", () => {
    const url = analyticsExportCsvUrl({ period: "daily" });
    expect(url).toContain("/api/v1/analytics/export.csv?");
    expect(url).toContain("period=daily");
    expect(url).not.toContain("date_from");
    expect(url).not.toContain("include_unknowns");
  });

  it("includes optional params only when provided", () => {
    const url = analyticsExportCsvUrl({
      period: "monthly",
      date_from: "2024-01-01",
      date_to: "2024-01-31",
      subject_id: "abc-123",
      include_unknowns: true,
    });
    expect(url).toContain("period=monthly");
    expect(url).toContain("date_from=2024-01-01");
    expect(url).toContain("date_to=2024-01-31");
    expect(url).toContain("subject_id=abc-123");
    expect(url).toContain("include_unknowns=true");
  });

  it("omits include_unknowns entirely when false", () => {
    const url = analyticsExportCsvUrl({ period: "weekly", include_unknowns: false });
    expect(url).not.toContain("include_unknowns");
  });
});

describe("mediaUrl", () => {
  it("returns null for a null path", () => {
    expect(mediaUrl(null)).toBeNull();
  });

  it("prefixes a relative API path with the API base URL", () => {
    const url = mediaUrl("/api/v1/media/crop/evt-1");
    expect(url).toBe(`${import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"}/api/v1/media/crop/evt-1`);
  });

  it("leaves an already-absolute URL untouched", () => {
    expect(mediaUrl("https://cdn.example.org/img.jpg")).toBe("https://cdn.example.org/img.jpg");
  });
});
