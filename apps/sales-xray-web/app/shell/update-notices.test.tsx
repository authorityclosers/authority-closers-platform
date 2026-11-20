// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AppAlert } from "../ui/alerts";
import type { UpdateNote, UpdateNotification } from "./updates-client";
const mocks = vi.hoisted(() => ({
  raise: vi.fn(),
  clear: vi.fn(),
  notify: vi.fn(),
  claimed: false,
  sounds: [] as string[],
}));
// The library sound a line plays (round-2 board 4, 20 Nov 2026), heard here as its moment.
vi.mock("../sounds/player", () => ({
  playEvent: (id: string) => {
    mocks.sounds.push(id);
    return id;
  },
}));

vi.mock("../ui/alerts", () => ({
  raiseAlert: mocks.raise,
  clearAlert: mocks.clear,
}));
vi.mock("../notice-center", () => ({
  notify: mocks.notify,
  dismissNotice: vi.fn(),
}));
vi.mock("./update-card-rules", async (original) => ({
  ...(await original<typeof import("./update-card-rules")>()),
  claimUpdateCard: () => {
    if (mocks.claimed) return false;
    mocks.claimed = true;
    return true;
  },
}));
import {
  ACTIVITY_BANNER_MS,
  raiseNotificationLines,
  UpdateNotices,
} from "./update-notices";
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
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
// Bell lines from the last hours: only those pop (tester report 206).
const HOUR = 60 * 60 * 1000;
const hoursAgo = (hours: number) =>
  new Date(Date.now() - hours * HOUR).toISOString();
const event: UpdateNotification = {
  id: "fictional-event",
  kind: "lead_assigned",
  title: "Neha Fictional is your lead now",
  body: "New from your website form.",
  href: "/leads",
  urgent: true,
  created_at: hoursAgo(1),
  read: false,
};
const markSeen = vi.fn().mockResolvedValue(undefined);
const markRead = vi.fn().mockResolvedValue(undefined);
const updates = {
  notes: [note, { ...note, key: "second" }],
  unseen_count: 2,
  notifications: [
    event,
    {
      ...event,
      id: "older",
      kind: "report_ready" as const,
      created_at: hoursAgo(2),
    },
    { ...event, id: "not-urgent", urgent: false },
    { ...event, id: "already-read", read: true },
  ],
  unread_count: 3,
  status: "ready" as const,
  notifications_status: "ready" as const,
  markSeen,
  markRead,
};
const raised = (): AppAlert[] => mocks.raise.mock.calls.map(([alert]) => alert);
let account = 0;
beforeEach(() => {
  vi.clearAllMocks();
  mocks.claimed = false;
  mocks.sounds = [];
  account += 1;
  window.sessionStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("shows what the bell received as a top banner, never as a corner card", async () => {
  const openNews = vi.fn();
  const openEvent = vi.fn();
  const render = () => (
    <UpdateNotices
      updates={updates}
      contextKey={`account-${account}`}
      openNews={openNews}
      openEvent={openEvent}
    />
  );
  await act(async () => root.render(render()));
  // One of the two major notes, and the newest urgent unread event only.
  expect(raised().map((alert) => alert.title)).toEqual([
    note.title,
    event.title,
  ]);
  for (const alert of raised()) {
    expect(alert.level).toBe("normal");
    expect(alert.timeout).toBe(ACTIVITY_BANNER_MS);
  }
  expect(mocks.notify).not.toHaveBeenCalled();
  // A lead given to you sounds as "New lead given to me".
  expect(mocks.sounds).toEqual(["sx.new_lead"]);
  raised()[0].action?.run?.();
  expect(openNews).toHaveBeenCalledTimes(1);
  expect(raised()[1].action?.label).toBe("Open lead");
  raised()[1].action?.run?.();
  expect(openEvent).toHaveBeenCalledWith("/leads");
  // Leaving by itself reads nothing: the line stays unread in the bell.
  expect(markRead).not.toHaveBeenCalled();
  expect(markSeen).not.toHaveBeenCalled();

  // Rerenders and remounts show nothing again.
  await act(async () => root.render(render()));
  await act(async () => root.render(null));
  await act(async () => root.render(render()));
  expect(raised()).toHaveLength(2);
});

it("raises a page's early lines by the bell's rules, once, and clears them as the bell does", async () => {
  const key = `account-${account}`;
  const openEvent = vi.fn();
  const render = (data: Parameters<typeof UpdateNotices>[0]["updates"]) => (
    <UpdateNotices
      updates={data}
      contextKey={key}
      openNews={() => {}}
      openEvent={openEvent}
    />
  );
  // The bell has not read yet (its first read waits until the page is 3 s old).
  const waiting = {
    ...updates,
    notes: [],
    notifications: [],
    notifications_status: "loading" as const,
  };
  await act(async () => root.render(render(waiting)));
  const older = { ...event, id: "older", created_at: hoursAgo(2) };
  await act(async () => raiseNotificationLines([event, older]));
  const id = `event:${key}:fictional-event`;
  expect(raised().map((alert) => alert.id)).toEqual([id]);
  expect(raised()[0].action?.label).toBe("Open lead");
  raised()[0].action?.run?.();
  expect(openEvent).toHaveBeenCalledWith("/leads");
  // The bell's own read finds them shown: no second banner, not even the older.
  await act(async () =>
    root.render(
      render({
        ...waiting,
        notifications: [event, older],
        notifications_status: "ready",
      }),
    ),
  );
  expect(mocks.raise).toHaveBeenCalledTimes(1);
  await act(async () =>
    root.render(
      render({
        ...waiting,
        notifications: [{ ...event, read: true }, older],
        notifications_status: "ready",
      }),
    ),
  );
  expect(mocks.clear).toHaveBeenCalledWith(id);
});

it("raises nothing before the bell is ready, or from what is not a bell line", async () => {
  raiseNotificationLines([event]);
  await act(async () =>
    root.render(
      <UpdateNotices
        updates={{ ...updates, notes: [], notifications: [] }}
        contextKey={`account-${account}`}
        openNews={() => {}}
        openEvent={() => {}}
      />,
    ),
  );
  await act(async () => {
    raiseNotificationLines("not a list");
    raiseNotificationLines([{ ...event, href: 7 }]);
  });
  expect(mocks.raise).not.toHaveBeenCalled();
});

it("clears a banner whose line has left the bell, but never on a list that failed", async () => {
  const key = `account-${account}`;
  const render = (data: Parameters<typeof UpdateNotices>[0]["updates"]) => (
    <UpdateNotices
      updates={data}
      contextKey={key}
      openNews={() => {}}
      openEvent={() => {}}
    />
  );
  await act(async () =>
    root.render(render({ ...updates, notifications: [event] })),
  );
  const id = `event:${key}:fictional-event`;
  expect(raised().map((alert) => alert.id)).toContain(id);
  // The lead went to someone else: the next poll fails first, then loads without it.
  await act(async () =>
    root.render(
      render({
        ...updates,
        notifications: [],
        notifications_status: "error",
      }),
    ),
  );
  expect(mocks.clear).not.toHaveBeenCalledWith(id);
  await act(async () => root.render(render({ ...updates, notifications: [] })));
  expect(mocks.clear).toHaveBeenCalledWith(id);
});

it("clears banners once read and for another account, and never follows an unsafe link", async () => {
  const openEvent = vi.fn();
  const key = `account-${account}`;
  const render = (contextKey: string | null, data = updates) => (
    <UpdateNotices
      updates={data}
      contextKey={contextKey}
      openNews={() => {}}
      openEvent={openEvent}
    />
  );
  await act(async () =>
    root.render(
      render(key, {
        ...updates,
        notifications: [{ ...event, href: "//external.test" }],
      }),
    ),
  );
  const banner = raised().find((alert) => alert.id.startsWith("event:"))!;
  expect(banner.action).toBeUndefined();
  expect(openEvent).not.toHaveBeenCalled();
  await act(async () =>
    root.render(
      render(key, {
        ...updates,
        notes: [{ ...note, seen: true }],
        notifications: [{ ...event, read: true }],
      }),
    ),
  );
  expect(mocks.clear).toHaveBeenCalledWith(`update:${key}:fictional-note`);
  expect(mocks.clear).toHaveBeenCalledWith(`event:${key}:fictional-event`);
  await act(async () => root.render(render(null)));
  const count = mocks.raise.mock.calls.length;
  await act(async () => root.render(render(null)));
  expect(mocks.raise).toHaveBeenCalledTimes(count);
});

it("never pops a line older than a day, from the bell or a page; it waits in the bell (tester report 206)", async () => {
  // Production 1.58, 14 Nov 2026: a lead given on 30 Oct, still unread,
  // popped over a call report at an app open two weeks later.
  const stale = { ...event, id: "stale", created_at: hoursAgo(14 * 24) };
  await act(async () =>
    root.render(
      <UpdateNotices
        updates={{
          ...updates,
          notes: [],
          notifications: [stale],
          unread_count: 1,
        }}
        contextKey={`account-${account}`}
        openNews={vi.fn()}
        openEvent={vi.fn()}
      />,
    ),
  );
  await act(async () => raiseNotificationLines([stale]));
  expect(raised()).toEqual([]);
});

it("sounds each bell line as its library moment, and What's new not at all", async () => {
  const { LINE_SOUND } = await import("./update-notices");
  expect(LINE_SOUND).toEqual({
    report_ready: "sx.report_ready",
    lead_assigned: "sx.new_lead",
    analysis_paused: "sx.upload_failed",
    invite_received: "sx.new_message",
    bug_solved: "sx.new_message",
  });
  expect(LINE_SOUND.updates).toBeUndefined();
});
