import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { UpdatesBell } from "./updates-bell";
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
};
const trigger = () =>
  host.querySelector<HTMLButtonElement>('[aria-label="Notifications"]')!;
const panel = () =>
  document.querySelector<HTMLElement>(
    '[role="dialog"][aria-label="Notifications"]',
  )!;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("uses the API count, opens release notes and returns focus on Escape", async () => {
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
  await act(async () =>
    panel().querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(openNews).toHaveBeenCalledTimes(1);
  expect(panel()).toBeNull();
  await act(async () => trigger().click());
  await act(async () =>
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    ),
  );
  expect(trigger().getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(trigger());
});
it("keeps unsafe entries visible with navigation disabled, and safe events use the callback", async () => {
  const openEvent = vi.fn().mockResolvedValue(undefined);
  await act(async () =>
    root.render(
      <UpdatesBell
        notifications={[
          { ...event, href: "//external.test", id: "unsafe" },
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
  const buttons = panel().querySelectorAll<HTMLButtonElement>("button");
  expect(buttons[0].disabled).toBe(true);
  expect(buttons[0].textContent).toContain("Fictional report ready");
  await act(async () => buttons[1].click());
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
  await act(async () =>
    panel().querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(panel().querySelector('[role="alert"]')?.textContent).toContain(
    "Try again",
  );
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
  expect(panel().textContent).toContain(text);
  expect(trigger().textContent).toBe("");
});
