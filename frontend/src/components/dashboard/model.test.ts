import { describe, expect, it } from "vitest";
import type { DashboardTodayResponse } from "../../api/types";
import {
  buildRange,
  buildRecords,
  clampToToday,
  countKpis,
  formatClock,
  matchesEmpCode,
  matchesKiosks,
  matchesKpi,
  nextSort,
  sortRecords,
} from "./model";

const response: DashboardTodayResponse = {
  known: [
    {
      face_id: "EMP-1", emp_code: "E-100", name: "Asha", designation: "Nurse", department: "ER", shift_in: "09:00", shift_out: "18:00",
      // No OUT yet -- backend now returns elapsed-so-far hours, not 0.
      in_time: "09:40", out_time: null, total_hours: 2.75, status: "Late", similarity: 0.9, thumb_url: null,
      best_shot_url: "/api/v1/media/crop/1", date: "2026-09-23", kiosk_ids: ["gate-1"], is_active: true, on_time: false,
      subject_id: "emp-1", in_event_id: "ev-1", out_event_id: null, home_kiosk_id: "gate-1",
    },
    {
      face_id: "EMP-2", emp_code: "E-200", name: "Bala", designation: null, department: "OPD", shift_in: null, shift_out: null,
      in_time: "08:50", out_time: "17:20", total_hours: 8.5, status: "Present", similarity: 0.95, thumb_url: null,
      best_shot_url: null, date: "2026-09-23", kiosk_ids: ["opd-cam"], is_active: true, on_time: true,
      subject_id: "emp-2", in_event_id: "ev-2", out_event_id: "ev-3", home_kiosk_id: null,
    },
  ],
  unknown: [
    {
      face_id: "UNK-1", label: null, first_seen: "", last_seen: "", sighting_count: 1, in_time: "11:00",
      out_time: null, total_hours: 0, status: "OPEN", best_crop_url: null, date: "2026-09-23", kiosk_ids: ["opd-cam"],
      subject_id: "unk-1", in_event_id: "ev-4", out_event_id: null,
    },
  ],
  absent: [
    {
      face_id: "EMP-3", emp_code: "E-300", name: "Chitra", designation: null, department: null, shift_in: null, shift_out: null,
      thumb_url: null, date: "2026-09-23", is_active: true, subject_id: "emp-3", home_kiosk_id: null,
    },
  ],
  exceptions: [
    { kind: "late_arrival", face_id: "EMP-1", label: "Asha", detail: "In at 09:40", date: "2026-09-23", kiosk_ids: ["gate-1"] },
    { kind: "no_out_recorded", face_id: "EMP-1", label: "Asha", detail: "No OUT", date: "2026-09-23", kiosk_ids: ["gate-1"] },
    { kind: "liveness_failure", face_id: "gate-1", label: null, detail: "t", date: "2026-09-23", kiosk_ids: ["gate-1"] },
  ],
  counts: { present: 2, unknown: 1, absent: 1, exceptions: 3 },
  date_from: "2026-09-23",
  date_to: "2026-09-23",
  kiosks: ["gate-1", "opd-cam"],
};

describe("buildRecords", () => {
  const records = buildRecords(response);

  it("attaches exceptions to the matching person/day and keeps orphans as their own rows", () => {
    const asha = records.find((r) => r.face_id === "EMP-1");
    expect(asha?.exceptions.map((x) => x.kind)).toEqual(["late_arrival", "no_out_recorded"]);
    expect(records.filter((r) => r.category === "EXCEPTION")).toHaveLength(1);
    expect(records).toHaveLength(5);
  });

  it("shows elapsed-so-far hours when there is no OUT yet (backend-computed)", () => {
    expect(records.find((r) => r.face_id === "EMP-1")?.total_hours).toBe(2.75);
    expect(records.find((r) => r.face_id === "EMP-2")?.total_hours).toBe(8.5);
  });

  it("carries emp_code through for known/absent rows, null for unknown/exception rows", () => {
    expect(records.find((r) => r.face_id === "EMP-1")?.emp_code).toBe("E-100");
    expect(records.find((r) => r.face_id === "EMP-3")?.emp_code).toBe("E-300");
    expect(records.find((r) => r.face_id === "UNK-1")?.emp_code).toBeNull();
  });

  it("keeps the ids the inline edit actions need", () => {
    const asha = records.find((r) => r.face_id === "EMP-1");
    expect(asha).toMatchObject({ subject_id: "emp-1", in_event_id: "ev-1", out_event_id: null, home_kiosk_id: "gate-1" });
    expect(records.find((r) => r.face_id === "UNK-1")?.subject_id).toBe("unk-1");
    expect(records.find((r) => r.category === "EXCEPTION")?.subject_id).toBe("");
  });

  it("filters by emp_code, case-insensitively, blank = no filter", () => {
    expect(records.filter((r) => matchesEmpCode(r, "e-100")).map((r) => r.face_id)).toEqual(["EMP-1"]);
    expect(records.filter((r) => matchesEmpCode(r, ""))).toHaveLength(5);
    expect(records.filter((r) => matchesEmpCode(r, "nope"))).toHaveLength(0);
  });

  it("counts KPIs with Exception overlapping the other buckets", () => {
    expect(countKpis(records)).toEqual({ KNOWN_PRESENT: 2, UNKNOWN_PRESENT: 1, ABSENT: 1, EXCEPTION: 2 });
    expect(records.filter((r) => matchesKpi(r, "EXCEPTION")).map((r) => r.face_id)).toEqual(["EMP-1", "gate-1"]);
  });

  it("filters by entry point but keeps absent rows while any entry point is selected", () => {
    expect(records.filter((r) => matchesKiosks(r, ["opd-cam"])).map((r) => r.face_id)).toEqual(["EMP-2", "UNK-1", "EMP-3"]);
    expect(records.filter((r) => matchesKiosks(r, []))).toHaveLength(0);
    expect(records.filter((r) => matchesKiosks(r, null))).toHaveLength(5);
  });

  it("sorts with nulls last in both directions and cycles asc -> desc -> default", () => {
    const asc = sortRecords(records, { key: "intime", direction: "asc" }).map((r) => r.intime);
    const desc = sortRecords(records, { key: "intime", direction: "desc" }).map((r) => r.intime);
    expect(asc.slice(0, 3)).toEqual(["08:50", "09:40", "11:00"]);
    expect(desc.slice(0, 3)).toEqual(["11:00", "09:40", "08:50"]);
    expect(asc.slice(3)).toEqual([null, null]);
    let s = nextSort({ key: null, direction: null }, "name");
    expect(s).toEqual({ key: "name", direction: "asc" });
    s = nextSort(s, "name");
    expect(s.direction).toBe("desc");
    expect(nextSort(s, "name")).toEqual({ key: null, direction: null });
  });
});

describe("date helpers", () => {
  it("builds month / year / custom ranges", () => {
    expect(buildRange("month", "2024-02-10")).toMatchObject({ from: "2024-02-01", to: "2024-02-29" });
    expect(buildRange("year", "2026-09-23")).toMatchObject({ from: "2026-01-01", to: "2026-12-31" });
    expect(buildRange("custom", "2026-09-10", "2026-09-01")).toMatchObject({ from: "2026-09-01", to: "2026-09-10" });
  });

  it("never requests the future", () => {
    expect(clampToToday(buildRange("year", "2026-01-01"), "2026-09-23")).toEqual({
      date_from: "2026-01-01",
      date_to: "2026-09-23",
    });
  });

  it("formats 24h times as 12h", () => {
    expect(formatClock("00:05")).toBe("12:05 AM");
    expect(formatClock("13:30")).toBe("01:30 PM");
    expect(formatClock(null)).toBe("--");
  });
});
