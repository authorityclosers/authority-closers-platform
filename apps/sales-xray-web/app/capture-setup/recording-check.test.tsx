// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const route = vi.hoisted(() => ({ path: "/leads", pushed: [] as string[] }));
vi.mock("next/navigation", () => ({
  usePathname: () => route.path,
  useRouter: () => ({ push: (to: string) => route.pushed.push(to) }),
}));
const notices = vi.hoisted(() => ({
  shown: [] as Array<Record<string, unknown>>,
  dismissed: [] as string[],
}));
vi.mock("../notice-center", () => ({
  notify: (notice: Record<string, unknown>) => notices.shown.push(notice),
  dismissNotice: (id: string) => notices.dismissed.push(id),
}));

import type { Notice } from "../notice-center";
import { WorkspaceAccessContext } from "../workspace-access";
import { CAPTURE_SETUP_ATTRIBUTE } from "./capture-setup-rules";
import { RECORDING_NOTICE, RecordingCheck } from "./recording-check";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 30 Oct 2026 (fix 5): "if a connected call has no recording file after
// 2 minutes, show the rep a banner with the steps to turn on automatic call
// recording in their phone's dialer (Xiaomi/HyperOS steps first)". Persona QA
// and the test robot, 31 Oct 2026: a corner card, never on Home, one slim line
// after the day's first sight, closed for the day; the same calls as Tried.

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  window.localStorage.clear();
  notices.shown.length = 0;
  notices.dismissed.length = 0;
  route.pushed.length = 0;
  route.path = "/leads";
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute(CAPTURE_SETUP_ATTRIBUTE);
});

async function mount(calls: number, tried = calls ? 54 : 0) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            schema: "sales-xray-missing-recordings/1",
            calls,
            tried,
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

const last = () => notices.shown.at(-1) as Notice | undefined;

it("shows the day's first card in full, then one slim line that opens again", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  await mount(28);
  expect(host.innerHTML).toBe("");
  let card = last();
  expect(card?.id).toBe(RECORDING_NOTICE);
  expect(card?.title).toBe("28 calls today have no recording");
  expect(card?.message).toContain("record automatically, all numbers");
  expect(card?.action?.label).toBe("See which");
  card?.action?.run();
  expect(route.pushed).toEqual(["/calls"]);
  // After a while the card becomes one line, for the rest of the day too.
  await act(async () => {
    vi.advanceTimersByTime(13_000);
  });
  card = last();
  expect(card?.title).toBe("28 calls not recorded");
  expect(card?.message).toBeUndefined();
  expect(card?.slim).toBe(true);
  expect(card?.action?.label).toBe("Details");
  await act(async () => card?.action?.run());
  expect(last()?.title).toBe("28 calls today have no recording");
});

it("closing it hides it for the rest of the day", async () => {
  await mount(3);
  await act(async () => last()?.onDismiss?.());
  expect(window.localStorage.getItem("sx-recording-check-day")).toMatch(
    /:closed$/,
  );
  const before = notices.shown.length;
  await act(async () => root.unmount());
  root = createRoot(host);
  await mount(3);
  expect(notices.shown.length).toBe(before);
});

it("never shows on Home, whose Tried row already says it", async () => {
  route.path = "/dashboard";
  await mount(28);
  expect(notices.shown).toEqual([]);
  expect(notices.dismissed).toContain(RECORDING_NOTICE);
});

it("never shows when Home tried nothing today, or every call has its recording", async () => {
  await mount(2, 0);
  expect(notices.shown).toEqual([]);
  await act(async () => root.unmount());
  root = createRoot(host);
  await mount(0);
  expect(notices.shown).toEqual([]);
});

it("never shows over a setup screen", async () => {
  document.documentElement.setAttribute(CAPTURE_SETUP_ATTRIBUTE, "");
  await mount(1);
  expect(notices.shown).toEqual([]);
});
