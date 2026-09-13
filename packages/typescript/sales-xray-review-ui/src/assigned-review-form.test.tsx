// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AssignedReviewForm,
  type ReviewAssignment,
  type ReviewProposalDraft,
} from "./assigned-review-form";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const assignment: ReviewAssignment = {
  assignment_id: "assignment-7",
  recording_id: "recording-7",
  run_revision: "run-revision-3",
  cursor: "cursor-4",
  reviewer: { person_id: "person-7", display_name: "Suyash" },
  report: {
    title: "Call report",
    summary: "A report grounded in the selected call.",
  },
  clips: [
    {
      segment_id: "segment-1",
      start_ms: 42_000,
      end_ms: 68_000,
      playback_url: "/v1/conversation/review-clips/segment-1",
      quote: "Let us clarify the next step.",
    },
  ],
  allowed_lenses: ["sales", "technical", "ux"],
};

function setValue(
  element: HTMLInputElement | HTMLTextAreaElement,
  value: string,
) {
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(
    element,
    value,
  );
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("AssignedReviewForm", () => {
  it("keeps the server reviewer identity while submitting the selected lens and clip", async () => {
    let submitted: ReviewProposalDraft | undefined;
    const onSubmit = vi.fn(async (draft: ReviewProposalDraft) => {
      submitted = draft;
      return { submission_id: "submission-1", cursor: "cursor-5" };
    });

    await act(async () =>
      root.render(
        <AssignedReviewForm assignment={assignment} onSubmit={onSubmit} />,
      ),
    );
    const feedback = container.querySelector("textarea")!;
    const confidence = container.querySelector("input")!;
    await act(async () => {
      setValue(feedback, "Correct the next-step attribution.");
      setValue(confidence, "high");
    });
    await act(async () =>
      [...container.querySelectorAll("button")]
        .find((button) =>
          button.textContent?.includes("Save append-only proposal"),
        )
        ?.click(),
    );

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(submitted).toMatchObject({
      assignment_id: "assignment-7",
      reviewer_id: "person-7",
      lens: "sales",
      clip: { segment_id: "segment-1", start_ms: 42_000, end_ms: 68_000 },
    });
    expect(container.textContent).toContain("Proposal appended.");
    expect(container.textContent).toContain("cursor-5");
  });

  it("preserves draft text and reuses the idempotency key after a failed save", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValueOnce(new Error("temporary review API failure"))
      .mockResolvedValueOnce({
        submission_id: "submission-2",
        cursor: "cursor-6",
      });
    await act(async () =>
      root.render(
        <AssignedReviewForm assignment={assignment} onSubmit={onSubmit} />,
      ),
    );
    const feedback = container.querySelector("textarea")!;
    const confidence = container.querySelector("input")!;
    await act(async () => {
      setValue(feedback, "Keep the original evidence immutable.");
      setValue(confidence, "medium");
    });
    const submit = () =>
      [...container.querySelectorAll("button")]
        .find((button) =>
          /Save append-only proposal|Retry append-only proposal/.test(
            button.textContent ?? "",
          ),
        )
        ?.click();
    await act(async () => submit());
    expect(container.textContent).toContain("temporary review API failure");
    expect(feedback.value).toBe("Keep the original evidence immutable.");
    await act(async () => submit());
    expect(onSubmit).toHaveBeenCalledTimes(2);
    expect(onSubmit.mock.calls[0]?.[1]).toBe(onSubmit.mock.calls[1]?.[1]);
    expect(container.textContent).toContain("Proposal appended.");
  });
});
