// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { ProviderHub, initials } from "./provider-hub";
import {
  NO_MODEL_FILTER,
  contextWords,
  filterModels,
  normalizeHub,
  priceWords,
  rupeeWords,
  searchProviders,
} from "./provider-hub-data";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const RAW = {
  providers: [
    {
      id: "gemini",
      name: "Google Gemini",
      kind: "llm",
      kind_label: "Language models",
      blurb: "Gemini Flash and Pro.",
      console: "https://aistudio.google.com",
      aliases: ["google"],
      pipeline: "ready",
      models: 3,
      pipeline_models: 1,
      cheapest_in_per_million: 0.75,
    },
    {
      id: "groq",
      name: "Groq",
      kind: "llm",
      kind_label: "Language models",
      blurb: "Fast open models.",
      aliases: ["llama"],
      pipeline: "ready",
      models: 0,
    },
    {
      id: "sarvam",
      name: "Sarvam",
      kind: "speech",
      kind_label: "Speech to text",
      blurb: "Indian languages.",
      aliases: ["hindi"],
      pipeline: "planned",
      models: 0,
    },
  ],
  selected: "gemini",
  models: [
    {
      id: "google/gemini-3.8-flash",
      name: "Gemini 3.8 Flash",
      context: 1_048_576,
      inputs: ["text", "audio"],
      audio_in: true,
      json: true,
      usd_in_per_million: 0.75,
      usd_out_per_million: 3.75,
      stages: ["Facts", "Report and coaching"],
      source: "openrouter",
    },
    {
      id: "google/gemma-free",
      name: "Gemma (free)",
      context: 32_000,
      inputs: ["text"],
      free: true,
      usd_in_per_million: 0,
      usd_out_per_million: 0,
      source: "openrouter",
    },
    {
      id: "google/gemini-3.1-pro",
      name: "Gemini 3.1 Pro",
      context: 2_000_000,
      inputs: ["text"],
      json: true,
      usd_in_per_million: 2.5,
      usd_out_per_million: 15,
      source: "openrouter",
    },
  ],
  catalogue: {
    source: "OpenRouter",
    fetched_at: "2026-10-20T12:00:00Z",
    problem: null,
  },
  fx: { usd_to_inr: 100 },
};

it("reads the hub, searches providers and filters models", () => {
  const hub = normalizeHub(RAW);
  expect(hub.providers[0]).toMatchObject({
    pipeline: "ready",
    cheapestInPerMillion: 0.75,
  });
  expect(hub.usdToInr).toBe(100);
  expect(searchProviders(hub.providers, "hindi").map((p) => p.id)).toEqual([
    "sarvam",
  ]);
  expect(searchProviders(hub.providers, "", "speech").map((p) => p.id)).toEqual(
    ["sarvam"],
  );
  expect(searchProviders(hub.providers, "lla").map((p) => p.id)).toEqual([
    "groq",
  ]);
  const cheapest = filterModels(hub.models, {
    ...NO_MODEL_FILTER,
    cheapest: true,
  });
  expect(cheapest.map((m) => m.id)).toEqual([
    "google/gemma-free",
    "google/gemini-3.8-flash",
    "google/gemini-3.1-pro",
  ]);
  expect(
    filterModels(hub.models, { ...NO_MODEL_FILTER, audio: true }),
  ).toHaveLength(1);
  expect(
    filterModels(hub.models, { ...NO_MODEL_FILTER, json: true }),
  ).toHaveLength(2);
  expect(
    filterModels(hub.models, { ...NO_MODEL_FILTER, runsHere: true })[0].id,
  ).toBe("google/gemini-3.8-flash");
  expect(
    filterModels(hub.models, { ...NO_MODEL_FILTER, query: "pro" }),
  ).toHaveLength(1);
  // Pipeline models come first by default.
  expect(
    filterModels(hub.models, NO_MODEL_FILTER)[0].stages.length,
  ).toBeGreaterThan(0);
  const flash = hub.models[0];
  expect(priceWords(flash)).toBe("$0.75 in · $3.75 out per 1M tokens");
  expect(rupeeWords(flash, 100)).toBe("₹75.00 · ₹375.00");
  expect(priceWords(hub.models[1])).toBe("Free");
  expect(contextWords(1_048_576)).toBe("1M");
  expect(contextWords(32_000)).toBe("32K");
  expect(contextWords(null)).toBe("–");
  expect(
    priceWords({
      ...flash,
      usdPerAudioHour: 0.22,
      usdInPerMillion: null,
      usdOutPerMillion: null,
    }),
  ).toBe("$0.22 an audio hour");
});

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
});

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const button = (text: string) =>
  [...host.querySelectorAll("button")].find(
    (item) => item.textContent === text,
  )!;

it("filters providers as you type and models by chip, with prices and stages", async () => {
  await act(async () => root.render(<ProviderHub hub={normalizeHub(RAW)} />));
  const names = () =>
    [...host.querySelectorAll('[aria-label="Providers"] li strong')].map(
      (n) => n.textContent,
    );
  expect(names()).toEqual(["Google Gemini", "Groq", "Sarvam"]);
  expect(
    host.querySelector('a[aria-current="true"]')?.getAttribute("href"),
  ).toBe("/sales-xray/providers?tab=hub&provider=gemini");
  await type(
    host.querySelector<HTMLInputElement>(
      'input[aria-label="Search providers"]',
    )!,
    "sar",
  );
  expect(names()).toEqual(["Sarvam"]);
  await type(
    host.querySelector<HTMLInputElement>(
      'input[aria-label="Search providers"]',
    )!,
    "zzz",
  );
  expect(host.textContent).toContain("No provider matches");
  // The chosen provider's models: price in dollars and rupees, stages it runs here.
  expect(host.textContent).toContain("$0.75 in · $3.75 out per 1M tokens");
  expect(host.textContent).toContain("Report and coaching");
  expect(host.textContent).toContain("Showing 3 of 3");
  await act(async () => button("Hears audio").click());
  expect(host.textContent).toContain("Showing 1 of 3");
  expect(button("Hears audio").getAttribute("aria-pressed")).toBe("true");
  expect(host.textContent).toContain("can call this provider today");
  expect(
    host.querySelector('a[href="https://aistudio.google.com"]'),
  ).not.toBeNull();
});

it("asks for a provider when none is chosen and says when the catalogue is down", async () => {
  const raw = {
    ...RAW,
    selected: null,
    models: [],
    catalogue: {
      source: "OpenRouter",
      problem: "OpenRouter's catalogue could not be read just now.",
    },
  };
  await act(async () => root.render(<ProviderHub hub={normalizeHub(raw)} />));
  expect(host.textContent).toContain("Choose a provider to see its models");
  expect(host.textContent).toContain("could not be read just now");
  expect(host.querySelector('a[aria-current="true"]')).toBeNull();
});

it("gives every provider two distinct letters", () => {
  expect(initials("OpenRouter")).toBe("OR");
  expect(initials("OpenAI")).toBe("OA");
  expect(initials("Google Gemini")).toBe("GG");
  expect(initials("Groq")).toBe("GR");
  expect(initials("DeepSeek")).toBe("DS");
  expect(initials("Custom (OpenAI-compatible)")).toBe("CU");
});
