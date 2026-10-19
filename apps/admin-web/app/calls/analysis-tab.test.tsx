// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AnalysisTab } from "./analysis-tab";
import { normalizeCallDetail } from "./call-detail-data";
import { normalizeReviewCall } from "./review-verdicts-data";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const DETAIL = normalizeCallDetail({
  call: {
    recording_id: "r-1",
    organisation: { name: "Fictional Org", kind: "customer" },
  },
  runs: [
    { run_id: "r2", pipeline: "deep", state: "failed" },
    { run_id: "r1", pipeline: "fast", state: "succeeded" },
  ],
  objects: [{ object_id: "f-1", type: "need", current: true }],
  totals: { call: { cost_inr: 2.4, tokens_in: 6190, tokens_out: 900 } },
  categories: { needs: "Needs and goals" },
  facts: [
    {
      object_id: "f-1",
      type: "need",
      category: "needs",
      label: "Main need",
      display: "More site visits confirmed in writing",
      confidence: 0.92,
      basis: "confirmed",
      source: { pipeline: "deep" },
      evidence: [
        {
          start_ms: 95_000,
          end_ms: 99_000,
          quote: "Confirm visits in writing",
          role: "prospect",
        },
        {
          start_ms: 42_000,
          end_ms: 45_000,
          quote: "Visits go unrecorded",
          role: "prospect",
        },
      ],
    },
    {
      object_id: "f-2",
      type: "objection",
      category: "needs",
      label: "Worry",
      display: "Paying before the scope fits",
      confidence: 0.81,
      basis: "inferred",
      source: { pipeline: "fast" },
    },
  ],
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

it("lists facts under their category, whose word each is, and jumps to each moment", async () => {
  const onSeek = vi.fn();
  await act(async () =>
    root.render(
      <AnalysisTab detail={DETAIL} recordingId="r-1" onSeek={onSeek} />,
    ),
  );
  expect(host.textContent).toContain("Needs and goals 2");
  expect(host.textContent).toContain("Person · confirmed");
  expect(host.textContent).toContain("AI · inferred");
  expect(host.textContent).toContain("Fast succeeded");
  expect(host.textContent).toContain("Deep failed");
  expect(host.textContent).toContain("6.2k in");
  const moments = [...host.querySelectorAll("button")];
  // Earliest moment first.
  expect(moments.map((button) => button.textContent)).toEqual([
    "▶ 0:42",
    "▶ 1:35",
  ]);
  await act(async () => moments[0].click());
  expect(onSeek).toHaveBeenCalledWith(42_000);
  expect(host.querySelector('a[href="/calls/r-1/map"]')).not.toBeNull();
});

it("says so when the engine has not read the call", async () => {
  await act(async () =>
    root.render(
      <AnalysisTab detail={null} recordingId="r-1" onSeek={() => {}} />,
    ),
  );
  expect(host.textContent).toContain("hasn’t read this call yet");
  expect(host.querySelector('a[href="/calls/r-1/map"]')).not.toBeNull();
});

const INTENTS = [
  "greeting",
  "rapport",
  "discovery",
  "pain",
  "goal",
  "qualification",
  "pitch",
  "pricing",
  "objection",
];
const MOMENTS = normalizeCallDetail({
  call: { recording_id: "r-2" },
  segments: Array.from({ length: 14 }, (_, index) => ({
    object_id: `m-${index}`,
    segment_id: `s${index}`,
    start_ms: index * 10_000,
    end_ms: index * 10_000 + 8_000,
    speaker: index % 2 ? "prospect" : "seller",
    intent: index === 0 ? "pricing" : "small_talk",
    act: "question",
    sentiment: "negative",
    tone: "hesitant",
    topics: index === 0 ? ["price", "emi"] : [],
  })),
});
const PSYCHOLOGY = normalizeReviewCall({
  pipelines: [
    {
      key: "analysis-psychology",
      version: 1,
      kind: "analysis",
      title: "Analysis: psychology",
      definition: {
        targets: ["segment"],
        questions: [
          {
            key: "correct",
            kind: "verdict",
            label: "Is this reading right?",
            options: ["correct", "wrong", "unsure"],
          },
          {
            key: "intent",
            kind: "pick",
            label: "What is this moment really about?",
            options: INTENTS,
            when: { correct: "wrong" },
          },
        ],
      },
    },
  ],
  verdicts: [],
});

it("lists moments with their reading and judges them in psychology terms", async () => {
  const fetcher = vi.fn(
    async (_path: string, init?: RequestInit) =>
      new Response(
        JSON.stringify({
          id: "v-1",
          target: { kind: "segment", ref: "m-0" },
          question: JSON.parse(String(init?.body)).question,
          answer: JSON.parse(String(init?.body)).answer,
          mine: true,
          reviewer_id: "me",
        }),
        { status: 201, headers: { "content-type": "application/json" } },
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const onSeek = vi.fn();
  await act(async () =>
    root.render(
      <AnalysisTab
        detail={MOMENTS}
        recordingId="r-2"
        review={PSYCHOLOGY}
        onSeek={onSeek}
      />,
    ),
  );
  const section = host.querySelector('[aria-label="Moments"]')!;
  expect(section.textContent).toContain("Moments 14");
  expect(section.textContent).toContain("Pricing · Question · price, emi");
  expect(section.textContent).toContain("Hesitant");
  expect(section.textContent).toContain("Negative");
  // The first 12, then all of them on request.
  expect(section.querySelectorAll("li")).toHaveLength(12);
  const more = [...section.querySelectorAll("button")].find((button) =>
    button.textContent?.startsWith("Show all"),
  )!;
  await act(async () => more.click());
  expect(section.querySelectorAll("li")).toHaveLength(14);

  const first = section.querySelector("li")!;
  await act(async () =>
    first.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(onSeek).toHaveBeenCalledWith(0);

  // Wrong: the long intent list shows as a menu, and a pick saves as a segment verdict.
  const wrong = [...first.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent === "Wrong",
  )!;
  await act(async () => wrong.click());
  const menu = first.querySelector<HTMLSelectElement>("select")!;
  expect(menu.getAttribute("aria-label")).toBe(
    "What is this moment really about?",
  );
  Object.getOwnPropertyDescriptor(
    HTMLSelectElement.prototype,
    "value",
  )?.set?.call(menu, "objection");
  await act(async () => {
    menu.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const bodies = fetcher.mock.calls.map((call) =>
    JSON.parse(String((call as unknown as [string, RequestInit])[1].body)),
  );
  expect(bodies).toEqual([
    {
      pipeline: "analysis-psychology",
      target_kind: "segment",
      target_ref: "m-0",
      question: "correct",
      answer: { value: "wrong" },
    },
    {
      pipeline: "analysis-psychology",
      target_kind: "segment",
      target_ref: "m-0",
      question: "intent",
      answer: { value: "objection" },
    },
  ]);
  vi.unstubAllGlobals();
});
