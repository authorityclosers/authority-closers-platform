// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import { ProviderHub } from "./provider-hub";
import {
  agoWords,
  failureCountWords,
  normalizeHealth,
  normalizeHub,
  spendWords,
} from "./provider-hub-data";

const NOW = new Date("2026-10-20T12:00:00Z");

const HUB = normalizeHub({
  providers: [
    {
      id: "gemini",
      name: "Google Gemini",
      kind: "llm",
      kind_label: "Language models",
      blurb: "Gemini Flash and Pro.",
      console: "https://aistudio.google.com",
      pipeline: "ready",
      models: 3,
    },
    {
      id: "sarvam",
      name: "Sarvam",
      kind: "speech",
      kind_label: "Speech to text",
      blurb: "Indian languages.",
      pipeline: "planned",
      models: 0,
    },
  ],
  selected: "gemini",
  models: [],
  catalogue: { source: "OpenRouter" },
  fx: { usd_to_inr: 100 },
});

const RAW_HEALTH = {
  environment: "staging",
  window_days: 30,
  failure_days: 7,
  month: { spent_inr: 412.6, cap_inr: 1500 },
  providers: [
    {
      id: "gemini",
      state: "attention",
      spend: {
        today_inr: 18.4,
        month_inr: 371.2,
        window_inr: 402.9,
        requests: 2140,
      },
      failures: {
        last_7_days: 6,
        last_24_hours: 4,
        latest: {
          at: "2026-10-20T11:00:00Z",
          status: 402,
          feature: "call_data_fast",
          feature_label: "Call data: fast pipeline",
          words:
            "Out of credit, or billing is not set up. Top up in the provider's console.",
          fix: "console",
        },
      },
    },
    {
      id: "sarvam",
      state: "ok",
      spend: { today_inr: 0, month_inr: 41.4, window_inr: 44, requests: 96 },
      failures: null,
    },
    { id: "", state: "ok" },
    {
      id: "odd",
      state: "loud",
      failures: { last_7_days: 1, latest: { at: "x", fix: "pray" } },
    },
  ],
};

const health = normalizeHealth(RAW_HEALTH);

function row(id: string) {
  const value = health.providers[id];
  if (!value) throw new Error(`no health for ${id}`);
  return value;
}

it("reads provider health, with safe defaults for anything unexpected", () => {
  expect(Object.keys(health.providers)).toEqual(["gemini", "sarvam", "odd"]);
  expect(row("odd")).toMatchObject({ state: "idle", spend: null });
  expect(row("odd").failures?.latest?.fix).toBe("engineer");
  expect(health.month).toEqual({ spentInr: 412.6, capInr: 1500 });
  expect(health.environment).toBe("staging");
  expect(spendWords(371.2)).toBe("₹371.20");
  expect(failureCountWords(row("gemini"), 7)).toBe(
    "6 failures in the last 7 days, 4 in the last 24 hours.",
  );
  expect(failureCountWords(row("sarvam"), 7)).toBe(
    "No failures in the last 7 days.",
  );
  expect(failureCountWords(row("odd"), 7)).toBe(
    "1 failure in the last 7 days, none in the last 24 hours.",
  );
});

it("says how long ago in plain words", () => {
  expect(agoWords("2026-10-20T11:59:30Z", NOW)).toBe("just now");
  expect(agoWords("2026-10-20T11:20:00Z", NOW)).toBe("40 min ago");
  expect(agoWords("2026-10-20T11:00:00Z", NOW)).toBe("1 h ago");
  expect(agoWords("2026-10-17T12:00:00Z", NOW)).toBe("3 days ago");
  expect(agoWords("not a date", NOW)).toBe("");
});

it("marks a failing provider in the list and shows the chosen one's health in full", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <ProviderHub hub={HUB} health={health} />,
  );
  const items = [...host.querySelectorAll('[aria-label="Providers"] li')];
  expect(items[0]?.textContent).toContain("Failing today");
  expect(items[0]?.textContent).toContain("₹371.20 this month");
  expect(items[1]?.textContent).not.toContain("Failing today");
  expect(items[1]?.textContent).toContain("₹41.40 this month");

  const here = host.querySelector('[aria-label="Google Gemini in staging"]');
  expect(here?.getAttribute("data-state")).toBe("attention");
  const text = here?.textContent ?? "";
  expect(text).toContain("Here in staging");
  expect(text).toContain("₹18.40");
  expect(text).toContain("2140 requests");
  expect(text).toContain(
    "6 failures in the last 7 days, 4 in the last 24 hours.",
  );
  expect(text).toContain(
    ", in Call data: fast pipeline (HTTP 402): Out of credit",
  );
  expect(
    here?.querySelector('a[href="https://aistudio.google.com"]')?.textContent,
  ).toBe("Top up credit");
  expect(text).toContain("₹412.60 of the ₹1,500.00 cap");
  expect(here?.querySelector('a[href="/ai-spend"]')).not.toBeNull();
});

it("shows no health at all when the server has none to give", () => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<ProviderHub hub={HUB} />);
  expect(host.textContent).not.toContain("Here in");
  expect(host.textContent).not.toContain("this month");
});
