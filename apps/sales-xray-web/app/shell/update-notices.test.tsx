import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Notice } from "../notice-center";
import type { UpdateNote, UpdateNotification } from "./updates-client";
const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  dismiss: vi.fn(),
  claimed: false,
}));
vi.mock("../notice-center", () => ({
  notify: mocks.notify,
  dismissNotice: mocks.dismiss,
}));
vi.mock("./update-card-rules", async (original) => ({
  ...(await original<typeof import("./update-card-rules")>()),
  claimUpdateCard: () => {
    if (mocks.claimed) return false;
    mocks.claimed = true;
    return true;
  },
}));
import { UpdateNotices } from "./update-notices";
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
  kind: "analysis_paused",
  title: "Fictional pause",
  body: "Check your call",
  href: "/analysis/calls",
  urgent: true,
  created_at: "2026-10-09T00:00:00Z",
  read: false,
};
const markSeen = vi.fn().mockResolvedValue(undefined);
const markRead = vi.fn().mockResolvedValue(undefined);
const updates = {
  notes: [note, { ...note, key: "second" }],
  unseen_count: 2,
  notifications: [
    event,
    { ...event, id: "not-urgent", urgent: false },
    { ...event, id: "already-read", read: true },
  ],
  unread_count: 2,
  status: "ready" as const,
  notifications_status: "ready" as const,
  markSeen,
  markRead,
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.claimed = false;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("shows only one of two major notes across rerenders/remounts, and dismissals acknowledge the right keys", async () => {
  const openNews = vi.fn();
  const openEvent = vi.fn();
  const render = () => (
    <UpdateNotices
      updates={updates}
      contextKey="fictional-account"
      openNews={openNews}
      openEvent={openEvent}
    />
  );
  await act(async () => root.render(render()));
  const cards: Notice[] = mocks.notify.mock.calls.map(([card]) => card);
  expect(cards).toHaveLength(2);
  expect(cards[0].title).toBe(note.title);
  expect(cards[0].timeout).toBe(0);
  cards[0].action?.run();
  expect(openNews).toHaveBeenCalledTimes(1);
  await cards[0].onDismiss?.();
  expect(markSeen).toHaveBeenCalledWith([note.key]);
  await cards[1].onDismiss?.();
  expect(markRead).toHaveBeenCalledWith([event.id]);
  await act(async () => root.render(render()));
  await act(async () => root.render(null));
  await act(async () => root.render(render()));
  expect(
    mocks.notify.mock.calls.filter(([card]) => card.id.startsWith("update:")),
  ).toHaveLength(1);
});
it("removes acknowledged cards and old-account cards and never navigates an unsafe urgent event", async () => {
  const openEvent = vi.fn();
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
      render("first", {
        ...updates,
        notifications: [{ ...event, href: "//external.test" }],
      }),
    ),
  );
  const card: Notice = mocks.notify.mock.calls.find(([card]) =>
    card.id.startsWith("event:"),
  )![0];
  expect(card.action).toBeUndefined();
  expect(openEvent).not.toHaveBeenCalled();
  await act(async () =>
    root.render(
      render("first", {
        ...updates,
        notes: [{ ...note, seen: true }],
        notifications: [{ ...event, read: true }],
      }),
    ),
  );
  expect(mocks.dismiss).toHaveBeenCalledWith("update:first:fictional-note");
  expect(mocks.dismiss).toHaveBeenCalledWith("event:first:fictional-event");
  await act(async () => root.render(render(null)));
  const count = mocks.notify.mock.calls.length;
  await act(async () => root.render(render(null)));
  expect(mocks.notify).toHaveBeenCalledTimes(count);
});
