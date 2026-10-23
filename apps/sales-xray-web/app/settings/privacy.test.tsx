import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { telemetry } from "../telemetry";
import { PrivacySettings, type AnalyticsPreferences } from "./privacy";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let calls: Array<{ url: string; method: string; body: unknown }>;
let state: AnalyticsPreferences;

const preferences = (
  extra: Partial<AnalyticsPreferences> = {},
): AnalyticsPreferences => ({
  notice: {
    version: "sx-product-analytics-2026-10-24-v1",
    paragraphs: ["Sales X-Ray records how its app is used.", "This is on."],
  },
  collecting: true,
  sandbox: false,
  you: { enabled: true, changed_at: null },
  workspace: { enabled: true, changed_at: null, can_change: false },
  ...extra,
});

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  calls = [];
  state = preferences();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, method, body });
      if (method === "PUT") {
        const enabled = (body as { enabled: boolean }).enabled;
        state = url.endsWith("/you")
          ? { ...state, you: { enabled, changed_at: "2026-10-24T01:00:00Z" } }
          : {
              ...state,
              workspace: { ...state.workspace, enabled },
            };
        state = {
          ...state,
          collecting: state.you.enabled && state.workspace.enabled,
        };
      }
      return Response.json(state);
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const render = async () => {
  await act(async () => root.render(<PrivacySettings />));
};
const switches = () => [
  ...host.querySelectorAll<HTMLButtonElement>('button[role="switch"]'),
];
const press = async (button: HTMLElement) => {
  await act(async () => button.click());
};
const inSheet = (name: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("dialog button")].find(
    (button) => button.textContent === name,
  )!;

it("shows your switch and the notice's words; only managers get the workspace's", async () => {
  await render();
  expect(switches().map((item) => item.getAttribute("aria-label"))).toEqual([
    "Help improve Sales X-Ray",
  ]);
  expect(host.textContent).toContain(
    "Sales X-Ray records how its app is used.",
  );
  expect(host.querySelector('a[href="/privacy"]')).not.toBeNull();

  await act(async () => root.unmount());
  root = createRoot(host);
  state = preferences({
    workspace: { enabled: true, changed_at: null, can_change: true },
  });
  await render();
  expect(switches().map((item) => item.getAttribute("aria-label"))).toEqual([
    "Help improve Sales X-Ray",
    "Usage analytics for this workspace",
  ]);
});

it("turns yours off after asking, saves it and has the page ask again what it may send", async () => {
  const refresh = vi.spyOn(telemetry, "refresh");
  await render();
  await press(switches()[0]!);
  expect(calls.filter((call) => call.method === "PUT")).toEqual([]);
  await press(inSheet("Turn off"));
  expect(calls.at(-1)).toEqual({
    url: "/v1/telemetry/preferences/you",
    method: "PUT",
    body: { enabled: false },
  });
  expect(refresh).toHaveBeenCalled();
  expect(switches()[0]?.getAttribute("aria-checked")).toBe("false");
  expect(host.textContent).toContain(
    "Off: nothing about how you use the app is recorded",
  );
});

it("says when the workspace is off or a sandbox", async () => {
  state = preferences({
    collecting: false,
    workspace: { enabled: false, changed_at: null, can_change: false },
  });
  await render();
  expect(host.textContent).toContain("An owner or admin has turned usage");
  await act(async () => root.unmount());
  root = createRoot(host);
  state = preferences({ collecting: false, sandbox: true });
  await render();
  expect(switches()).toEqual([]);
  expect(host.textContent).toContain("This is a sandbox workspace.");
});
