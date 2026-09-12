// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AppUpdateFeed, AppUpdatesApi } from "../lib/app-updates-api";
import { ApiError } from "../lib/learner-api";
import {
  AppUpdatesProvider,
  AppUpdateUnreadIndicator,
} from "./app-updates-provider";
import {
  NotificationsRuntime,
  NotificationPopover,
} from "./notifications-runtime";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const feed: AppUpdateFeed = {
  person_id: "9b678390-0d63-450c-9257-e6078c3b030e",
  tenant_id: "c94b31ee-27fd-4b70-9525-2d176437ba42",
  items: [
    {
      id: "app-updates-v0-2-alpha",
      title: "A home for app updates",
      message: "What changed in your app.",
      version: "v0.2 Alpha",
      highlights: ["Version notes", "Feature links", "Saved read state"],
      target_href: "/practice",
      created_at: "2026-09-10T00:00:00Z",
      read: false,
    },
  ],
  unread_count: 1,
};
let root: Root;
let container: HTMLDivElement;
let api: AppUpdatesApi;
const readFeed = {
  ...feed,
  unread_count: 0,
  items: feed.items.map((item) => ({ ...item, read: true })),
};
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { resolve, promise };
};
beforeEach(() => {
  vi.useFakeTimers();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  api = {
    list: vi.fn(async () => feed),
    markRead: vi.fn(async () => readFeed),
  };
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
async function render() {
  await act(async () =>
    root.render(
      <AppUpdatesProvider api={api}>
        <AppUpdateUnreadIndicator />
        <NotificationsRuntime />
        <NotificationPopover onClose={() => {}} />
      </AppUpdatesProvider>,
    ),
  );
  await act(async () => vi.advanceTimersByTimeAsync(1));
}
const button = (text: string) =>
  Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
    (node) => node.textContent?.trim() === text,
  )!;

it("mounts the live inbox and bell from one request without marking anything read on opening", async () => {
  await render();
  expect(api.list).toHaveBeenCalledTimes(1);
  expect(container.querySelector("h1")?.textContent).toBe("Notifications");
  expect(
    container.querySelector('[aria-label="App update history"]'),
  ).not.toBeNull();
  expect(container.textContent).toContain("v0.2 Alpha");
  expect(container.querySelector('a[href="/practice"]')).not.toBeNull();
  expect(container.querySelector('a[href="/notifications"]')).not.toBeNull();
  expect(api.markRead).not.toHaveBeenCalled();
  expect(container.textContent).not.toContain("4K");
});
it("keeps unread state until the server confirms and shares confirmation with the bell", async () => {
  const save = deferred<AppUpdateFeed>();
  api.markRead = vi.fn(() => save.promise);
  await render();
  await act(async () => button("Mark as read").click());
  expect(container.textContent).toContain("1 unread");
  expect(button("Saving…").getAttribute("aria-disabled")).toBe("true");
  await act(async () => save.resolve(readFeed));
  expect(container.textContent).toContain("0 unread");
  expect(container.querySelector('[data-read="true"]')).not.toBeNull();
  await act(async () => button("Unread0").click());
  expect(container.textContent).toContain("You’re up to date");
});
it("preserves unread after save failure and offers retry", async () => {
  api.markRead = vi
    .fn()
    .mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValue(readFeed);
  await render();
  await act(async () => button("Mark as read").click());
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "Couldn’t confirm",
  );
  expect(container.textContent).toContain("1 unread");
  await act(async () => button("Mark as read").click());
  expect(container.textContent).toContain("0 unread");
});
it("clears the private feed on session denial instead of retaining an old count", async () => {
  await render();
  api.list = vi.fn(async () => {
    throw new ApiError(401, "expired");
  });
  await act(async () => window.dispatchEvent(new Event("focus")));
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(container.textContent).not.toContain("A home for app updates");
  expect(container.textContent).toContain("Sign in to see your updates");
});
it("ignores a stale save after focus changes the authenticated account", async () => {
  const save = deferred<AppUpdateFeed>();
  api.markRead = vi.fn(() => save.promise);
  await render();
  await act(async () => button("Mark as read").click());
  api.list = vi.fn(async () => ({
    ...feed,
    person_id: "a9575a41-312d-41bb-968a-24f5b7bef112",
    items: [],
    unread_count: 0,
  }));
  await act(async () => window.dispatchEvent(new Event("focus")));
  await act(async () => vi.advanceTimersByTimeAsync(1));
  await act(async () => save.resolve(readFeed));
  expect(container.textContent).toContain("No app updates yet");
  expect(container.textContent).not.toContain("A home for app updates");
});
it("does not accept a save response belonging to a different account", async () => {
  api.markRead = vi.fn(async () => ({
    ...readFeed,
    tenant_id: "a9575a41-312d-41bb-968a-24f5b7bef112",
  }));
  await render();
  await act(async () => button("Mark as read").click());
  expect(container.textContent).toContain("Sign in to see your updates");
  expect(container.textContent).not.toContain("A home for app updates");
});

it("refreshes on returning to a visible tab and coalesces the accompanying focus event", async () => {
  await render();
  const visibility = vi.spyOn(document, "visibilityState", "get");
  visibility.mockReturnValue("hidden");
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(api.list).toHaveBeenCalledTimes(1);
  visibility.mockReturnValue("visible");
  api.list = vi.fn(async () => readFeed);
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("focus"));
  });
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(api.list).toHaveBeenCalledTimes(1);
  expect(container.textContent).toContain("0 unread");
});
