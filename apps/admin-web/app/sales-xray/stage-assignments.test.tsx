// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";

import { normalizeRegistry } from "../settings/registry-data";
import { normalizeMetrics } from "../usage/cost-data";
import {
  estimatePerMinute,
  modelPrices,
  rupeesPerMinute,
} from "./provider-hub-data";
import { StageAssignments } from "./stage-assignments";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const CALL_DATA = "/v1/admin/call-data";

const settings = normalizeRegistry({
  settings: [
    {
      id: "call_data.fast.model",
      area: "call-data",
      label: "Fast read: model",
      kind: "enum",
      read: {
        path: CALL_DATA,
        value: "/config/fast/model",
        revision: "/revision",
      },
      write: {
        method: "PUT",
        path: `${CALL_DATA}/settings`,
        body: { expected_revision: "$revision", config: "$merged" },
        idempotency_key: false,
        merge: { container: "/config", key: ["fast", "model"] },
        needs_reason: false,
      },
      options: [],
      options_from: { list: "/models", value: "model", label: "label" },
    },
  ],
}).settings;

const MODELS = [
  {
    model: "model-a",
    label: "Model A",
    input_usd_per_million: "0.30",
    output_usd_per_million: "2.50",
  },
  {
    model: "model-b",
    label: "Model B",
    input_usd_per_million: "0.25",
    output_usd_per_million: "2.00",
  },
];

const answers = {
  [CALL_DATA]: {
    revision: 4,
    config: { fast: { model: "model-a" } },
    models: MODELS,
  },
};

const prices = modelPrices(
  MODELS.map((item) => ({
    model: item.model,
    label: item.label,
    inputUsd: item.input_usd_per_million,
    outputUsd: item.output_usd_per_million,
  })),
);

const metrics = normalizeMetrics({
  window: { days: 14 },
  here: "dev",
  fx: { usd_to_inr: 88 },
  routes: [
    {
      environment: "staging",
      stage: "CDF",
      provider: "other",
      model: "old-model",
    },
    { environment: "dev", stage: "CDF", provider: "gemini", model: "model-a" },
    { environment: "dev", stage: "C2", provider: "sarvam", model: "speech-1" },
  ],
  overview: {
    audio_minutes: 100,
    by_stage: [
      {
        stage: "CDF",
        per_minute: 0.05,
        input_tokens: 200_000,
        output_tokens: 20_000,
      },
      { stage: "C2", per_minute: 0.5 },
    ],
  },
});

function render(props: Partial<Parameters<typeof StageAssignments>[0]> = {}) {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(
    <StageAssignments
      metrics={metrics}
      settings={settings}
      answers={answers}
      prices={prices}
      {...props}
    />,
  );
  return host;
}

const row = (host: HTMLElement, label: string) =>
  [...host.querySelectorAll("tbody tr")].find(
    (item) => item.querySelector("th")?.textContent === label,
  ) as HTMLElement;

it("lists every paid job once, in pipeline order", () => {
  const host = render();
  expect(
    [...host.querySelectorAll("tbody th")].map((item) => item.textContent),
  ).toEqual([
    "Transcription",
    "Facts",
    "Report and coaching",
    "Pointer review",
    "Call data · fast",
    "Call data · deep",
    "AI replies",
    "Analysis pipeline (one-pass trial)",
  ]);
  expect(host.textContent).toContain("dev · last 14 days");
});

it("gives phones one card per job, with the change on the card", () => {
  const cards = [
    ...render().querySelectorAll('[role="list"] [role="listitem"]'),
  ];
  expect(
    cards.map((card) => card.querySelector("strong")?.textContent),
  ).toHaveLength(8);
  const fast = cards[4] as HTMLElement;
  expect(fast.querySelector("strong")?.textContent).toBe("Call data · fast");
  expect(fast.querySelector("code")?.textContent).toBe("model-a");
  expect(fast.textContent).toContain("₹0.05 a min");
  expect(fast.querySelectorAll("li")).toHaveLength(2);
  expect(cards[0]?.querySelector("a")?.getAttribute("href")).toBe(
    "/sales-xray/providers?tab=providers",
  );
});

it("shows this environment's model, its cost, and an estimate for every model", () => {
  const fast = row(render(), "Call data · fast");
  const text = fast.textContent ?? "";
  expect(text).toContain("gemini");
  expect(text).not.toContain("old-model");
  expect(fast.querySelector("code")?.textContent).toBe("model-a");
  expect(text).toContain("₹0.05 a min");
  const estimates = fast.querySelector(
    '[aria-label="Call data · fast: estimate per model"]',
  ) as HTMLElement;
  const items = [...estimates.querySelectorAll("li")];
  expect(items.map((item) => item.textContent)).toEqual([
    "Model A ₹0.097 a min",
    "Model B ₹0.079 a min",
  ]);
  expect(items[0]?.hasAttribute("data-current")).toBe(true);
  expect(items[1]?.hasAttribute("data-current")).toBe(false);
});

it("sends approval-bound jobs to Routes, and says plainly what cannot change here", () => {
  const host = render();
  const speech = row(host, "Transcription");
  expect(speech.querySelector("a")?.getAttribute("href")).toBe(
    "/sales-xray/providers?tab=providers",
  );
  expect(speech.textContent).toContain("needs approval in production");
  expect(speech.textContent).toContain("₹0.50 a min");
  expect(row(host, "Pointer review").textContent).toContain("Set in code");
  expect(row(host, "Facts").textContent).toContain("Not run in this window");
  expect(row(host, "Facts").textContent).toContain("–");
});

it("still offers the change without metrics, and leaves out estimates it cannot make", () => {
  const host = render({ metrics: null });
  const fast = row(host, "Call data · fast");
  expect(fast.querySelector("code")?.textContent).toBe("model-a");
  expect(fast.querySelector("ul")).toBeNull();
  expect(host.textContent).toContain("This environment · last 30 days");
});

it("prices a stage's tokens per audio minute at a model's list price", () => {
  const stage = { inputTokens: 200_000, outputTokens: 20_000 };
  const first = prices[0];
  if (!first) throw new Error("expected a priced model");
  expect(estimatePerMinute(stage, 100, first, 88)).toBeCloseTo(0.0968, 6);
  expect(estimatePerMinute(stage, 0, first, 88)).toBeNull();
  expect(rupeesPerMinute(null)).toBe("–");
  expect(
    modelPrices([{ model: "x", label: "X", inputUsd: "", outputUsd: "1" }]),
  ).toEqual([]);
});

it("switches the analysis pipeline here and links to its comparison", () => {
  const PIPELINE = "/v1/admin/analysis-pipeline";
  const withPipeline = normalizeRegistry({
    settings: [
      {
        id: "analysis_pipeline.mode",
        area: "analysis-pipeline",
        label: "Analysis pipeline",
        kind: "enum",
        read: { path: PIPELINE, value: "/config/mode", revision: "/revision" },
        write: {
          method: "PUT",
          path: `${PIPELINE}/settings`,
          body: {
            expected_revision: "$revision",
            config: "$merged",
            reason: "$reason",
          },
          idempotency_key: false,
          merge: { container: "/config", key: ["mode"] },
          needs_reason: true,
        },
        options: [],
        options_from: { list: "/modes", value: "value", label: "label" },
      },
    ],
  }).settings;
  const pipeline = row(
    render({
      settings: withPipeline,
      answers: {
        ...answers,
        [PIPELINE]: {
          revision: 2,
          config: { mode: "both" },
          modes: [
            { value: "classic", label: "Today's pipeline" },
            { value: "both", label: "Both, side by side" },
          ],
        },
      },
    }),
    "Analysis pipeline (one-pass trial)",
  );
  expect(
    pipeline.querySelector('button[aria-label="Change Analysis pipeline"]'),
  ).not.toBeNull();
  expect(
    pipeline.querySelector('a[href="/sales-xray/one-pass"]')?.textContent,
  ).toBe("Compare side by side");
  // Without its answer the row still links to the comparison.
  const bare = row(render(), "Analysis pipeline (one-pass trial)");
  expect(bare.querySelector("a")?.getAttribute("href")).toBe(
    "/sales-xray/one-pass",
  );
});
