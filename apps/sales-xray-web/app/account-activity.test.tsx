// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/account",
}));
vi.mock("./acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => children,
}));

import { AccountView } from "./account-view";
import { AccountSettings } from "./account-settings";
import { WorkspaceAccessProvider } from "./workspace-access";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const SUMMARY_PATH = "/v1/conversation/acquisition/submissions/summary";
const ACTIVITY_PATH = "/v1/conversation/acquisition/activity";
const SUMMARY = { total: 9, completed: 5, processing: 2, needs_attention: 1 };
const PROFILE = {
  name: "Asha Rao",
  email: "asha@example.invalid",
  phone_number_e164: null,
  phone_verified: false,
  profile_complete: true,
  revision: 1,
};

function activity(analysed = 5, previous = 2) {
  return {
    timezone: "Asia/Kolkata",
    days: Array.from({ length: 30 }, (_, index) => ({
      date: `2026-09-${String(index + 1).padStart(2, "0")}`,
      analysed: index === 29 ? analysed : 0,
      analysed_seconds: index === 29 ? analysed * 60 : 0,
    })),
    analysed_last_30_days: analysed,
    analysed_previous_30_days: previous,
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

let host: HTMLDivElement;
let root: Root;
let calls: { path: string; init: RequestInit }[];
let handlers: Record<string, () => Response | Promise<Response>>;

async function flush() {
  await act(async () => {
    for (let i = 0; i < 10; i++) await Promise.resolve();
  });
}

async function render(
  personId = "person-a",
  tenantId = "tenant-a",
  dialog = false,
) {
  await act(async () =>
    root.render(
      <WorkspaceAccessProvider
        value={{
          authenticated: true,
          status: "ready",
          context: { personId, sessionId: "session-a", tenantId },
          retry: () => {},
        }}
      >
        {dialog ? <AccountSettings variant="dialog" /> : <AccountView />}
      </WorkspaceAccessProvider>,
    ),
  );
  await flush();
}

async function openUsage() {
  await act(async () =>
    host.querySelector<HTMLButtonElement>("#account-tab-usage")!.click(),
  );
  await flush();
  return host.querySelector<HTMLElement>("#account-pane-usage")!;
}

function section(label: string) {
  return host.querySelector<HTMLElement>(`section[aria-label="${label}"]`)!;
}

function values(label: string) {
  return [...section(label).querySelectorAll("span")]
    .map((node) => node.textContent)
    .filter((text) => /^\d+$/.test(text ?? ""));
}

beforeEach(() => {
  window.history.replaceState({}, "", "/account");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  calls = [];
  handlers = {
    "/v1/me/sales-xray-profile": () => json(PROFILE),
    "/v1/conversation/acquisition/session": () =>
      json({
        allowance: {
          allowance_seconds: 3600,
          committed_seconds: 900,
          available_seconds: 2700,
        },
      }),
    [SUMMARY_PATH]: () => json(SUMMARY),
    [ACTIVITY_PATH]: () => json(activity()),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo, init: RequestInit = {}) => {
      const path = String(input).split("?")[0];
      calls.push({ path, init });
      return Promise.resolve(handlers[path]?.() ?? json({}, 404));
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("loads real activity only when Usage opens and preserves the balance and destination", async () => {
  await render();
  expect(
    calls.some(({ path }) => path === SUMMARY_PATH || path === ACTIVITY_PATH),
  ).toBe(false);
  const pane = await openUsage();
  expect(pane.hidden).toBe(false);
  expect(pane.querySelector("h2")?.textContent).toBe("Usage & activity");
  expect(values("Saved call counts")).toEqual(["9", "5", "2", "1"]);
  expect(values("Recent analysis activity")).toEqual(["5", "2"]);
  expect(section("Recent analysis activity").textContent).toContain(
    "India time · +3 vs previous 30 days",
  );
  expect(pane.textContent).toContain("45 of 60 min available");
  expect(pane.querySelector('a[href="/dashboard"]')?.textContent).toBe(
    "Open Dashboard",
  );
  expect(window.location.hash).toBe("#usage");
  expect(calls.every(({ init }) => (init.method ?? "GET") === "GET")).toBe(
    true,
  );
});

it("shows confirmed zero counts, with no invented trend", async () => {
  handlers[SUMMARY_PATH] = () =>
    json({ total: 0, completed: 0, processing: 0, needs_attention: 0 });
  handlers[ACTIVITY_PATH] = () => json(activity(0, 0));
  await render();
  await openUsage();
  expect(values("Saved call counts")).toEqual(["0", "0", "0", "0"]);
  expect(values("Recent analysis activity")).toEqual(["0", "0"]);
  expect(section("Recent analysis activity").textContent).not.toContain(
    "vs previous",
  );
});

it("keeps a pending read separate from zero while the other activity read works", async () => {
  handlers[SUMMARY_PATH] = () => new Promise<Response>(() => {});
  await render();
  await openUsage();
  expect(
    section("Saved call counts").querySelector('[role="status"]')?.textContent,
  ).toContain("Loading saved call counts");
  expect(values("Saved call counts")).toEqual([]);
  expect(values("Recent analysis activity")).toEqual(["5", "2"]);
});

it.each([404, 422])(
  "labels an unserved activity route (%i) without inventing zero counts",
  async (status) => {
    handlers[ACTIVITY_PATH] = () => json({}, status);
    await render();
    await openUsage();
    expect(section("Recent analysis activity").textContent).toContain(
      "not available yet",
    );
    expect(
      section("Recent analysis activity").querySelector('[role="alert"]'),
    ).toBeNull();
    expect(values("Recent analysis activity")).toEqual([]);
    expect(values("Saved call counts")).toEqual(["9", "5", "2", "1"]);
  },
);

it.each([401, 403, 503])(
  "keeps denied/failed activity (%i) separate from zeros and retries",
  async (status) => {
    handlers[ACTIVITY_PATH] = () => json({}, status);
    await render();
    await openUsage();
    expect(
      section("Recent analysis activity").querySelector('[role="alert"]')
        ?.textContent,
    ).toContain("could not be loaded");
    expect(values("Recent analysis activity")).toEqual([]);
    expect(values("Saved call counts")).toEqual(["9", "5", "2", "1"]);
    handlers[ACTIVITY_PATH] = () => json(activity());
    await act(async () =>
      section("Recent analysis activity")
        .querySelector<HTMLButtonElement>("button")!
        .click(),
    );
    await flush();
    expect(values("Recent analysis activity")).toEqual(["5", "2"]);
    expect(calls.filter(({ path }) => path === ACTIVITY_PATH)).toHaveLength(2);
  },
);

it("rejects malformed counts while showing successful recent activity", async () => {
  handlers[SUMMARY_PATH] = () => json({ ...SUMMARY, completed: "5" });
  await render();
  await openUsage();
  expect(
    section("Saved call counts").querySelector('[role="alert"]'),
  ).not.toBeNull();
  expect(values("Saved call counts")).toEqual([]);
  expect(values("Recent analysis activity")).toEqual(["5", "2"]);
});

it.each(["account", "workspace"])(
  "aborts old %s reads and ignores late responses after identity changes",
  async (boundary) => {
    let resolveOld!: (response: Response) => void;
    handlers[SUMMARY_PATH] = () =>
      new Promise<Response>((resolve) => {
        resolveOld = resolve;
      });
    await render();
    await openUsage();
    const oldSignal = calls.find(({ path }) => path === SUMMARY_PATH)!.init
      .signal!;
    handlers[SUMMARY_PATH] = () =>
      json({ total: 1, completed: 1, processing: 0, needs_attention: 0 });
    await render(
      boundary === "account" ? "person-b" : "person-a",
      boundary === "workspace" ? "tenant-b" : "tenant-a",
    );
    expect(oldSignal.aborted).toBe(true);
    expect(values("Saved call counts")).toEqual(["1", "1", "0", "0"]);
    await act(async () => resolveOld(json(SUMMARY)));
    await flush();
    expect(values("Saved call counts")).toEqual(["1", "1", "0", "0"]);
  },
);

it("honours the existing dialog Usage deep link", async () => {
  window.history.replaceState({}, "", "/analysis/calls#settings-usage");
  await act(async () =>
    root.render(<AccountSettings variant="dialog" hashPrefix="settings-" />),
  );
  await flush();
  expect(
    host
      .querySelector<HTMLButtonElement>("#account-tab-usage")
      ?.getAttribute("aria-selected"),
  ).toBe("true");
  expect(values("Saved call counts")).toEqual(["9", "5", "2", "1"]);
  expect(window.location.hash).toBe("#settings-usage");
});
