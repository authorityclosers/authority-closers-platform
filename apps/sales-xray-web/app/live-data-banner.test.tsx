import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { LiveDataBanner, LocalSettingsButton } from "./live-data-banner";

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  window.localStorage.clear();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

it("hides the banner by default and keeps live-data details in Settings", async () => {
  await act(async () => root.render(<LiveDataBanner><LocalSettingsButton /></LiveDataBanner>));
  expect(container.querySelector('[role="note"]')).toBeNull();
  const dialog = container.querySelector("dialog")!;
  expect(dialog.open).toBe(false);
  await act(async () => container.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')!.click());
  expect(dialog.open).toBe(true);
  expect(dialog.textContent).toContain("live AC data");
  expect(dialog.textContent).toContain("affects real data");
  expect(
    container.querySelector<HTMLAnchorElement>(
      'a[href="https://admin.authorityclosers.com/sales-xray/settings"]',
    ),
  ).not.toBeNull();
  await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Close settings"]')!.click());
  expect(dialog.open).toBe(false);
});

function shortcut(target: EventTarget = window, options: KeyboardEventInit = {}) {
  target.dispatchEvent(new KeyboardEvent("keydown", {
    key: "b", ctrlKey: true, altKey: true, bubbles: true, cancelable: true, ...options,
  }));
}

it("toggles with Ctrl+Alt+B and remembers both choices across remounts", async () => {
  await act(async () => root.render(<LiveDataBanner />));
  await act(async () => shortcut());
  expect(container.querySelector('[role="note"]')).not.toBeNull();
  await act(async () => root.render(null));
  await act(async () => root.render(<LiveDataBanner />));
  expect(container.querySelector('[role="note"]')).not.toBeNull();
  await act(async () => shortcut());
  await act(async () => root.render(null));
  await act(async () => root.render(<LiveDataBanner />));
  expect(container.querySelector('[role="note"]')).toBeNull();
});

it("supports the Settings checkbox and banner dismiss button", async () => {
  await act(async () => root.render(<LiveDataBanner />));
  const toggle = container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
  await act(async () => toggle.click());
  expect(container.querySelector('[role="note"]')).not.toBeNull();
  await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Hide live data banner"]')!.click());
  expect(toggle.checked).toBe(false);
  expect(container.querySelector('[role="note"]')).toBeNull();
});

it("ignores shortcut repeats and typing in editable fields", async () => {
  await act(async () => root.render(<LiveDataBanner><input aria-label="Email" /></LiveDataBanner>));
  await act(async () => shortcut(window, { repeat: true }));
  await act(async () => shortcut(container.querySelector("input")!));
  expect(container.querySelector('[role="note"]')).toBeNull();
});

it("does not expose local Settings outside the live development layout", async () => {
  await act(async () => root.render(<LocalSettingsButton />));
  expect(container.querySelector("button")).toBeNull();
});
