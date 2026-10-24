import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { dayLabel, listTime, NO_FILTER, type ChatThread } from "./chats-client";
import { FIRST_ROWS, ThreadList } from "./thread-list";

vi.mock("next/link", () => ({
  default: ({
    href,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} href={href} />
  ),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const now = new Date(2026, 9, 24, 15, 30);
const thread = (index: number): ChatThread => ({
  key: `messenger:${String(index).padStart(8, "0")}-1111-4111-8111-111111111111`,
  channel: "messenger",
  leadId: `${String(index).padStart(8, "0")}-1111-4111-8111-111111111111`,
  leadName: `Fictional Lead ${index + 1}`,
  lastText: "Is the 2 BHK still free?",
  lastAt: new Date(now.getTime() - index * 3_600_000).toISOString(),
  waiting: false,
  windowOpen: true,
});

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("paints the first rows with the screen and more as the list nears its end", async () => {
  const watched: Array<(entries: { isIntersecting: boolean }[]) => void> = [];
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
        watched.push(callback);
      }
      observe() {}
      disconnect() {}
    },
  );
  const threads = Array.from({ length: 150 }, (_, index) => thread(index));
  const list = (
    <ThreadList
      threads={threads}
      filter={NO_FILTER}
      me={null}
      marks={{}}
      sla={null}
      activeKey={null}
      showOwner={false}
      now={now}
      onOpen={() => undefined}
      onClear={() => undefined}
    />
  );
  await act(async () => root.render(list));
  const rows = () => host.querySelectorAll("li:not([aria-hidden])").length;
  expect(rows()).toBe(FIRST_ROWS);
  // Nothing more joins until the end comes near.
  await act(async () => await new Promise((done) => setTimeout(done, 50)));
  expect(rows()).toBe(FIRST_ROWS);
  for (let step = 0; step < 3; step++)
    await act(async () => watched.at(-1)?.([{ isIntersecting: true }]));
  expect(rows()).toBe(150);
  expect(host.querySelector("li[aria-hidden]")).toBeNull();
  expect(host.querySelector("li:last-child strong")?.textContent).toBe(
    "Fictional Lead 150",
  );
  vi.unstubAllGlobals();
});

it("tells times the same way with its formats made once", () => {
  const today = new Date(2026, 9, 24, 9, 5).toISOString();
  expect(listTime(today, now)).toBe(
    new Date(today).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    }),
  );
  expect(listTime(new Date(2026, 9, 23, 22, 0).toISOString(), now)).toBe(
    "Yesterday",
  );
  const older = new Date(2026, 8, 2, 10, 0).toISOString();
  expect(listTime(older, now)).toBe(
    new Date(older).toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
    }),
  );
  expect(dayLabel(new Date(2026, 9, 24, 1, 0).toISOString(), now)).toBe(
    "Today",
  );
  expect(dayLabel(new Date(2025, 0, 3, 10, 0).toISOString(), now)).toBe(
    new Date(2025, 0, 3).toLocaleDateString(undefined, {
      day: "numeric",
      month: "long",
      year: "numeric",
    }),
  );
});
