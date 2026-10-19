// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { PipelineEditor } from "./pipeline-editor";
import {
  draftProblems,
  newQuestionKey,
  normalizePipelineSettings,
  optionsFromText,
  pipelineRequest,
  reviewArea,
  slug,
} from "./review-pipelines-data";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const SETTINGS = normalizePipelineSettings({
  can_edit: true,
  limits: {
    questions: 8,
    options: 12,
    label: 120,
    sample: 100,
    kinds: ["verdict", "pick", "correct", "scale"],
  },
  pipelines: [
    {
      key: "analysis-sales",
      version: 1,
      saved: false,
      kind: "analysis",
      title: "Analysis: sales",
      definition: {
        targets: ["object", "fact"],
        show: ["evidence", "transcript_window"],
        sample: { order: "newest", limit: 20 },
        reconcile: { reviewers: 2 },
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
});
const SALES = SETTINGS.pipelines[0];

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  refresh.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

/** Set a React-controlled field's value the way typing does. */
async function type(
  element: HTMLInputElement | HTMLSelectElement,
  value: string,
) {
  const proto =
    element instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(element, value);
  await act(async () => {
    element.dispatchEvent(
      new Event(element instanceof HTMLSelectElement ? "change" : "input", {
        bubbles: true,
      }),
    );
  });
}

const button = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find((item) =>
    item.textContent?.includes(text),
  )!;

it("reads pipelines as settings and checks a draft the way the API does", () => {
  expect(SALES.sampleLimit).toBe(20);
  expect(SALES.reconcileReviewers).toBe(2);
  expect(SALES.questions[1].when).toEqual({ correct: "wrong" });
  const area = reviewArea({ ok: true, data: SETTINGS });
  expect(area.href).toBe("/settings/review-pipelines");
  expect(area.rows[0]).toEqual({
    label: "Analysis: sales",
    value: "Version 1 · 2 questions · 20 calls a sample",
    note: "Call objects, Facts · default, never edited",
  });
  expect(reviewArea({ ok: false, error: "No access" }).unavailable).toBe(
    "No access",
  );

  expect(slug("Buyer's emotion!")).toBe("buyer_s_emotion");
  expect(optionsFromText("Correct, wrong , Not sure,,")).toEqual([
    "correct",
    "wrong",
    "not_sure",
  ]);
  expect(newQuestionKey(SALES.questions)).toBe("question_3");

  const draft = { title: "T", sampleLimit: 20, questions: SALES.questions };
  expect(draftProblems(draft, SETTINGS.limits)).toEqual([]);
  expect(
    draftProblems(
      { ...draft, questions: [SALES.questions[1]] },
      SETTINGS.limits,
    ),
  ).toEqual([
    "Question 1: it must follow an option of an earlier question.",
    "The first question must be a verdict: Analysis health measures it.",
  ]);
  expect(
    draftProblems({ ...draft, sampleLimit: 0, title: " " }, SETTINGS.limits),
  ).toEqual([
    "Write a title (1 to 120 characters).",
    "Sample 1 to 100 calls at a time.",
  ]);
  expect(pipelineRequest(1, draft).questions[1]).toEqual({
    key: "fix",
    kind: "correct",
    label: "What should it say?",
    when: { correct: "wrong" },
  });
});

it("edits a question, adds one that follows an answer, and saves a new version once", async () => {
  const fetcher = vi.fn(
    async () =>
      new Response(JSON.stringify({ version: 2, changed: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  await act(async () =>
    root.render(
      <PipelineEditor pipeline={SALES} limits={SETTINGS.limits} canEdit />,
    ),
  );
  expect(button("Save as version 2").disabled).toBe(true); // nothing changed yet

  const inputs = () => [...host.querySelectorAll<HTMLInputElement>("input")];
  await type(inputs()[1], "30"); // calls a sample
  await act(async () => button("Add question").click());
  const fields = inputs();
  await type(fields[fields.length - 2], "What type is it really?");
  await type(fields[fields.length - 1], "objection, question, pain");
  const selects = [...host.querySelectorAll<HTMLSelectElement>("select")];
  await type(selects[selects.length - 1], "correct=wrong");

  const save = button("Save as version 2");
  expect(save.disabled).toBe(false);
  await act(async () => save.click());
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [path, init] = fetcher.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(path).toBe("/v1/admin/conversation/review/pipelines/analysis-sales");
  const body = JSON.parse(String(init.body));
  expect(body.based_on).toBe(1);
  expect(body.sample_limit).toBe(30);
  expect(body.questions[2]).toEqual({
    key: "question_3",
    kind: "pick",
    label: "What type is it really?",
    options: ["objection", "question", "pain"],
    when: { correct: "wrong" },
  });
  expect(host.querySelector('[role="status"]')?.textContent).toContain(
    "Saved as version 2",
  );
  expect(refresh).toHaveBeenCalled();
});

it("blocks a draft the API would refuse and says why", async () => {
  vi.stubGlobal("fetch", vi.fn());
  await act(async () =>
    root.render(
      <PipelineEditor pipeline={SALES} limits={SETTINGS.limits} canEdit />,
    ),
  );
  const options = [...host.querySelectorAll<HTMLInputElement>("input")][3];
  await type(options, "correct");
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Question 1: give 2 to 12 different options.",
  );
  expect(button("Save as version 2").disabled).toBe(true);
  await act(async () => button("Undo changes").click());
  expect(host.querySelector('[role="alert"]')).toBeNull();
});

it("shows the API's refusal, and is read-only for people who cannot edit", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: "This pipeline changed meanwhile. Reload and try again.",
          }),
          { status: 409, headers: { "content-type": "application/json" } },
        ),
    ),
  );
  await act(async () =>
    root.render(
      <PipelineEditor pipeline={SALES} limits={SETTINGS.limits} canEdit />,
    ),
  );
  await type(
    [...host.querySelectorAll<HTMLInputElement>("input")][0],
    "Sales analysis",
  );
  await act(async () => button("Save as version 2").click());
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "This pipeline changed meanwhile. Reload and try again.",
  );
  expect(refresh).not.toHaveBeenCalled();

  await act(async () =>
    root.render(
      <PipelineEditor
        pipeline={SALES}
        limits={SETTINGS.limits}
        canEdit={false}
      />,
    ),
  );
  expect(
    [...host.querySelectorAll<HTMLInputElement>("input")].every(
      (input) => input.disabled,
    ),
  ).toBe(true);
  expect(host.textContent).toContain("Only the AC control accounts");
});
