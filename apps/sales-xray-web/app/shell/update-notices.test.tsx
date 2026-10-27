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
import { ACTIVITY_BANNER_MS, UpdateNotices } from "./update-notices";
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
const event: UpdateNotification = {
  id: "fictional-event",
  kind: "lead_assigned",
  title: "Neha Fictional is your lead now",
  body: "New from your website form.",
  href: "/leads",
  urgent: true,
  created_at: "2026-10-27T09:00:00Z",
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
      created_at: "2026-10-27T08:00:00Z",
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
