import { afterEach, expect, it, vi } from "vitest";
import type { ActivityItem } from "../leads/leads-client";
import {
  activitySummary,
  dayNumber,
  readAnalytics,
  type AnalyticsHistory,
} from "./analytics-data";
vi.mock("./organisation-api", () => ({
  readMembers: vi.fn(async () => [
    { status: "active", personId: "seller-a", name: "Mira Fictional" },
    { status: "active", personId: "seller-b", name: "Tali Example" },
  ]),
}));
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
  expect(result.people[0].daily[29]).toEqual(result.current);
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
it("paginates the team feed until both periods are covered, rather than using all-time counts", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [event("a", "note", now)],
          next_before: "2026-10-20T12:00:00Z",
          counts: { note: 9999 },
          timezone: "Asia/Kolkata",
        }),
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [event("b", "stage", "2026-09-05T12:00:00Z")],
          next_before: "2026-08-01T12:00:00Z",
          counts: { note: 9999 },
          timezone: "Asia/Kolkata",
        }),
      ),
    );
  vi.stubGlobal("fetch", fetch);
  const read = await readAnalytics({ team: true, now });
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[0][0]).toContain("team=true");
  expect(fetch.mock.calls[1][0]).toContain("before=2026-10-20");
  expect(activitySummary(read).current.notes).toBe(1);
  expect(activitySummary(read).previous.moves).toBe(1);
  expect(activitySummary(read).previousComplete).toBe(true);
});
it("bounds large reads, resumes at the cursor and never fetches the team for a seller", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          items: [event("a", "note", now)],
          next_before: "2026-10-20T12:00:00Z",
          timezone: "Asia/Kolkata",
        }),
      ),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ items: [], next_before: null })),
    );
  vi.stubGlobal("fetch", fetch);
  const first = await readAnalytics({
    team: false,
    personId: "seller-a",
    now,
    pages: 1,
  });
  expect(first.members).toHaveLength(1);
  expect(first.members[0].personId).toBe("seller-a");
  expect(fetch.mock.calls[0][0]).not.toContain("team=true");
  expect(activitySummary(first).currentComplete).toBe(false);
  const second = await readAnalytics({
    team: false,
    personId: "seller-a",
    previous: first,
  });
  expect(second.items).toHaveLength(1);
  expect(activitySummary(second).previousComplete).toBe(true);
});
it("does not call a failed or stuck read an empty period", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 403 })),
  );
  await expect(readAnalytics({ team: true, now })).rejects.toThrow();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ items: [], next_before: "2026-10-20T12:00:00Z" }),
        ),
    ),
  );
  await expect(readAnalytics({ team: true, now })).rejects.toThrow(
    "did not advance",
  );
});
