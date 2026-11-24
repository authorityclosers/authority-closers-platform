// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("./app-router", () => ({ useAppRouter: () => ({ refresh }) }));
const notify = vi.fn();
const dismissNotice = vi.fn();
vi.mock("../notice-center", () => ({
  notify: (...args: unknown[]) => notify(...args),
  dismissNotice: (...args: unknown[]) => dismissNotice(...args),
}));

import { OFFLINE_NOTICE, OfflineWatch } from "./offline-watch";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// v1.96 device polish, lane P: offline, one calm line and the screen stays.
let root: Root;
let host: HTMLDivElement;
let online = true;

beforeEach(() => {
  online = true;
  Object.defineProperty(navigator, "onLine", {
    configurable: true,
    get: () => online,
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  notify.mockReset();
  dismissNotice.mockReset();
  refresh.mockReset();
});

it("says No internet once offline, keeps the screen on a link tap, and reads afresh once back", async () => {
  await act(async () => root.render(<OfflineWatch />));
  expect(notify).not.toHaveBeenCalled();

  online = false;
  await act(async () => window.dispatchEvent(new Event("offline")));
  expect(notify).toHaveBeenLastCalledWith(
    expect.objectContaining({
      id: OFFLINE_NOTICE,
      title: "No internet",
      message: "Showing what was loaded.",
      action: expect.objectContaining({ label: "Try again" }),
    }),
  );

  const link = document.createElement("a");
  link.href = `${window.location.origin}/analysis/calls`;
  document.body.append(link);
  const tap = new MouseEvent("click", { bubbles: true, cancelable: true });
  link.dispatchEvent(tap);
  expect(tap.defaultPrevented).toBe(true);
  link.remove();

  online = true;
  await act(async () => window.dispatchEvent(new Event("online")));
  expect(dismissNotice).toHaveBeenCalledWith(OFFLINE_NOTICE);
  expect(refresh).toHaveBeenCalledTimes(1);

  // Online, links are the app's own business.
  const later = document.createElement("a");
  later.href = `${window.location.origin}/leads?x=1`;
  document.body.append(later);
  const normal = new MouseEvent("click", { bubbles: true, cancelable: true });
  later.addEventListener("click", (event) => event.preventDefault());
  const seen = vi.fn();
  document.addEventListener("click", seen);
  later.dispatchEvent(normal);
  expect(seen).toHaveBeenCalled();
  document.removeEventListener("click", seen);
  later.remove();
});
