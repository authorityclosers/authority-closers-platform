import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CallsDrawer } from "./calls-drawer";
import { extractInsight } from "./calls-insights";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
let trigger: HTMLButtonElement;
const props = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Fictional call",
  meta: "Today",
  status: "Ready",
  tone: "ready",
  insight: null,
  readState: "loading" as const,
  hasReport: true,
  canRename: true,
  onOpen: vi.fn(),
  onRename: vi.fn(),
  onClose: vi.fn(),
  onRetry: vi.fn(),
};
const buttons = () =>
  Array.from(host.querySelectorAll<HTMLButtonElement>("button"));
const copy = () =>
  buttons().find((button) => button.textContent?.includes("Copy link"))!;
const close = () =>
  host.querySelector<HTMLButtonElement>('[aria-label="Close preview"]')!;
const key = (value: string, shiftKey = false) =>
  document.activeElement!.dispatchEvent(
    new KeyboardEvent("keydown", {
      key: value,
      shiftKey,
      bubbles: true,
      cancelable: true,
    }),
  );

beforeEach(async () => {
  host = document.createElement("div");
  trigger = document.createElement("button");
  document.body.append(trigger, host);
  trigger.focus();
  root = createRoot(host);
  await act(async () => root.render(<CallsDrawer {...props} />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  trigger.remove();
  vi.clearAllMocks();
});

it("focuses on opening, preserves focus through insight/callback changes, and restores on close", async () => {
  expect(document.activeElement).toBe(close());
  copy().focus();
  const focused = document.activeElement;
  const newClose = vi.fn();
  await act(async () =>
    root.render(
      <CallsDrawer
        {...props}
        insight={extractInsight(null, { verdict: "Report arrived" })}
        readState="ready"
        onClose={newClose}
      />,
    ),
  );
  expect(document.activeElement).toBe(focused);
  await act(async () => key("Escape"));
  expect(newClose).toHaveBeenCalledOnce();
  expect(props.onClose).not.toHaveBeenCalled();
  await act(async () => root.render(null));
  expect(document.activeElement).toBe(trigger);
});

it("wraps Tab in both directions and prevents outside focus or background shortcuts", () => {
  expect(key("Tab", true)).toBe(false);
  expect(document.activeElement).toBe(copy());
  expect(key("Tab")).toBe(false);
  expect(document.activeElement).toBe(close());
  trigger.focus();
  expect(document.activeElement).toBe(close());
  const shortcut = vi.fn();
  window.addEventListener("keydown", shortcut);
  key("/");
  expect(shortcut).not.toHaveBeenCalled();
  window.removeEventListener("keydown", shortcut);
});

it("shows unavailable measurements without invented zeros and offers recovery", async () => {
  await act(async () =>
    root.render(
      <CallsDrawer
        {...props}
        insight={extractInsight(null, { verdict: "Report arrived" })}
        readState="error"
      />,
    ),
  );
  for (const title of [
    "Questions asked",
    "Next steps and commitments",
    "Business details",
    "Concerns",
  ])
    expect(host.querySelector(`[title="${title}"]`)?.textContent).toBe("—");
  await act(async () =>
    buttons()
      .find((button) => button.textContent === "Retry report")!
      .click(),
  );
  expect(props.onRetry).toHaveBeenCalledOnce();
});
