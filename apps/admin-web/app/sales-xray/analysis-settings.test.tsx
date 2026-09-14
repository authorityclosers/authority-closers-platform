// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AnalysisSettingsPanel } from "./analysis-settings";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const state = {
  revision: 0,
  settings: {
    c4_max_requests: 64,
    c4_max_completion_tokens: 1400,
    c5_max_completion_tokens: 3200,
    c5_output_profile: "detailed",
  },
  bounds: {
    c4_max_requests: { min: 1, max: 64 },
    c4_max_completion_tokens: { min: 256, max: 4000 },
    c5_max_completion_tokens: { min: 256, max: 8000 },
    c5_output_profile: { values: ["standard", "detailed"] },
  },
  created_at: null,
  message: "These limits apply to new plans.",
};

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("loads the bounded controls and saves a real future-plan revision", async () => {
  const fetcher = vi.fn(async (_url: string, init: RequestInit) => {
    if (init.method === "POST") {
      return json({
        ...state,
        revision: 1,
        settings: JSON.parse(init.body as string).settings,
      });
    }
    return json(state);
  });
  vi.stubGlobal("fetch", fetcher);
  await act(async () => root.render(createElement(AnalysisSettingsPanel)));
  const profile = host.querySelector<HTMLSelectElement>(
    '[aria-label="C5 output profile"]',
  );
  expect(profile).toBeTruthy();
  await act(async () => {
    profile!.value = "standard";
    profile!.dispatchEvent(new Event("change", { bubbles: true }));
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) =>
        button.textContent?.includes("Save future plan limits"),
      )!
      .click();
  });
  const post = fetcher.mock.calls.find(([, init]) => init.method === "POST");
  expect(post).toBeTruthy();
  expect(JSON.parse(post![1].body as string)).toMatchObject({
    expected_revision: 0,
    settings: { c5_output_profile: "standard" },
  });
  expect(new Headers(post![1].headers).get("Idempotency-Key")).toBeTruthy();
  expect(host.textContent).toContain("revision 1");
});
