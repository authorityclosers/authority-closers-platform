import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ acquisition: vi.fn() }));
vi.mock("../acquisition-client", async (original) => ({
  ...(await original<typeof import("../acquisition-client")>()),
  acquisition: api.acquisition,
}));

import {
  REPORTS_MAX_PAGES,
  markSaved,
  parseReportsPage,
  readReports,
  reportsListPath,
  shelveReports,
  shelvedReports,
  sourceOf,
  forgetReports,
} from "./report-rows";

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

const row = (n: number, extra: Record<string, unknown> = {}) => ({
  submission_id: id(n),
  created_at: `2026-11-${String(10 + n).padStart(2, "0")}T18:30:00Z`,
  duration_seconds: 45,
  state: "processing",
  has_report: false,
  display_name: null,
  display_name_revision: 0,
  summary: null,
  upload: "auto",
  lead_side: null,
  saved: false,
  ...extra,
});

beforeEach(() => {
  forgetReports();
  api.acquisition.mockReset();
});

describe("the list contract (section 23)", () => {
  it("asks for the whole library, newest first, with how each call arrived", () => {
    const path = reportsListPath(null);
    for (const part of [
      "order=newest",
      "limit=100",
      "include_summary=true",
      "include_leads=true",
      "include_kind=true",
      "include_saved=true",
    ])
      expect(path).toContain(part);
    expect(reportsListPath(id(9))).toContain(`before=${id(9)}`);
  });

  it("checks Reports' three fields and passes the rest to the list's own contract", () => {
    const page = parseReportsPage({
      submissions: [
        row(1, { upload: "manual", saved: true }),
        row(2, { lead_side: "cold" }),
      ],
      next_cursor: null,
    });
    expect(page.submissions.map((item) => item.id)).toEqual([id(1), id(2)]);
    expect(page.facts.get(id(1))).toEqual({
      upload: "manual",
      leadSide: null,
      saved: true,
    });
    expect(page.facts.get(id(2))).toEqual({
      upload: "auto",
      leadSide: "cold",
      saved: false,
    });
    for (const broken of [
      { upload: "phone" },
      { lead_side: "warm" },
      { saved: "yes" },
      { saved: undefined },
      { unexpected: 1 },
    ])
      expect(() =>
        parseReportsPage({ submissions: [row(3, broken)], next_cursor: null }),
      ).toThrow();
  });

  it("takes a whole page of 100 calls, the list's contract on every row", () => {
    const many = Array.from({ length: 45 }, (_, index) =>
      row(index + 1, { created_at: "2026-11-10T08:00:00Z" }),
    );
    const page = parseReportsPage({ submissions: many, next_cursor: id(45) });
    expect(page.submissions).toHaveLength(45);
    expect(page.facts.size).toBe(45);
    expect(page.nextCursor).toBe(id(45));
    // A repeated call, a bad cursor or a page over 100 is refused.
    expect(() =>
      parseReportsPage({
        submissions: [...many, row(3, { created_at: "2026-11-10T08:00:00Z" })],
        next_cursor: null,
      }),
    ).toThrow();
    expect(() =>
      parseReportsPage({ submissions: many, next_cursor: "next" }),
    ).toThrow();
    expect(() =>
      parseReportsPage({
        submissions: Array.from({ length: 101 }, (_, index) =>
          row(index + 1, { created_at: "2026-11-10T08:00:00Z" }),
        ),
        next_cursor: null,
      }),
    ).toThrow();
  });

  it("files every report under exactly one source", () => {
    expect(sourceOf({ upload: "manual", leadSide: "cold", saved: true })).toBe(
      "manual",
    );
    expect(sourceOf({ upload: "auto", leadSide: "cold", saved: false })).toBe(
      "cold_auto",
    );
    expect(
      sourceOf({ upload: "auto", leadSide: "inbound", saved: false }),
    ).toBe("inbound_auto");
    // An auto call no lead names reads Inbound, as an empty side does.
    expect(sourceOf({ upload: "auto", leadSide: null, saved: false })).toBe(
      "inbound_auto",
    );
  });
});

describe("reading the library", () => {
  it("reads page after page until the list ends, each report once", async () => {
    api.acquisition
      .mockResolvedValueOnce({
        submissions: [row(3), row(2)],
        next_cursor: id(2),
      })
      .mockResolvedValueOnce({
        submissions: [row(2), row(1)],
        next_cursor: null,
      });
    const pages: number[] = [];
    const rows = await readReports(
      { timeZone: "Asia/Kolkata" },
      null,
      undefined,
      (read) => pages.push(read.length),
    );
    expect(rows.map((item) => item.id)).toEqual([id(3), id(2), id(1)]);
    expect(pages).toEqual([2, 3]);
    expect(api.acquisition.mock.calls[1][0]).toContain(`before=${id(2)}`);
    // Dates come from the stored instant in the reader's zone: 18:30 UTC is
    // the next day in India.
    expect(rows[0].day).toBe("2026-11-14");
    expect(rows[0].status).toBe("Analysis in progress");
    expect(rows[0].active).toBe(true);
    expect(rows[0].topic).toBe("Sales call");
  });

  it("stops after the page cap", async () => {
    let calls = 0;
    api.acquisition.mockImplementation(async () => ({
      submissions: [{ ...row(1), submission_id: id(1000 + (calls += 1)) }],
      next_cursor: id(1),
    }));
    await readReports({ timeZone: "UTC" }, null);
    expect(api.acquisition).toHaveBeenCalledTimes(REPORTS_MAX_PAGES);
  });

  it("names an owner only when it is someone else's call", async () => {
    const owner = { owner_person_id: id(50), owner_name: "sneha sample" };
    api.acquisition.mockResolvedValueOnce({
      submissions: [
        row(1, owner),
        row(2, { ...owner, owner_person_id: id(51) }),
      ],
      next_cursor: null,
    });
    const rows = await readReports({ timeZone: "UTC" }, id(50));
    expect(rows.map((item) => item.owner)).toEqual([null, "Sneha Sample"]);
  });
});

describe("the shelf", () => {
  it("marks a report saved on every shelf that holds it", async () => {
    api.acquisition.mockResolvedValueOnce({
      submissions: [row(1)],
      next_cursor: null,
    });
    const rows = await readReports({ timeZone: "UTC" }, null);
    shelveReports("me", { rows, complete: true });
    markSaved(id(1), true);
    expect(shelvedReports("me")?.rows[0].saved).toBe(true);
    markSaved(id(1), false);
    expect(shelvedReports("me")?.rows[0].saved).toBe(false);
  });
});
