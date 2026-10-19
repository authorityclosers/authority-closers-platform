// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { normalizeHealth } from "./health-data";
import { EngineHealthPanels, ReviewHealthPanels } from "./engine-panels";
import { percent, typeLabel } from "./engine-data";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const HEALTH = normalizeHealth({
  window: { days: 7 },
  engine: {
    pipelines: [
      {
        pipeline: "fast",
        version: "fast-2",
        runs: 4,
        succeeded: 2,
        failed: 1,
        skipped: 1,
        success_share: 0.667,
        time: { count: 2, p50_ms: 6000, p90_ms: 9000 },
        cost_inr: 0.5,
        cost_per_run_inr: 0.17,
        calls: 1,
        running: 0,
        quiet: 0,
        reasons: [
          { state: "failed", code: "provider_timeout", runs: 1 },
          { state: "skipped", code: "too_long", runs: 1 },
        ],
        models: [{ provider: "gemini", model: "flash", runs: 2 }],
      },
      {
        pipeline: "deep",
        version: null,
        runs: 0,
        succeeded: 0,
        failed: 0,
        skipped: 0,
        success_share: null,
        time: { count: 0, p50_ms: null, p90_ms: null },
        cost_inr: 0,
        cost_per_run_inr: null,
        running: 1,
        quiet: 1,
      },
    ],
    versions: [
      { pipeline: "fast", version: "fast-2", runs: 1, success_share: 1 },
      { pipeline: "fast", version: "fast-1", runs: 3, success_share: 0.5 },
    ],
    daily: [
      {
        day: "2026-10-18",
        fast: { succeeded: 0, failed: 1 },
        deep: { succeeded: 0, failed: 0 },
      },
      {
        day: "2026-10-19",
        fast: { succeeded: 2, failed: 0 },
        deep: { succeeded: 0, failed: 0 },
      },
    ],
    quiet: [
      {
        run_id: "8a0c1d2e-0000-4000-8000-000000000008",
        recording_id: "rec-1",
        pipeline: "deep",
        started_at: "2026-10-19T10:00:00+00:00",
      },
    ],
  },
  review: {
    answers: 9,
    calls: 2,
    pipelines: [
      {
        key: "analysis-sales",
        title: "Analysis: sales",
        answers: 6,
        calls: 2,
        items: 3,
        reviewers: 2,
        right: 3,
        wrong: 1,
        right_share: 0.75,
        questions: [
          {
            key: "correct",
            label: "Is this right?",
            kind: "verdict",
            answers: 5,
            counts: { correct: 3, wrong: 1, unsure: 1 },
          },
          {
            key: "fix",
            label: "What should it say?",
            kind: "correct",
            answers: 1,
          },
        ],
        types: [
          {
            type: "buyer.budget",
            answers: 2,
            right: 1,
            wrong: 1,
            right_share: 0.5,
          },
        ],
        agreement: { compared: 2, agreed: 1, share: 0.5 },
      },
      {
        key: "coaching",
        title: "Coaching",
        answers: 3,
        calls: 1,
        items: 2,
        reviewers: 2,
        right: 1,
        wrong: 0,
        right_share: 1,
        questions: [
          {
            key: "useful",
            label: "How useful for this rep?",
            kind: "scale",
            answers: 2,
            average: 3,
          },
        ],
        types: [],
        agreement: { compared: 0, agreed: 0, share: null },
      },
    ],
    engine_versions: [
      { pipeline: "fast", version: "fast-2", answers: 2, right_share: 1 },
    ],
    reviewers: [{ name: "Dipak", answers: 5, calls: 1 }],
  },
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

it("reads the engine and review sections, and defaults when the API has none", () => {
  expect(HEALTH.engine.pipelines.map((row) => row.pipeline)).toEqual([
    "fast",
    "deep",
  ]);
  expect(HEALTH.engine.daily[1].counts.fast).toEqual({
    succeeded: 2,
    failed: 0,
  });
  expect(HEALTH.review.pipelines[0].questions[1].counts).toBeNull();
  const bare = normalizeHealth({});
  expect(bare.engine.pipelines).toEqual([]);
  expect(bare.review.answers).toBe(0);
  expect(percent(0.667)).toBe("67%");
  expect(percent(null)).toBe("–");
  expect(typeLabel("buyer.next_step")).toBe("Buyer next step");
});

it("shows each pipeline's outcomes, reasons and runs gone quiet", async () => {
  await act(async () =>
    root.render(<EngineHealthPanels data={HEALTH.engine} />),
  );
  const text = host.textContent ?? "";
  const rows = [...host.querySelectorAll("tbody tr")].map(
    (row) => row.textContent,
  );
  expect(rows[0]).toContain("Fast fast-2");
  expect(rows[0]).toContain("67%");
  expect(rows[0]).toContain("6 s");
  expect(rows[1]).toContain("1 running");
  expect(rows[1]).toContain("1 quiet");
  expect(rows[0]).not.toContain("running");
  expect(text).not.toContain("0 running");
  expect(text).toContain("provider_timeout");
  expect(text).toContain("too_long");
  expect(text).toContain("Deep run with no outcome");
  const quiet = host.querySelector('a[href="/calls/rec-1?tab=analysis"]');
  expect(quiet).not.toBeNull();
  expect(text).toContain("By engine version");
});

it("shows judged-right shares, agreement and question summaries", async () => {
  await act(async () =>
    root.render(<ReviewHealthPanels data={HEALTH.review} />),
  );
  const text = host.textContent ?? "";
  expect(text).toContain("Analysis: sales");
  expect(text).toContain("3 of 4");
  expect(text).toContain("1 of 2 shared claims");
  expect(text).toContain("3 correct · 1 wrong · 1 unsure");
  expect(text).toContain("1 correction");
  expect(text).toContain("3.0 of 5 on average");
  expect(text).toContain("No claim has two reviewers yet");
  expect(text).toContain("Buyer budget");
  expect(text).toContain("Dipak");
});

it("points to Analysis review when nobody has answered yet", async () => {
  await act(async () =>
    root.render(<ReviewHealthPanels data={normalizeHealth({}).review} />),
  );
  expect(host.textContent).toContain("No review answers in this window");
  expect(host.querySelector('a[href="/analysis-review"]')).not.toBeNull();
});
