import { afterEach, expect, it, vi } from "vitest";
import type { ActivityItem } from "../leads/leads-client";
import {
  activitySummary,
  dayNumber,
  readAnalytics,
  type AnalyticsHistory,
} from "./analytics-data";
const now = "2026-10-28T12:00:00Z";
const event = (id: string, kind: string, at: string, extras = {}) =>
  ({
    event_id: id,
    event: {
      kind,
      at,
      actor_person_id: "seller-a",
      actor_name: "Mira Fictional",
      ...extras,
    },
  }) as ActivityItem;
const history = (
  items: ActivityItem[],
  cursor: string | null = null,
): AnalyticsHistory => ({
  items,
  members: [],
  directoryMissing: false,
  cursor,
  timezone: "Asia/Kolkata",
  now,
});
afterEach(() => vi.unstubAllGlobals());
it("counts Lead Desk work by actor, with no report requirement, and no duplicated events", () => {
  const call = event("a", "call", now, { connected: true });
  const result = activitySummary(
    history([
      call,
      call,
      event("b", "note", now),
      event("c", "stage", now),
      event("d", "call", now, { connected: false, duration_seconds: 30 }),
      event("e", "result", now),
    ]),
  );
  expect(result.current).toEqual({
    calls: 2,
    conversations: 2,
    notes: 1,
    moves: 1,
  });
  expect(result.people[0].daily[29]).toMatchObject(result.current);
  expect(result.people[0].daily[29]?.work).toBe(5);
  expect(result.currentComplete).toBe(true);
});
it("uses organisation calendar days at both 30-day boundaries and excludes future events", () => {
  const result = activitySummary(
    history([
      event("a", "note", "2026-09-28T18:30:00Z"),
      event("b", "note", "2026-09-28T18:29:59Z"),
      event("c", "stage", "2026-08-29T18:30:00Z"),
      event("d", "stage", "2026-08-29T18:29:59Z"),
      event("e", "call", "2026-10-28T13:00:00Z"),
    ]),
  );
  expect(result.current.notes).toBe(1);
  expect(result.previous.notes).toBe(1);
  expect(result.previous.moves).toBe(1);
  expect(result.current.calls).toBe(0);
  expect(dayNumber("2026-09-28T18:30:00Z", "Asia/Kolkata")).toBe(result.start);
});
it("keeps unobserved days missing while real zero days stay zero", () => {
  const result = activitySummary(
    history([event("a", "note", now)], "2026-10-20T12:00:00Z"),
  );
  expect(result.currentComplete).toBe(false);
  expect(result.previousComplete).toBe(false);
  expect(result.people[0].daily[0]).toBeNull();
  expect(result.people[0].daily[28]?.calls).toBe(0);
});
it("reads both complete periods in one request with no directory or paging", async () => {
  const fetch = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          schema: "lead-desk/1",
          days: 30,
          timezone: "Asia/Kolkata",
          now,
          start: "2026-09-29",
          prior: "2026-08-30",
          today: "2026-10-28",
          current: { calls: 7, conversations: 3, notes: 2, moves: 1, work: 12 },
          previous: { calls: 4, conversations: 2, notes: 1, moves: 0, work: 6 },
          people: [
            {
              id: "seller-a",
              name: "mira fictional",
              current: {
                calls: 7,
                conversations: 3,
                notes: 2,
                moves: 1,
                work: 12,
              },
              previous: {
                calls: 4,
                conversations: 2,
                notes: 1,
                moves: 0,
                work: 6,
              },
              daily: [
                {
                  day: "2026-10-28",
                  calls: 7,
                  conversations: 3,
                  notes: 2,
                  moves: 1,
                  work: 12,
                },
              ],
            },
          ],
        }),
      ),
  );
  vi.stubGlobal("fetch", fetch);
  const signal = new AbortController().signal;
  const result = await readAnalytics({ team: true, signal });
  expect(fetch).toHaveBeenCalledExactlyOnceWith(
    "/v1/lead-desk/activity/summary?days=30&team=true",
    expect.objectContaining({
      signal,
      cache: "no-store",
      credentials: "same-origin",
    }),
  );
  expect(result.current.calls).toBe(7);
  expect(result.previous.calls).toBe(4);
  expect(result.currentComplete && result.previousComplete).toBe(true);
  expect(result.people[0].daily).toHaveLength(30);
  expect(result.people[0].daily[29]?.work).toBe(12);
  expect(result.people[0].daily[0]?.work).toBe(0);
  expect(result.people[0].name).toBe("Mira Fictional");
});
it("scopes personal reads and never turns a failed summary into an empty period", async () => {
  const fetch = vi.fn(async () => new Response("{}", { status: 403 }));
  vi.stubGlobal("fetch", fetch);
  await expect(
    readAnalytics({ team: false, personId: "seller-a" }),
  ).rejects.toThrow();
  expect(fetch).toHaveBeenCalledExactlyOnceWith(
    "/v1/lead-desk/activity/summary?days=30&person=seller-a",
    expect.anything(),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}")),
  );
  await expect(readAnalytics({ team: true })).rejects.toThrow("unavailable");
});

it("keeps a person active through messages and meetings without adding fake calls", () => {
  const result = activitySummary(
    history([
      event("message", "message", now),
      event("meeting", "meeting", now),
      event("intake", "captured", now),
    ]),
  );
  expect(result.current).toEqual({
    calls: 0,
    conversations: 0,
    notes: 0,
    moves: 0,
  });
  expect(result.currentWork).toBe(2);
  expect(result.people[0].work).toBe(2);
  expect(result.people[0].daily[29]?.work).toBe(2);
});
