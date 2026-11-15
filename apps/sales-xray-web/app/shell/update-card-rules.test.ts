import { expect, it, vi } from "vitest";
import type { UpdateNote, UpdateNotification } from "./updates-client";
import {
  EVENT_BANNER_MAX_AGE_MS,
  eligibleEvents,
  eligibleUpdate,
} from "./update-card-rules";

const note: UpdateNote = {
  key: "fictional-note",
  version: 1,
  release_id: "fictional-release",
  date: "2026-10-09",
  title: "Fictional update",
  items: ["Updates follow your account"],
  major: true,
  draft: false,
  seen: false,
  published_at: null,
};
const event: UpdateNotification = {
  id: "fictional-event",
  kind: "analysis_paused",
  title: "Fictional analysis paused",
  body: "Check your saved call",
  href: "/analysis/calls",
  urgent: true,
  created_at: "2026-10-09T00:00:00Z",
  read: false,
};

it("selects the first unseen major note in API order and only unread urgent events", () => {
  expect(
    eligibleUpdate([
      { ...note, major: false },
      { ...note, seen: true },
      note,
      { ...note, key: "second" },
    ]),
  ).toBe(note);
  expect(
    eligibleUpdate([
      { ...note, major: false },
      { ...note, seen: true },
    ]),
  ).toBeUndefined();
  expect(
    eligibleEvents(
      [
        event,
        { ...event, read: true },
        { ...event, urgent: false },
        { ...event, kind: "updates" },
      ],
      Date.parse("2026-10-09T01:00:00Z"),
    ),
  ).toEqual([event]);
});
it("pops only lines from the last day; older unread ones wait in the bell (tester report 206)", () => {
  const made = Date.parse(event.created_at);
  const lead: UpdateNotification = {
    ...event,
    kind: "lead_assigned",
    title: "Fictional Lead is your lead now",
  };
  expect(eligibleEvents([lead], made + 60_000)).toEqual([lead]);
  expect(eligibleEvents([lead], made + EVENT_BANNER_MAX_AGE_MS)).toEqual([
    lead,
  ]);
  // Two weeks on and still unread: no banner at the next app open.
  expect(eligibleEvents([lead], made + 14 * EVENT_BANNER_MAX_AGE_MS)).toEqual(
    [],
  );
  // A time the app can't read never hides a line.
  const odd = { ...lead, created_at: "not a time" };
  expect(eligibleEvents([odd], made + 14 * EVENT_BANNER_MAX_AGE_MS)).toEqual([
    odd,
  ]);
});
it("allows one update card across reloads of the module in a browser session", async () => {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
  vi.resetModules();
  const first = await import("./update-card-rules");
  expect(first.claimUpdateCard(storage)).toBe(true);
  expect(first.claimUpdateCard(storage)).toBe(false);
  vi.resetModules();
  expect((await import("./update-card-rules")).claimUpdateCard(storage)).toBe(
    false,
  );
});
it("prevents repeat cards in memory when browser storage throws", async () => {
  vi.resetModules();
  const rules = await import("./update-card-rules");
  const storage = {
    getItem: () => {
      throw new Error("storage disabled");
    },
    setItem: () => {
      throw new Error("storage disabled");
    },
  };
  expect(rules.claimUpdateCard(storage)).toBe(true);
  expect(rules.claimUpdateCard(null)).toBe(false);
});
