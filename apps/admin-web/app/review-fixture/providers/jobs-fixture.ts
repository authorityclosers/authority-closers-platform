/**
 * Fictional "Who does each job" data for local review: the settings registry rows, the
 * areas' answers and 30 days of metrics, in the shapes the API returns. Illustrative only.
 */
import { normalizeRegistry } from "../../settings/registry-data";
import { modelPrices } from "../../sales-xray/provider-hub-data";
import { normalizeMetrics } from "../../usage/cost-data";

const CALL_DATA = "/v1/admin/call-data";
const LEAD_DESK_AI = "/v1/admin/lead-desk-ai";

const MODELS = [
  ["gemini-3.8-flash-lite", "Gemini Flash-Lite", "0.10", "0.40"],
  ["gemini-3.8-flash", "Gemini Flash", "0.30", "2.50"],
  ["gemini-3.8-pro", "Gemini Pro", "1.25", "10.00"],
].map(([model, label, input, output]) => ({
  model,
  label,
  input_usd_per_million: input,
  output_usd_per_million: output,
}));

const modelSetting = (
  id: string,
  label: string,
  path: string,
  value: string,
  key: string[],
) => ({
  id,
  area: path === CALL_DATA ? "call-data" : "lead-desk-ai",
  label,
  kind: "enum",
  read: { path, value, revision: "/revision" },
  write: {
    method: "PUT",
    path: `${path}/settings`,
    body: { expected_revision: "$revision", config: "$merged" },
    idempotency_key: false,
    merge: { container: "/config", key },
    needs_reason: false,
  },
  options: [],
  options_from: { list: "/models", value: "model", label: "label" },
});

export const jobsSettings = normalizeRegistry({
  settings: [
    modelSetting(
      "call_data.fast.model",
      "Fast read: model",
      CALL_DATA,
      "/config/fast/model",
      ["fast", "model"],
    ),
    modelSetting(
      "call_data.deep.model",
      "Deep read: model",
      CALL_DATA,
      "/config/deep/model",
      ["deep", "model"],
    ),
    modelSetting(
      "lead_desk_ai.model",
      "AI replies: model",
      LEAD_DESK_AI,
      "/config/model",
      ["model"],
    ),
  ],
}).settings;

export const jobsAnswers = {
  [CALL_DATA]: {
    revision: 12,
    config: {
      fast: { model: "gemini-3.8-flash-lite" },
      deep: { model: "gemini-3.8-pro" },
    },
    models: MODELS,
  },
  [LEAD_DESK_AI]: {
    revision: 3,
    config: { model: "gemini-3.8-flash" },
    models: MODELS,
  },
};

export const jobsPrices = modelPrices(
  MODELS.map((item) => ({
    model: item.model,
    label: item.label,
    inputUsd: item.input_usd_per_million,
    outputUsd: item.output_usd_per_million,
  })),
);

const route = (stage: string, provider: string, model: string) => ({
  environment: "dev",
  stage,
  provider,
  model,
  runs: 40,
});

const stage = (code: string, perMinute: number, input = 0, output = 0) => ({
  stage: code,
  per_minute: perMinute,
  input_tokens: input,
  output_tokens: output,
});

export const jobsMetrics = normalizeMetrics({
  window: { days: 30 },
  here: "dev",
  fx: { currency: "USD", usd_to_inr: 100, set_on: "2026-09-19" },
  routes: [
    route("C2", "sarvam", "saaras:v3"),
    route("C4", "gemini", "gemini-3.8-flash"),
    route("C5", "gemini", "gemini-3.8-pro"),
    route("PR", "gemini", "gemini-3.8-flash"),
    route("CDF", "gemini", "gemini-3.8-flash-lite"),
    route("CDD", "gemini", "gemini-3.8-pro"),
  ],
  overview: {
    audio_minutes: 1200,
    by_stage: [
      stage("C2", 0.5),
      stage("C4", 0.06, 2_400_000, 180_000),
      stage("C5", 0.21, 1_900_000, 260_000),
      stage("PR", 0.03, 1_100_000, 90_000),
      stage("CDF", 0.008, 720_000, 60_000),
      stage("CDD", 0.09, 720_000, 18_000),
    ],
  },
});
