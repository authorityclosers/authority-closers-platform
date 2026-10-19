// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  myAnswers,
  normalizeReviewCall,
  othersOn,
  withSaved,
} from "./review-verdicts-data";
import { VerdictChips } from "./verdict-chips";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const REVIEW = normalizeReviewCall({
  pipelines: [
    {
      key: "analysis-sales",
      version: 1,
      kind: "analysis",
      title: "Analysis: sales",
      definition: {
        targets: ["object", "fact"],
        questions: [
          {
            key: "correct",
            kind: "verdict",
            label: "Is this right?",
            options: ["correct", "wrong", "unsure"],
          },
          {
            key: "fix",
            kind: "correct",
            label: "What should it say?",
            when: { correct: "wrong" },
          },
        ],
      },
    },
  ],
  verdicts: [
    {
      id: "v1",
      target: { kind: "fact", ref: "f-1" },
      question: "correct",
      answer: { value: "correct" },
      mine: false,
      reviewer_id: "dipak",
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

it("reads answers per target and replaces only this reviewer's answer", () => {
  expect(othersOn(REVIEW.verdicts, "f-1")).toBe(1);
  expect(myAnswers(REVIEW.verdicts, "f-1")).toEqual({});
  const saved = {
    id: "v2",
    targetKind: "fact",
    targetRef: "f-1",
    question: "correct",
    answer: { value: "wrong" },
    mine: true,
    reviewerId: "me",
  };
  const after = withSaved(REVIEW.verdicts, saved);
  expect(myAnswers(after, "f-1")).toEqual({ correct: { value: "wrong" } });
  expect(after).toHaveLength(2);
});

it("saves a one-tap verdict, then asks for the correction once it is wrong", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        id: "v2",
        target: { kind: "fact", ref: "f-1" },
        question: "correct",
        answer: { value: "wrong" },
        mine: true,
        reviewer_id: "me",
      }),
      { status: 201, headers: { "content-type": "application/json" } },
    ),
  );
  const onSaved = vi.fn();
  const draw = (mine: Record<string, { value?: string; text?: string }>) =>
    act(async () =>
      root.render(
        <VerdictChips
          recordingId="r-1"
          pipeline={REVIEW.pipelines[0]}
          targetKind="fact"
          targetRef="f-1"
          mine={mine}
          others={1}
          onSaved={onSaved}
        />,
      ),
    );
  await draw({});
  expect(
    host.querySelector('input[aria-label="What should it say?"]'),
  ).toBeNull();
  expect(host.textContent).toContain("1 other reviewer");
  const wrong = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Wrong",
  )!;
  await act(async () => wrong.click());
  const [path, init] = fetcher.mock.calls[0];
  expect(path).toBe("/v1/admin/conversation/review/calls/r-1/verdicts");
  expect(JSON.parse(String(init?.body))).toEqual({
    pipeline: "analysis-sales",
    target_kind: "fact",
    target_ref: "f-1",
    question: "correct",
    answer: { value: "wrong" },
  });
  expect(new Headers(init?.headers).get("idempotency-key")).toBeTruthy();
  expect(onSaved).toHaveBeenCalledWith(
    expect.objectContaining({
      question: "correct",
      answer: { value: "wrong" },
    }),
  );

  await draw({ correct: { value: "wrong" } });
  const pressed = host.querySelector('button[aria-pressed="true"]');
  expect(pressed?.textContent).toBe("Wrong");
  expect(
    host.querySelector('input[aria-label="What should it say?"]'),
  ).not.toBeNull();
});
