import { afterEach, expect, it, vi } from "vitest";
import {
  parseUpdates,
  parseNotifications,
  parseSeen,
  parseRead,
  readUpdates,
  readNotifications,
  markUpdatesSeen,
  markNotificationsRead,
  isRelativeUpdateHref,
} from "./updates-client";

const note = {
  key: "seed-fictional",
  version: 1,
  release_id: "fictional-release",
  date: "2026-10-05",
  title: "Fictional update",
  items: ["Updates follow your account"],
  major: true,
  draft: false,
  seen: false,
  published_at: "2026-10-05T12:00:00Z",
};
const release = {
  id: "updates:fictional-release",
  kind: "updates",
  count: 1,
  title: "1 new update",
  href: null,
  urgent: false,
  created_at: "2026-10-05T12:00:00Z",
  read: false,
};
const event = {
  id: "fictional-event",
  kind: "report_ready",
  title: "Report ready",
  body: "Your fictional report is ready",
  href: "/analysis/calls/fictional",
  urgent: true,
  created_at: "2026-10-05T12:00:00Z",
  read: false,
};
afterEach(() => vi.unstubAllGlobals());

it("accepts the API note, release and event shapes without inventing state", () => {
  expect(parseUpdates({ updates: [note], unseen_count: 1 }).notes).toEqual([
    note,
  ]);
  expect(
    parseUpdates({
      updates: [{ ...note, draft: true, published_at: null }],
      unseen_count: 1,
    }).notes[0].draft,
  ).toBe(true);
  expect(
    parseNotifications({ notifications: [release, event], unread_count: 2 })
      .notifications,
  ).toEqual([release, event]);
});
it.each([
  null,
  [],
  {},
  { updates: null, unseen_count: 0 },
  { updates: [note], unseen_count: "1" },
  { updates: [note], unseen_count: -1 },
])("rejects malformed update lists: %j", (value) => {
  expect(() => parseUpdates(value)).toThrow();
});
it.each([
  { key: null },
  { version: 0 },
  { date: "yesterday" },
  { items: [] },
  { items: [1] },
  { major: "true" },
  { draft: null },
  { seen: "false" },
  { published_at: "yesterday" },
])("rejects malformed note fields: %j", (patch) => {
  expect(() =>
    parseUpdates({ updates: [{ ...note, ...patch }], unseen_count: 1 }),
  ).toThrow();
});
it.each([
  null,
  {},
  { notifications: {}, unread_count: 0 },
  { notifications: [], unread_count: 0.5 },
  { notifications: [{ ...release, count: "1" }], unread_count: 1 },
  { notifications: [{ ...event, body: null }], unread_count: 1 },
  { notifications: [{ ...event, href: null }], unread_count: 1 },
  { notifications: [{ ...event, href: 1 }], unread_count: 1 },
  { notifications: [{ ...event, kind: "unknown" }], unread_count: 1 },
])("rejects malformed notification responses: %j", (value) => {
  expect(() => parseNotifications(value)).toThrow();
});
it.each([
  "https://example.test",
  "//example.test/path",
  "/\\example.test",
  "/path\n",
  "javascript:alert(1)",
  "relative/path",
  "/\t/example.test",
  "/\u0000/example.test",
])(
  "keeps unsafe destinations visible without a navigation link: %s",
  (href) => {
    expect(isRelativeUpdateHref(href)).toBe(false);
    expect(
      parseNotifications({
        notifications: [release, { ...event, href }],
        unread_count: 2,
      }),
    ).toEqual({
      notifications: [release, { ...event, href: null }],
      unread_count: 2,
    });
  },
);
it.each(["/", "/analysis/calls/fictional", "/my report?label=hello world"])(
  "preserves safe relative paths, including spaces: %s",
  (href) => {
    expect(isRelativeUpdateHref(href)).toBe(true);
    expect(
      parseNotifications({
        notifications: [{ ...event, href }],
        unread_count: 1,
      }).notifications[0].href,
    ).toBe(href);
  },
);
it.each([
  null,
  [],
  {},
  { unseen_count: -1 },
  { unseen_count: "0" },
  { unseen_count: Number.NaN },
])("rejects malformed seen receipts: %j", (value) =>
  expect(() => parseSeen(value)).toThrow(),
);
it.each([
  null,
  [],
  {},
  { unread_count: -1 },
  { unread_count: "0" },
  { unread_count: Infinity },
])("rejects malformed read receipts: %j", (value) =>
  expect(() => parseRead(value)).toThrow(),
);
it("uses exactly the four same-origin endpoints and validates each receipt", async () => {
  const fetcher = vi
    .fn()
    .mockImplementation((path: string) =>
      Promise.resolve(
        Response.json(
          path === "/v1/updates"
            ? { updates: [note], unseen_count: 1 }
            : path === "/v1/notifications"
              ? { notifications: [release], unread_count: 1 }
              : path === "/v1/updates/seen"
                ? { unseen_count: 0 }
                : { unread_count: 0 },
        ),
      ),
    );
  vi.stubGlobal("fetch", fetcher);
  await readUpdates();
  await readNotifications();
  await markUpdatesSeen([note.key]);
  await markNotificationsRead([event.id]);
  expect(fetcher.mock.calls.map(([path]) => path)).toEqual([
    "/v1/updates",
    "/v1/notifications",
    "/v1/updates/seen",
    "/v1/notifications/read",
  ]);
  for (const [, init] of fetcher.mock.calls)
    expect(init).toMatchObject({
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
  expect(fetcher.mock.calls[2][1]).toMatchObject({
    method: "POST",
    body: JSON.stringify({ keys: [note.key] }),
  });
  expect(fetcher.mock.calls[3][1]).toMatchObject({
    method: "POST",
    body: JSON.stringify({ ids: [event.id] }),
  });
  fetcher.mockResolvedValueOnce(new Response(null, { status: 401 }));
  await expect(readUpdates()).rejects.toThrow("updates_request_failed:401");
  fetcher.mockResolvedValueOnce(Response.json({ unseen_count: "0" }));
  await expect(markUpdatesSeen([note.key])).rejects.toThrow(
    "invalid_seen_response",
  );
});
