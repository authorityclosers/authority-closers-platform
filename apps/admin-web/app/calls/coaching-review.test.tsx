// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { CoachingReview } from "./coaching-review";
import {
  normalizeCoachingPoints,
  normalizeReviewCall,
} from "./review-verdicts-data";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const REVIEW = normalizeReviewCall({
  pipelines: [
    {
      key: "coaching",
      version: 1,
      kind: "coaching",
      title: "Coaching",
      definition: {
        targets: ["coaching"],
        questions: [
          {
            key: "true",
            kind: "verdict",
            label: "True for this call?",
            options: ["true", "false", "unsure"],
          },
          { key: "useful", kind: "scale", label: "How useful for this rep?" },
          {
            key: "fix",
            kind: "correct",
            label: "What should the coaching say?",
            when: { true: "false" },
          },
        ],
      },
    },
  ],
  verdicts: [],
});

const POINTS = normalizeCoachingPoints({
  run_id: "run-1",
  points: [
    {
      ref: "run-1:focus",
      key: "focus",
      kind: "focus",
      title: "What to work on now",
      text: "Ask for the date",
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
  vi.restoreAllMocks();
});

it("judges each coaching point as true or false and how useful, apart from the report", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        id: "v1",
        target: { kind: "coaching", ref: "run-1:focus" },
        question: "useful",
        answer: { value: 4 },
        mine: true,
        reviewer_id: "me",
      }),
      { status: 201, headers: { "content-type": "application/json" } },
    ),
  );
  await act(async () =>
    root.render(
      <CoachingReview recordingId="r-1" review={REVIEW} points={POINTS} />,
    ),
  );
  expect(host.textContent).toContain("What to work on now");
  expect(host.textContent).toContain("Ask for the date");
  const buttons = [...host.querySelectorAll("button")].map(
    (button) => button.textContent,
  );
  expect(buttons).toEqual(["True", "False", "Unsure", "1", "2", "3", "4", "5"]);
  const four = host.querySelector<HTMLButtonElement>(
    'button[aria-label="How useful for this rep? 4 of 5"]',
  )!;
  await act(async () => four.click());
  const [, init] = fetcher.mock.calls[0];
  expect(JSON.parse(String(init?.body))).toEqual({
    pipeline: "coaching",
    target_kind: "coaching",
    target_ref: "run-1:focus",
    question: "useful",
    answer: { value: 4 },
  });
  expect(
    host
      .querySelector('button[aria-label="How useful for this rep? 4 of 5"]')
      ?.getAttribute("aria-pressed"),
  ).toBe("true");
});

it("shows nothing without a coaching pipeline or points", async () => {
  await act(async () =>
    root.render(
      <CoachingReview
        recordingId="r-1"
        review={{ pipelines: [], verdicts: [] }}
        points={POINTS}
      />,
    ),
  );
  expect(host.textContent).toBe("");
});
