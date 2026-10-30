// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { WorkspaceAccessContext } from "../workspace-access";
import { CAPTURE_SETUP_ATTRIBUTE } from "./capture-setup-rules";
import { RecordingCheck } from "./recording-check";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 30 Oct 2026 (fix 5): "if a connected call has no recording file after
// 2 minutes, show the rep a banner with the steps to turn on automatic call
// recording in their phone's dialer (Xiaomi/HyperOS steps first)".

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  window.sessionStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute(CAPTURE_SETUP_ATTRIBUTE);
});

async function mount(calls: number) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            schema: "sales-xray-missing-recordings/1",
            calls,
            latest_at: calls ? "2026-10-30T09:00:00+00:00" : null,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    ),
  );
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: "p", sessionId: "s", tenantId: "t" },
          workspaces: [],
          retry: () => {},
        }}
      >
        <RecordingCheck />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  for (let i = 0; i < 8; i++) await act(async () => await Promise.resolve());
}

it("shows Xiaomi's steps first when a call has no recording, until Done", async () => {
  await mount(2);
  expect(host.textContent).toContain("2 calls today have no recording");
  expect(host.textContent).toContain("On Xiaomi, Redmi and POCO (HyperOS):");
  expect(host.textContent).toContain(
    "Turn on Record calls automatically, for All numbers.",
  );
  // In a browser there is no Phone app to open, only the steps.
  expect(host.textContent).not.toContain("Open call recording settings");
  const done = [...host.querySelectorAll("button")].find(
    (item) => item.textContent === "Done",
  );
  await act(async () => done?.click());
  expect(host.querySelector("aside")).toBeNull();
});

it("says nothing when every call has its recording, or over a setup screen", async () => {
  await mount(0);
  expect(host.querySelector("aside")).toBeNull();
  await act(async () => root.unmount());
  root = createRoot(host);
  document.documentElement.setAttribute(CAPTURE_SETUP_ATTRIBUTE, "");
  await mount(1);
  expect(host.querySelector("aside")).toBeNull();
});
