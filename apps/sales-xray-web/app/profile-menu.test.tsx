import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProfileMenu } from "./profile-menu";

vi.mock("./live-data-banner", () => ({ LocalSettingsButton: () => null }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.setItem("ac.xray.submission.v1", "opaque-synthetic-selector");
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function signOut() {
  await act(async () =>
    root.render(<ProfileMenu authenticated accountHref="/calls" />),
  );
  await act(async () =>
    host.querySelector<HTMLButtonElement>("button[aria-expanded]")!.click(),
  );
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "Sign out")!
      .click(),
  );
}
it("discards the private document only after confirmed sign out", async () => {
  const assign = vi
    .spyOn(window.location, "assign")
    .mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
  );
  await signOut();
  expect(assign).toHaveBeenCalledWith("/");
  expect(localStorage.getItem("ac.xray.submission.v1")).toBeNull();
});
it("keeps the current session when sign out cannot be confirmed", async () => {
  const assign = vi
    .spyOn(window.location, "assign")
    .mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(null, { status: 503 })),
  );
  await signOut();
  expect(assign).not.toHaveBeenCalled();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "couldn’t confirm sign out",
  );
  expect(localStorage.getItem("ac.xray.submission.v1")).not.toBeNull();
});
