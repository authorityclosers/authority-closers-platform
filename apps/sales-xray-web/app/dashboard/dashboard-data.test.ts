import { afterEach, describe, expect, it, vi } from "vitest";

import { AcquisitionError } from "../acquisition-client";
import {
  analysedTrend,
  isEmptyAccount,
  minutesLeft,
  otherSavedCalls,
  parseCallActivity,
  parseCallSummary,
  readCallActivity,
  readCallSummary,
  readRecentCalls,
} from "./dashboard-data";

afterEach(() => vi.unstubAllGlobals());

const summary = { total: 7, processing: 1, completed: 4, needs_attention: 1 };

function activity(counts: number[] = Array(30).fill(0), previous = 0) {
  const start = Date.UTC(2026, 7, 31);
  return {
    timezone: "Asia/Kolkata",
    days: counts.map((analysed, index) => ({
      date: new Date(start + index * 86_400_000).toISOString().slice(0, 10),
      analysed,
      analysed_seconds: analysed * 600,
    })),
    analysed_last_30_days: counts.reduce((sum, value) => sum + value, 0),
    analysed_previous_30_days: previous,
  };
}

function respond(status: number, body: unknown = {}) {
  const fetch = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("dashboard summary", () => {
  it("parses the Calls list status counts", () => {
    expect(parseCallSummary(summary)).toEqual({
      total: 7,
      processing: 1,
      completed: 4,
      needsAttention: 1,
    });
    expect(otherSavedCalls(parseCallSummary(summary))).toBe(1);
  });

  it.each([
    { ...summary, score: 80 },
    { ...summary, total: -1 },
    { ...summary, completed: 1.5 },
    { ...summary, total: 2 },
    { total: 1, processing: 0, completed: 0 },
  ])("rejects an unexpected summary %#", (value) => {
    expect(() => parseCallSummary(value)).toThrow();
  });

  it("counts the whole Calls list while the summary route is not deployed", async () => {
    const row = (index: number, state: string, has_report = false) => ({
      submission_id: `00000000-0000-4000-8000-00000000000${index}`,
      created_at: "2026-09-29T08:00:00Z",
      duration_seconds: 600,
      state,
      has_report,
    });
    const cursor = "00000000-0000-4000-8000-000000000002";
    const bodies = [
      [422, { detail: "not a call id" }],
      [
        200,
        {
          submissions: [row(1, "completed", true), row(2, "processing")],
          next_cursor: cursor,
        },
      ],
      [
        200,
        {
          submissions: [row(3, "failed"), row(4, "awaiting_upload")],
          next_cursor: null,
        },
      ],
    ] as const;
    const fetch = vi.fn();
    for (const [status, body] of bodies)
      fetch.mockResolvedValueOnce(
        new Response(JSON.stringify(body), { status }),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(readCallSummary()).resolves.toEqual({
      total: 4,
      processing: 1,
      completed: 1,
      needsAttention: 1,
    });
    expect(fetch.mock.calls.map((call) => call[0])).toEqual([
      "/v1/conversation/acquisition/submissions/summary",
      "/v1/conversation/acquisition/submissions",
      `/v1/conversation/acquisition/submissions?before=${cursor}`,
    ]);
  });

  it("reads null rather than an undercount for a very long Calls list", async () => {
    let page = 0;
    const fetch = vi.fn().mockImplementation(async () => {
      if (page === 0) {
        page += 1;
        return new Response("{}", { status: 404 });
      }
      const id = (n: number) =>
        `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
      const body = {
        submissions: [
          {
            submission_id: id(page),
            created_at: "2026-09-29T08:00:00Z",
            duration_seconds: 600,
            state: "active",
            has_report: false,
          },
        ],
        next_cursor: id(page),
      };
      page += 1;
      return new Response(JSON.stringify(body), { status: 200 });
    });
    vi.stubGlobal("fetch", fetch);
    await expect(readCallSummary()).resolves.toBeNull();
    expect(fetch).toHaveBeenCalledTimes(51);
  });

  it("reads the live summary from the acquisition namespace", async () => {
    const fetch = respond(200, summary);
    await expect(readCallSummary()).resolves.toMatchObject({ total: 7 });
    expect(fetch.mock.calls[0][0]).toBe(
      "/v1/conversation/acquisition/submissions/summary",
    );
  });

  it("surfaces other failures", async () => {
    respond(500);
    await expect(readCallSummary()).rejects.toBeInstanceOf(AcquisitionError);
  });
});

describe("dashboard activity", () => {
  it("parses 30 days and compares with the previous 30", () => {
    const counts = Array(30).fill(0);
    counts[29] = 2;
    counts[10] = 1;
    const parsed = parseCallActivity(activity(counts, 1));
    expect(parsed.days).toHaveLength(30);
    expect(parsed.days[29]).toEqual({
      date: "2026-09-29",
      analysed: 2,
      analysedSeconds: 1200,
    });
    expect(analysedTrend(parsed)).toEqual({
      direction: "up",
      text: "+2 vs previous 30 days",
    });
  });

  it("has no trend without history", () => {
    expect(analysedTrend(parseCallActivity(activity()))).toBeNull();
  });

  it.each([
    { ...activity(), days: activity().days.slice(1) },
    { ...activity(), analysed_last_30_days: 3 },
    { ...activity(), timezone: "UTC" },
    { ...activity(), days: [...activity().days].reverse() },
    { ...activity(), average_score: 80 },
  ])("rejects unexpected activity %#", (value) => {
    expect(() => parseCallActivity(value)).toThrow();
  });

  it("reads null while the activity route is not deployed", async () => {
    respond(404, { detail: "Not Found" });
    await expect(readCallActivity()).resolves.toBeNull();
  });
});

describe("minutes and recents", () => {
  it("matches the shell meter arithmetic", () => {
    expect(
      minutesLeft({
        allowance_seconds: 6000,
        committed_seconds: 1830,
        available_seconds: 4170,
      }),
    ).toEqual({ value: "69 min", subtext: "left of 100 min" });
    expect(
      minutesLeft({
        allowance_seconds: 6000,
        committed_seconds: 0,
        available_seconds: 6000,
        unlimited: true,
      }).value,
    ).toBe("Unlimited");
  });

  it("keeps the newest five calls from the Calls list", async () => {
    const submissions = Array.from({ length: 7 }, (_, index) => ({
      submission_id: `00000000-0000-4000-8000-00000000000${index}`,
      created_at: "2026-09-29T08:00:00Z",
      duration_seconds: 600,
      state: "active",
      has_report: false,
    }));
    respond(200, { submissions, next_cursor: null });
    const recent = await readRecentCalls();
    expect(recent.map((call) => call.id)).toEqual(
      submissions.slice(0, 5).map((row) => row.submission_id),
    );
  });

  it("treats a new account as empty and never invents numbers", () => {
    const empty = parseCallSummary({
      total: 0,
      processing: 0,
      completed: 0,
      needs_attention: 0,
    });
    expect(isEmptyAccount(empty, parseCallActivity(activity()), [])).toBe(true);
    expect(isEmptyAccount(null, null, null)).toBe(true);
    expect(isEmptyAccount(parseCallSummary(summary), null, [])).toBe(false);
  });
});
