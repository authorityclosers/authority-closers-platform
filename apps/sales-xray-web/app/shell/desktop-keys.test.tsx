import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const tracked = vi.hoisted(() => [] as { feature: string }[]);
vi.mock("../telemetry", () => ({
  track: (_name: string, payload: { feature: string }) => tracked.push(payload),
}));

import { DesktopKeys, goPlace } from "./desktop-keys";
import { OPEN_ADD_EVENT } from "./shell-store";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let shell: HTMLDivElement;
let computer = true;
const push = vi.fn();

beforeEach(async () => {
  computer = true;
  tracked.length = 0;
  push.mockReset();
  window.matchMedia = ((query: string) => ({
    matches: computer,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
  shell = document.createElement("div");
  shell.setAttribute("data-lightbox-shell", "");
  shell.setAttribute("data-authenticated", "true");
  document.body.append(shell);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <AppRouterContext.Provider value={{ push } as never}>
        <DesktopKeys />
      </AppRouterContext.Provider>,
    ),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  shell.remove();
  document.body.innerHTML = "";
});

const press = async (key: string, target: EventTarget = document.body) =>
  act(async () => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  });

// Owner, 20 Nov 2026 ("Learn how Vitals OS is so great on PC"): keys on a
// computer, taught on screen by ?.
it("? lists the keys and Esc closes the list", async () => {
  await press("?");
  const sheet = document.querySelector('[role="dialog"]');
  expect(sheet?.textContent).toContain("Keyboard shortcuts");
  expect(sheet?.textContent).toContain("Go to Leads");
  expect(sheet?.textContent).toContain("Add a lead, a call or a task");
  expect(tracked).toContainEqual({ feature: "key_help" });
  await press("Escape");
  expect(document.querySelector('[role="dialog"]')).toBeNull();
});

it("G then L goes to Leads, G then S to Settings", async () => {
  await press("g");
  await press("l");
  expect(push).toHaveBeenLastCalledWith("/leads");
  await press("g");
  await press("s");
  expect(push).toHaveBeenLastCalledWith("/settings");
  expect(tracked).toContainEqual({ feature: "key_go_l" });
  expect(goPlace("C")?.href).toBe("/analysis/calls");
});

it("N opens the + sheet and / opens search", async () => {
  const add = vi.fn();
  const search = vi.fn();
  window.addEventListener(OPEN_ADD_EVENT, add);
  const onSearch = (event: KeyboardEvent) => {
    if (event.ctrlKey && event.key === "k") search();
  };
  window.addEventListener("keydown", onSearch);
  await press("n");
  await press("/");
  expect(add).toHaveBeenCalledTimes(1);
  expect(search).toHaveBeenCalledTimes(1);
  window.removeEventListener(OPEN_ADD_EVENT, add);
  window.removeEventListener("keydown", onSearch);
});

it("leaves the keys alone while someone types, a sheet is up, or on a phone", async () => {
  const input = document.createElement("input");
  document.body.append(input);
  await press("g", input);
  await press("l", input);
  expect(push).not.toHaveBeenCalled();

  const sheet = document.createElement("div");
  sheet.setAttribute("role", "dialog");
  document.body.append(sheet);
  await press("?");
  expect(document.querySelector("[data-desktop-keys]")).toBeNull();
  sheet.remove();

  computer = false;
  await press("?");
  expect(document.querySelector("[data-desktop-keys]")).toBeNull();
  expect(tracked).toEqual([]);
});
