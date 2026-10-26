import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const felt = vi.fn();
vi.mock("../ui/haptics", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  haptic: (kind: string) => felt(kind),
  tick: () => felt("tap"),
}));

import type { AutoAnalysis } from "./auto-analysis-client";
import { AutoAnalysisPanel } from "./auto-analysis-panel";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Owner, 26 Oct 2026: a seller agrees once to have their calls analysed as they
// arrive. The words come from the server; nothing is on until Turn on.
const WORDS =
  "When I record a sales call with Sales X-Ray in Fictional Traders, the customer knows the call is recorded.";
const NOTICE = {
  version: "auto-analysis-2026-10-26",
  language: "en" as const,
  title: "Analyse my calls automatically",
  text: WORDS,
  policy_sha256: "c".repeat(64),
};
const TERMS = {
  schema: "ac.sales-xray.private-upload-consent/1",
  max_cost_paise: 0,
  policy_sha256: "d".repeat(64),
  title: "Upload your call and get your report",
  description: "Upload only a call you have permission to analyse.",
  privacy_details:
    "Fictional providers receive the recording only to transcribe it.",
  maximum_file_bytes: 100_000_000,
  maximum_call_seconds: 3600,
  retention_days: 30,
};

let root: Root;
let host: HTMLDivElement;
let state: AutoAnalysis;
let posts: Array<{ body: unknown; key: string | null }>;

const view = (extra: Partial<AutoAnalysis> = {}): AutoAnalysis => ({
  schema: "sales-xray-auto-analysis/1",
  state: "ask",
  can_start: false,
  since: null,
  terms_sha256: null,
  ai_level: "full",
  notice: NOTICE,
  pending_languages: ["hi", "mr"],
  ...extra,
});

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  posts = [];
  state = view();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith("/upload-policy")) return Response.json(TERMS);
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { decision: string };
        posts.push({
          body,
          key: new Headers(init.headers).get("Idempotency-Key"),
        });
        state =
          body.decision === "granted"
            ? view({
                state: "on",
                can_start: true,
                terms_sha256: TERMS.policy_sha256,
              })
            : view({ state: "off" });
      }
      return Response.json(state);
    }),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  felt.mockClear();
});

// Reads and saves settle (fetch, then its JSON).
const settle = () =>
  act(async () => {
    for (let i = 0; i < 3; i += 1)
      await new Promise((resolve) => setTimeout(resolve, 0));
  });
const render = async () => {
  await act(async () => root.render(<AutoAnalysisPanel />));
  await settle();
};
const press = async (button: HTMLElement) => {
  await act(async () => button.click());
  await settle();
};
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent === name,
  )!;
const sheetText = () => document.querySelector("dialog")?.textContent ?? "";

it("turns on only from the sheet, with the server's words and the terms shown", async () => {
  await render();
  // Not on: no switch to flip, only Turn on.
  expect(host.querySelector('button[role="switch"]')).toBeNull();
  expect(host.textContent).toContain("Off: each call waits for your tap.");
  await press(button("Turn on", host));
  expect(sheetText()).toContain(WORDS);
  expect(sheetText()).toContain(TERMS.privacy_details);
  expect(posts).toEqual([]);

  // "Not now" records nothing.
  await press(button("Not now"));
  expect(posts).toEqual([]);

  await press(button("Turn on", host));
  await press(button("Turn on", document.querySelector("dialog")!));
  expect(posts).toHaveLength(1);
  expect(posts[0]?.body).toEqual({
    decision: "granted",
    policy_sha256: NOTICE.policy_sha256,
    upload_policy_sha256: TERMS.policy_sha256,
    language: "en",
  });
  expect(posts[0]?.key).toMatch(/^[0-9a-f-]{36}$/);
  expect(felt).toHaveBeenCalledWith("success");
  const on = host.querySelector<HTMLButtonElement>('button[role="switch"]')!;
  expect(on.getAttribute("aria-checked")).toBe("true");
  expect(host.textContent).toContain(
    "On: each call you record here is analysed as it arrives",
  );
});

it("turns off after asking, and says when the AI level holds calls", async () => {
  state = view({ state: "on", can_start: false, ai_level: "off" });
  await render();
  expect(host.textContent).toContain("AI on calls is off for you");
  await press(host.querySelector<HTMLButtonElement>('button[role="switch"]')!);
  expect(posts).toEqual([]);
  expect(sheetText()).toContain(
    "Calls you record from now on wait for your tap.",
  );
  await press(button("Turn off"));
  expect(posts.map((post) => post.body)).toEqual([{ decision: "withdrawn" }]);
  expect(host.textContent).toContain("Off: each call waits for your tap.");
});

it("shows nothing in a personal workspace", async () => {
  state = {
    schema: "sales-xray-auto-analysis/1",
    state: "unavailable",
    can_start: false,
  };
  await render();
  expect(host.textContent).toBe("");
});
