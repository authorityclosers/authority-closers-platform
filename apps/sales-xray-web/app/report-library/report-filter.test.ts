import { describe, expect, it } from "vitest";

import {
  LEAD_TYPE_OPTIONS,
  NO_FILTERS,
  activeFilterCount,
  completeRange,
  countLine,
  dayWords,
  matchesReport,
  newestFirst,
  pickDay,
  rangeWords,
  showButtonLabel,
  summaryLine,
  visibleReports,
  type ReportRow,
} from "./report-filter";

/** Fictional reports (no real people), stored times in UTC as the API sends. */
const row = (
  id: string,
  createdAt: string,
  extra: Partial<ReportRow> = {},
): ReportRow => ({
  id,
  createdAt,
  createdMs: Date.parse(createdAt),
  day: createdAt.slice(0, 10),
  prospect: "Sample Prospect",
  topic: "Sales call",
  summary: null,
  durationSeconds: 600,
  status: "Report ready",
  ready: true,
  active: false,
  source: "inbound_auto",
  saved: false,
  owner: null,
  ...extra,
});

const ROWS: ReportRow[] = [
  row("r-05", "2026-11-05T09:00:00Z", {
    source: "cold_auto",
    prospect: "Aarav Sample",
  }),
  row("r-13a", "2026-11-13T13:10:00Z", {
    prospect: "Rohit Example",
    topic: "Discovery call",
    summary: "Good connection. The business impact needed more exploration.",
  }),
  row("r-01", "2026-11-01T06:00:00Z", {
    source: "manual",
    prospect: null,
    topic: "Uploaded recording",
  }),
  row("r-12", "2026-11-12T12:00:00Z", {
    source: "manual",
    saved: true,
    topic: "Pricing discussion",
  }),
  row("r-10", "2026-11-10T08:00:00Z", { source: "cold_auto", saved: true }),
  row("r-13b", "2026-11-13T08:45:00Z", { prospect: "Priya Fictional" }),
];

const ids = (rows: readonly ReportRow[]) => rows.map((item) => item.id);

describe("default display (section 12)", () => {
  it("shows every report, newest first, with no filter chosen", () => {
    expect(ids(visibleReports(ROWS, NO_FILTERS))).toEqual([
      "r-13a",
      "r-13b",
      "r-12",
      "r-10",
      "r-05",
      "r-01",
    ]);
    expect(activeFilterCount(NO_FILTERS)).toBe(0);
  });

  it("orders by the stored time, never by formatted text", () => {
    const sameDay = [
      row("late", "2026-11-13T23:59:00Z"),
      row("early", "2026-11-13T00:01:00Z"),
    ];
    expect(ids(newestFirst(sameDay))).toEqual(["late", "early"]);
    expect(ids(newestFirst([...sameDay].reverse()))).toEqual(["late", "early"]);
  });
});

describe("lead type (section 9)", () => {
  it("offers the four categories in the spec's order", () => {
    expect(LEAD_TYPE_OPTIONS.map((option) => option.label)).toEqual([
      "Inbound leads (Auto-uploaded)",
      "Cold leads (Auto-uploaded)",
      "Manually Uploaded",
      "Saved Reports",
    ]);
  });

  it("shows only the chosen category", () => {
    const only = (leadType: ReportRow["source"] | "saved") =>
      ids(visibleReports(ROWS, { ...NO_FILTERS, leadType }));
    expect(only("inbound_auto")).toEqual(["r-13a", "r-13b"]);
    expect(only("cold_auto")).toEqual(["r-10", "r-05"]);
    expect(only("manual")).toEqual(["r-12", "r-01"]);
    // Saved Reports is the person's own Save, whatever the report's source.
    expect(only("saved")).toEqual(["r-12", "r-10"]);
    expect(activeFilterCount({ ...NO_FILTERS, leadType: "saved" })).toBe(1);
  });
});

describe("date range (section 10)", () => {
  it("includes both boundary days", () => {
    const filters = { ...NO_FILTERS, from: "2026-11-01", to: "2026-11-12" };
    expect(ids(visibleReports(ROWS, filters))).toEqual([
      "r-12",
      "r-10",
      "r-05",
      "r-01",
    ]);
    expect(activeFilterCount(filters)).toBe(1);
  });

  it("never applies an incomplete or backwards range", () => {
    for (const filters of [
      { ...NO_FILTERS, from: "2026-11-12", to: null },
      { ...NO_FILTERS, from: null, to: "2026-11-12" },
      { ...NO_FILTERS, from: "2026-11-12", to: "2026-11-01" },
    ]) {
      expect(visibleReports(ROWS, filters)).toHaveLength(ROWS.length);
      expect(activeFilterCount(filters)).toBe(0);
    }
    expect(completeRange("2026-11-01", "2026-11-13")).toEqual({
      from: "2026-11-01",
      to: "2026-11-13",
    });
    expect(completeRange("2026-11-01", "13 Nov")).toBeNull();
  });

  it("works together with a lead type", () => {
    const filters = {
      ...NO_FILTERS,
      leadType: "cold_auto" as const,
      from: "2026-11-06",
      to: "2026-11-13",
    };
    expect(ids(visibleReports(ROWS, filters))).toEqual(["r-10"]);
    expect(activeFilterCount(filters)).toBe(2);
  });

  it("picks From, then To, and starts again before From (section 10)", () => {
    let state = { from: null, to: null, picking: "from" as "from" | "to" } as {
      from: string | null;
      to: string | null;
      picking: "from" | "to";
    };
    state = pickDay(state, "2026-11-05");
    expect(state).toEqual({ from: "2026-11-05", to: null, picking: "to" });
    state = pickDay(state, "2026-11-12");
    expect(state).toEqual({
      from: "2026-11-05",
      to: "2026-11-12",
      picking: "from",
    });
    // Tapping From again moves the start and keeps a later end.
    state = pickDay(state, "2026-11-08");
    expect(state).toEqual({
      from: "2026-11-08",
      to: "2026-11-12",
      picking: "to",
    });
    // A day before the start, while choosing the end, becomes the new start.
    state = pickDay(state, "2026-11-02");
    expect(state).toEqual({ from: "2026-11-02", to: null, picking: "to" });
    // Moving From past the end drops the end.
    state = pickDay(
      { from: "2026-11-02", to: "2026-11-04", picking: "from" },
      "2026-11-09",
    );
    expect(state).toEqual({ from: "2026-11-09", to: null, picking: "to" });
  });

  it("names the range as the chips and fields do (section 14)", () => {
    expect(rangeWords("2026-11-01", "2026-11-13")).toBe("1 Nov – 13 Nov 2026");
    expect(rangeWords("2025-12-28", "2026-01-03")).toBe(
      "28 Dec 2025 – 3 Jan 2026",
    );
    expect(dayWords("2026-11-01")).toBe("1 Nov 2026");
  });
});

describe("search (section 7)", () => {
  const search = (query: string, extra = {}) =>
    ids(visibleReports(ROWS, { ...NO_FILTERS, query, ...extra }));

  it("finds by prospect, topic, summary and lead type, in any case", () => {
    expect(search("rohit")).toEqual(["r-13a"]);
    expect(search("PRICING")).toEqual(["r-12"]);
    expect(search("business impact")).toEqual(["r-13a"]);
    expect(search("cold")).toEqual(["r-10", "r-05"]);
    expect(search("manual upload")).toEqual(["r-12", "r-01"]);
    expect(search("saved report")).toEqual(["r-12", "r-10"]);
    expect(search("   ")).toHaveLength(ROWS.length);
  });

  it("narrows within the filters, and clearing it keeps them", () => {
    const filters = { leadType: "manual" as const };
    expect(search("pricing", filters)).toEqual(["r-12"]);
    expect(search("", filters)).toEqual(["r-12", "r-01"]);
  });

  it("never changes the reports it reads", () => {
    const before = JSON.stringify(ROWS);
    visibleReports(ROWS, {
      query: "x",
      leadType: "saved",
      from: "2026-11-01",
      to: "2026-11-02",
    });
    expect(JSON.stringify(ROWS)).toBe(before);
    expect(matchesReport(ROWS[0], NO_FILTERS)).toBe(true);
  });
});

describe("counts and labels (sections 11 and 15)", () => {
  it("counts what is shown out of every report", () => {
    expect(countLine(10, 10, NO_FILTERS)).toBe("10 of 10 reports");
    expect(countLine(3, 10, { ...NO_FILTERS, leadType: "manual" })).toBe(
      "3 of 10 reports · Filtered",
    );
    expect(countLine(1, 1, NO_FILTERS)).toBe("1 of 1 report");
  });

  it("says how many reports the sheet's button will show", () => {
    expect(showButtonLabel(10, 10)).toBe("Show all reports");
    expect(showButtonLabel(5, 10)).toBe("Show 5 reports");
    expect(showButtonLabel(1, 10)).toBe("Show 1 report");
    expect(showButtonLabel(0, 10)).toBe("Show 0 reports");
  });

  it("keeps a card's summary to whole sentences, about two lines", () => {
    expect(
      summaryLine(
        "Good connection. The business impact needed more exploration.",
      ),
    ).toBe("Good connection. The business impact needed more exploration.");
    const long =
      "The seller opened warmly and asked about the team's current process before pricing came up. Later the buyer asked for a demo.";
    expect(summaryLine(long)).toBe(
      "The seller opened warmly and asked about the team's current process before pricing came up.",
    );
    expect(summaryLine("One line only")).toBe("One line only");
  });
});
