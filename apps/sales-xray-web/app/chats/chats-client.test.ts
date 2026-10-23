import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  chatHref,
  composerState,
  dayGroups,
  fileSize,
  filterThreads,
  hasMedia,
  isUnread,
  mediaUrl,
  markSeen,
  NO_FILTER,
  previewLine,
  readChats,
  readSeen,
  readThread,
  sameThread,
  threadKey,
  waitedFor,
  waitTone,
  type ChatDetail,
  type ChatThread,
} from "./chats-client";
import { openedFromHash } from "./chats-page";

const NOW = new Date("2027-01-15T10:00:00Z");
const LEAD_A = "11111111-1111-4111-8111-111111111111";
const LEAD_B = "22222222-2222-4222-8222-222222222222";
const ACCOUNT = "33333333-3333-4333-8333-333333333333";

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), {
    status: code,
    headers: { "content-type": "application/json" },
  });

let routes: Record<string, () => Response>;

beforeEach(() => {
  routes = {};
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const found = Object.entries(routes).find(([path]) => url.endsWith(path));
      return found ? found[1]() : json({ detail: "Not here." }, 404);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const thread = (extra: Partial<ChatThread> = {}): ChatThread => ({
  key: threadKey("messenger", LEAD_A),
  channel: "messenger",
  leadId: LEAD_A,
  leadName: "Asha Rao",
  lastText: "Is the 2BHK free?",
  lastAt: new Date(NOW.getTime() - 5 * 60000).toISOString(),
  waiting: true,
  windowOpen: true,
  ...extra,
});

it("merges WhatsApp, Messenger and Instagram, waiting first then newest", async () => {
  routes["/social/inbox"] = () =>
    json([
      {
        leadId: LEAD_A,
        leadName: "Asha Rao",
        channel: "messenger",
        lastText: "Hello",
        lastAt: "2027-01-15T09:00:00Z",
        waiting: false,
        windowOpen: true,
      },
      {
        leadId: LEAD_B,
        leadName: "Ravi Iyer",
        channel: "instagram",
        lastText: null,
        lastAt: "2027-01-15T08:00:00Z",
        waiting: true,
        windowOpen: true,
      },
    ]);
  routes["/whatsapp/inbox"] = () =>
    json([
      {
        leadId: LEAD_A,
        leadName: "Asha Rao",
        lastText: "Price?",
        lastAt: "2027-01-15T09:30:00Z",
        waiting: false,
        windowOpen: true,
      },
    ]);
  const list = await readChats();
  expect(list.threads.map((t) => [t.channel, t.leadName])).toEqual([
    ["instagram", "Ravi Iyer"],
    ["whatsapp", "Asha Rao"],
    ["messenger", "Asha Rao"],
  ]);
  expect(list.threads[0].key).toBe(`instagram:${LEAD_B}`);
  expect(list.threads[0].lastDirection).toBe("in");
  // The server doesn't send owners yet: no Mine / Unassigned filter.
  expect(list.owners).toBe(false);
});

it("keeps working when one channel isn't set up, and fails only when none answers", async () => {
  routes["/social/inbox"] = () => json([]);
  routes["/whatsapp/inbox"] = () =>
    json({ detail: "WhatsApp isn't set up." }, 409);
  expect((await readChats()).threads).toEqual([]);
  routes["/social/inbox"] = () => json({ detail: "Sign in." }, 401);
  await expect(readChats()).rejects.toMatchObject({ status: 401 });
});

it("reads the owner and reply clock when the server sends them", async () => {
  routes["/social/inbox"] = () =>
    json([
      {
        leadId: LEAD_A,
        leadName: "Asha Rao",
        channel: "messenger",
        lastText: "Hi",
        lastAt: "2027-01-15T09:00:00Z",
        waiting: true,
        windowOpen: true,
        accountId: ACCOUNT,
        place: "Messenger · Fictional Homes",
        ownerId: "p1",
        ownerName: "Neha",
        waitingSince: "2027-01-15T08:50:00Z",
      },
    ]);
  routes["/whatsapp/inbox"] = () => json([]);
  const list = await readChats();
  expect(list.owners).toBe(true);
  expect(list.threads[0]).toMatchObject({
    key: `messenger:${LEAD_A}:${ACCOUNT}`,
    ownerName: "Neha",
    place: "Messenger · Fictional Homes",
    waitingSince: "2027-01-15T08:50:00Z",
  });
});

it("filters by whose, channel, waiting and name", () => {
  const threads = [
    thread(),
    thread({
      key: "whatsapp:x",
      channel: "whatsapp",
      leadName: "Ravi Iyer",
      waiting: false,
      ownerId: "me",
    }),
  ];
  expect(filterThreads(threads, NO_FILTER, "me")).toHaveLength(2);
  expect(
    filterThreads(threads, { ...NO_FILTER, scope: "mine" }, "me"),
  ).toHaveLength(1);
  expect(
    filterThreads(threads, { ...NO_FILTER, scope: "unassigned" }, "me")[0]
      .leadName,
  ).toBe("Asha Rao");
  expect(
    filterThreads(threads, { ...NO_FILTER, channel: "whatsapp" }, "me"),
  ).toHaveLength(1);
  expect(
    filterThreads(threads, { ...NO_FILTER, waitingOnly: true }, "me"),
  ).toHaveLength(1);
  expect(
    filterThreads(threads, { ...NO_FILTER, search: "ravi" }, "me")[0].leadName,
  ).toBe("Ravi Iyer");
});

it("marks a chat seen up to its newest message, per person", () => {
  const open = thread();
  expect(isUnread(open, {})).toBe(true);
  const marks = markSeen("p1", {}, open);
  expect(isUnread(open, marks)).toBe(false);
  expect(readSeen("p1")).toEqual(marks);
  expect(readSeen("p2")).toEqual({});
  // A newer message brings the dot back.
  expect(
    isUnread({ ...open, lastAt: new Date(NOW).toISOString() }, marks),
  ).toBe(true);
  // Answered chats never show a dot; the server's own count wins.
  expect(isUnread({ ...open, waiting: false }, {})).toBe(false);
  expect(isUnread({ ...open, unread: 0 }, {})).toBe(false);
  expect(isUnread({ ...open, waiting: false, unread: 2 }, {})).toBe(true);
  // Read here since the server's count: read until the next count; a newer
  // message brings it back.
  expect(isUnread({ ...open, unread: 2 }, marks)).toBe(false);
  expect(
    isUnread(
      { ...open, unread: 2, lastAt: new Date(NOW).toISOString() },
      marks,
    ),
  ).toBe(true);
});

it("reads a message's file through Sales X-Ray, never from Meta", () => {
  expect(mediaUrl("whatsapp", "w 1")).toBe(
    "/v1/lead-desk/chats/media/whatsapp/w%201",
  );
  expect(mediaUrl("messenger", "m2", { preview: true })).toBe(
    "/v1/lead-desk/chats/media/messenger/m2?size=preview",
  );
  expect(hasMedia({ id: "m2", kind: "image" })).toBe(true);
  expect(hasMedia({ id: "m3", kind: "location" })).toBe(false);
  // A message still on its way has no file on the server yet.
  expect(hasMedia({ id: "pending-1", kind: "image" })).toBe(false);
  expect(fileSize(900)).toBe("900 B");
  expect(fileSize(245760)).toBe("240 KB");
  expect(fileSize(2.5 * 1024 * 1024)).toBe("2.5 MB");
  expect(fileSize(null)).toBeNull();
});

it("says how long they waited, calm, then amber, then red past the target", () => {
  const since = (minutes: number) =>
    new Date(NOW.getTime() - minutes * 60000).toISOString();
  expect(waitedFor(since(0), NOW)).toBe("now");
  expect(waitedFor(since(7), NOW)).toBe("7 min");
  expect(waitedFor(since(65), NOW)).toBe("1 h 5 min");
  expect(waitedFor(since(120), NOW)).toBe("2 h");
  expect(waitedFor(since(60 * 50), NOW)).toBe("2 d");
  const sla = { on: true, minutes: 10 };
  expect(waitTone(since(3), sla, NOW)).toBe("neutral");
  expect(waitTone(since(6), sla, NOW)).toBe("warn");
  expect(waitTone(since(11), sla, NOW)).toBe("bad");
});

it("groups messages by day and joins a run of one side's messages", () => {
  const at = (iso: string) => iso;
  const groups = dayGroups(
    [
      {
        id: "1",
        direction: "in",
        kind: "text",
        text: "a",
        status: "received",
        at: at("2027-01-14T09:00:00Z"),
      },
      {
        id: "2",
        direction: "in",
        kind: "text",
        text: "b",
        status: "received",
        at: at("2027-01-15T09:00:00Z"),
      },
      {
        id: "3",
        direction: "in",
        kind: "text",
        text: "c",
        status: "received",
        at: at("2027-01-15T09:02:00Z"),
      },
      {
        id: "4",
        direction: "out",
        kind: "text",
        text: "d",
        status: "read",
        at: at("2027-01-15T09:03:00Z"),
      },
    ],
    NOW,
  );
  expect(groups.map((group) => group.day)).toEqual(["Yesterday", "Today"]);
  expect(
    groups[1].items.map((item) => [item.message.id, item.first, item.last]),
  ).toEqual([
    ["2", true, false],
    ["3", false, true],
    ["4", true, true],
  ]);
});

it("names what a message without words is", () => {
  expect(previewLine(thread({ lastText: null, lastKind: "image" }))).toBe(
    "Photo",
  );
  expect(previewLine(thread({ lastText: null }))).toBe(
    "A photo, file or sticker",
  );
});

const detail = (extra: Partial<ChatDetail> = {}): ChatDetail => ({
  channel: "messenger",
  place: "Messenger · Fictional Homes",
  accountId: ACCOUNT,
  messages: [],
  windowOpen: true,
  windowClosesAt: new Date(NOW.getTime() + 5 * 3600_000).toISOString(),
  humanAgent: false,
  templates: [],
  optedIn: false,
  others: [],
  ...extra,
});

it("explains Meta's 24-hour window in plain words", () => {
  expect(composerState(detail(), NOW)).toEqual({
    canWrite: true,
    line: "",
    tone: "neutral",
  });
  expect(
    composerState(
      detail({
        windowClosesAt: new Date(NOW.getTime() + 20 * 60000).toISOString(),
      }),
      NOW,
    ).line,
  ).toMatch(/within 20 min/);
  expect(
    composerState(detail({ windowOpen: false, channel: "whatsapp" }), NOW),
  ).toMatchObject({ canWrite: false, line: expect.stringMatching(/template/) });
  expect(
    composerState(detail({ windowOpen: false, humanAgent: true }), NOW),
  ).toMatchObject({ canWrite: true, line: expect.stringMatching(/7 days/) });
  expect(composerState(detail({ windowOpen: false }), NOW).canWrite).toBe(
    false,
  );
});

it("opens the chat's own Page when a lead wrote to two", async () => {
  const OTHER = "44444444-4444-4444-8444-444444444444";
  routes[`/leads/${LEAD_A}/social`] = () =>
    json({
      configured: true,
      connected: true,
      threads: [
        {
          accountId: OTHER,
          channel: "messenger",
          place: "Messenger · Other",
          messages: [],
          windowOpen: false,
          humanAgent: false,
        },
        {
          accountId: ACCOUNT,
          channel: "messenger",
          place: "Messenger · Fictional Homes",
          messages: [],
          windowOpen: true,
          humanAgent: false,
        },
        {
          accountId: ACCOUNT,
          channel: "instagram",
          place: "Instagram · @fictional",
          messages: [],
          windowOpen: true,
          humanAgent: false,
        },
      ],
    });
  const found = await readThread({
    channel: "messenger",
    leadId: LEAD_A,
    accountId: ACCOUNT,
  });
  expect(found?.place).toBe("Messenger · Fictional Homes");
  expect(found?.others).toEqual([
    { accountId: OTHER, place: "Messenger · Other" },
  ]);
});

it("reads the open chat from the address and ignores anything else", () => {
  expect(openedFromHash(`#chat=messenger:${LEAD_A}`)).toEqual({
    key: `messenger:${LEAD_A}`,
    channel: "messenger",
    leadId: LEAD_A,
    accountId: null,
  });
  expect(openedFromHash(`#chat=whatsapp:${LEAD_A}:${ACCOUNT}`)?.accountId).toBe(
    ACCOUNT,
  );
  expect(openedFromHash("#chat=sms:abc")).toBeNull();
  expect(openedFromHash("#chat=messenger:<script>")).toBeNull();
  expect(openedFromHash("")).toBeNull();
});

it("links to one chat and finds it with or without the account", () => {
  expect(chatHref("messenger", LEAD_A)).toBe(`/chats#chat=messenger:${LEAD_A}`);
  expect(chatHref("whatsapp", LEAD_A, ACCOUNT)).toBe(
    `/chats#chat=whatsapp:${LEAD_A}:${ACCOUNT}`,
  );
  const base = { channel: "messenger" as const, leadId: LEAD_A };
  expect(sameThread({ ...base, accountId: ACCOUNT }, base)).toBe(true);
  expect(
    sameThread({ ...base, accountId: ACCOUNT }, { ...base, accountId: LEAD_B }),
  ).toBe(false);
  expect(sameThread(base, { ...base, channel: "instagram" })).toBe(false);
  expect(sameThread({ ...base, leadId: null }, { ...base, leadId: null })).toBe(
    false,
  );
});

it("reads all three channels in one request when the server has GET /chats", async () => {
  routes["/v1/lead-desk/chats"] = () =>
    json({
      generatedAt: NOW.toISOString(),
      sla: { on: true, minutes: 10 },
      threads: [
        {
          key: "whatsapp:n1:abcd",
          channel: "whatsapp",
          leadId: LEAD_A,
          leadName: "Asha Rao",
          lastText: "Hi",
          lastAt: "2027-01-15T09:00:00Z",
          waiting: true,
          windowOpen: true,
          accountId: ACCOUNT,
          place: "WhatsApp · +91 99990 10009",
          lastKind: "text",
          lastDirection: "in",
          lastStatus: "received",
          waitingSince: "2027-01-15T08:58:00Z",
          ownerId: null,
          ownerName: null,
        },
        {
          key: "sms:x",
          channel: "sms",
          leadId: LEAD_B,
          leadName: "Ravi",
          lastAt: "2027-01-15T09:00:00Z",
          waiting: false,
          windowOpen: false,
        },
      ],
    });
  const list = await readChats();
  expect(list.sla).toEqual({ on: true, minutes: 10 });
  expect(list.owners).toBe(true);
  expect(list.threads).toHaveLength(1);
  expect(list.threads[0]).toMatchObject({
    key: `whatsapp:${LEAD_A}:${ACCOUNT}`,
    place: "WhatsApp · +91 99990 10009",
    waitingSince: "2027-01-15T08:58:00Z",
    ownerId: null,
  });
  // Only GET /chats was read.
  expect(vi.mocked(fetch).mock.calls.map(([url]) => String(url))).toEqual([
    "/v1/lead-desk/chats",
  ]);
});
