import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { resetBackCloseForTests } from "../ui/back-close";
import { ago, groupNotifications, UpdatesBell } from "./updates-bell";
import type { UpdateNotification } from "./updates-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const release: UpdateNotification = {
  id: "fictional-release",
  kind: "updates",
  title: "6 new updates",
  href: null,
  urgent: false,
  created_at: "2026-10-09T00:00:00Z",
  read: false,
  count: 6,
};
const event: UpdateNotification = {
  ...release,
  id: "fictional-event",
  kind: "report_ready",
  title: "Fictional report ready",
  href: "/analysis/calls",
  body: "Your report is ready",
  urgent: true,
  created_at: "2026-10-10T00:00:00Z",
};
const trigger = () =>
  host.querySelector<HTMLButtonElement>('[aria-label="Notifications"]')!;
const sheet = () => document.querySelector<HTMLDialogElement>("dialog[open]")!;
const rows = () =>
  Array.from(sheet().querySelectorAll<HTMLButtonElement>("li > button"));

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  resetBackCloseForTests();
});

it("words times as people say them", () => {
  const now = Date.parse("2026-10-25T10:00:00Z");
  expect(ago("2026-10-25T09:59:40Z", now)).toBe("Just now");
  expect(ago("2026-10-25T09:48:00Z", now)).toBe("12 min ago");
  expect(ago("2026-10-25T07:00:00Z", now)).toBe("3 h ago");
  expect(ago("2026-10-24T06:00:00Z", now)).toBe("Yesterday");
  expect(ago("2026-10-12T06:00:00Z", now)).toBe("12 Oct");
});

// Owner program, 25 Oct 2026: grouping and priorities.
it("puts what needs you first, then what is new, then what was read", () => {
  const read = { ...release, id: "read", read: true };
  const groups = groupNotifications([read, release, event]);
  expect(groups.map((group) => group.title)).toEqual([
    "Needs you",
    "New",
    "Earlier",
  ]);
  expect(groups[0].items[0].id).toBe("fictional-event");
  expect(groupNotifications([read]).map((group) => group.title)).toEqual([
    "Earlier",
  ]);
});

it("uses the API count, opens release notes and gives focus back on close", async () => {
  const openNews = vi.fn();
  await act(async () =>
    root.render(
      <UpdatesBell
        notifications={[release]}
        unreadCount={6}
        status="ready"
        openNews={openNews}
        openEvent={async () => {}}
      />,
    ),
  );
  expect(trigger().textContent).toBe("6");
  await act(async () => trigger().click());
  expect(trigger().getAttribute("aria-expanded")).toBe("true");
  expect(rows()[0].textContent).toContain("What's new");
  await act(async () => rows()[0].click());
  expect(openNews).toHaveBeenCalledTimes(1);
  expect(trigger().getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(trigger());
});

it("keeps unsafe entries visible with navigation disabled, and safe events use the callback", async () => {
  const openEvent = vi.fn().mockResolvedValue(undefined);
  await act(async () =>
    root.render(
      <UpdatesBell
        notifications={[
          {
            ...event,
            href: "//external.test",
            id: "unsafe",
            created_at: "2026-10-11T00:00:00Z",
          },
          event,
        ]}
        unreadCount={2}
        status="ready"
        openNews={() => {}}
        openEvent={openEvent}
      />,
    ),
  );
  await act(async () => trigger().click());
  const [unsafe, safe] = rows();
  expect(unsafe.disabled).toBe(true);
  expect(unsafe.textContent).toContain("Fictional report ready");
  expect(safe.textContent).toContain("Open report");
  await act(async () => safe.click());
  expect(openEvent).toHaveBeenCalledWith(event);
});

it("shows acknowledgement failures without closing the list", async () => {
  await act(async () =>
    root.render(
      <UpdatesBell
        notifications={[event]}
        unreadCount={1}
        status="ready"
        openNews={() => {}}
        openEvent={async () => {
          throw new Error("offline");
        }}
      />,
    ),
  );
  await act(async () => trigger().click());
  await act(async () => rows()[0].click());
  expect(sheet().querySelector('[role="alert"]')?.textContent).toContain(
    "Try again",
  );
  expect(trigger().getAttribute("aria-expanded")).toBe("true");
});

it("marks every unread line read in one tap", async () => {
  const markRead = vi.fn().mockResolvedValue(undefined);
  await act(async () =>
    root.render(
      <UpdatesBell
        notifications={[release, event, { ...release, id: "old", read: true }]}
        unreadCount={2}
        status="ready"
        openNews={() => {}}
        openEvent={async () => {}}
        markRead={markRead}
      />,
    ),
  );
  await act(async () => trigger().click());
  expect(sheet().textContent).toContain("2 unread");
  const all = Array.from(sheet().querySelectorAll("button")).find(
    (button) => button.textContent === "Mark all read",
  )!;
  await act(async () => all.click());
  expect(markRead).toHaveBeenCalledWith([
    "fictional-release",
    "fictional-event",
  ]);
});

it.each([
  ["loading", "Loading notifications"],
  ["error", "Notifications could not load"],
  ["ready", "You're up to date"],
] as const)("renders %s state", async (status, text) => {
  await act(async () =>
    root.render(
      <UpdatesBell
        notifications={[]}
        unreadCount={0}
        status={status}
        openNews={() => {}}
        openEvent={async () => {}}
      />,
    ),
  );
  await act(async () => trigger().click());
  expect(sheet().textContent).toContain(text);
  expect(trigger().textContent).toBe("");
});
