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
  element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
  value: string,
) {
  if (element instanceof HTMLSelectElement) {
    element.value = value;
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return;
  }
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
  it("protects selected review settings before feedback text is entered", async () => {
    const guard = vi.fn(() => () => undefined);
    await act(async () =>
      root.render(
        <AssignedReviewForm
          assignment={assignment}
          onSubmit={vi.fn()}
          registerNavigationGuard={guard}
        />,
      ),
    );
    expect(guard).toHaveBeenLastCalledWith(false);
    await act(async () => setValue(container.querySelector("select")!, "high"));
    expect(guard).toHaveBeenLastCalledWith(true);
  });
  it("counts observations separately from reference material and keeps technical details collapsed", async () => {
    const finding = {
      title: "Clarify the next step",
      explanation: "Ask for a follow-up date.",
      evidence: [],
    };
    await act(async () =>
      root.render(
        <AssignedReviewForm
          assignment={{
            ...assignment,
            report: {
              ...assignment.report,
              groups: [
                { title: "Improvements", findings: [finding] },
                {
                  title: "Report framework",
                  kind: "reference",
                  findings: [finding, finding],
                },
                { title: "Strengths", findings: [] },
              ],
            },
          }}
          onSubmit={vi.fn()}
        />,
      ),
    );
    expect(container.textContent).toContain("1 observation");
    expect(container.textContent).not.toContain("No findings supplied");
    const reference = [...container.querySelectorAll("details")].find(
      (el) =>
        el.querySelector("summary")?.textContent ===
        "Report reference and technical details",
    )!;
    expect(reference.open).toBe(false);
    expect(reference.textContent).toContain("Report framework");
    const audio = container.querySelector("audio")!;
    expect(
      audio.compareDocumentPosition(reference) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("keeps feedback when switching perspective and searching moments", async () => {
    const clips = Array.from({ length: 7 }, (_, index) => ({
      ...assignment.clips[0]!,
      segment_id: `segment-${index}`,
      quote: `Moment topic ${index}`,
    }));
    const submit = vi.fn().mockResolvedValue({ submission_id: "new-review" });
    await act(async () =>
      root.render(
        <AssignedReviewForm
          assignment={{ ...assignment, clips }}
          onSubmit={submit}
        />,
      ),
    );
    await act(async () => {
      setValue(
        container.querySelector("textarea")!,
        "Preserve my observation.",
      );
      setValue(container.querySelector("select")!, "high");
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Developer"))!
        .click();
      setValue(
        container.querySelector<HTMLInputElement>('input[type="search"]')!,
        "topic 5",
      );
    });
    expect(container.querySelector("textarea")!.value).toBe(
      "Preserve my observation.",
    );
    expect(
      container.querySelectorAll('[aria-label="Timestamped clips"] button'),
    ).toHaveLength(1);
    await act(async () =>
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent === "Save feedback")!
        .click(),
    );
    expect(submit.mock.calls[0]?.[0]).toMatchObject({
      lens: "technical",
      clip: { segment_id: "segment-0" },
      feedback: "Preserve my observation.",
    });
  });
  it("uses a new request identity after editing a failed draft", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValueOnce(new Error("Temporary failure"))
      .mockResolvedValueOnce({ submission_id: "submission-edited" });
    await act(async () =>
      root.render(
        <AssignedReviewForm assignment={assignment} onSubmit={onSubmit} />,
      ),
    );
    await act(async () => {
      setValue(container.querySelector("textarea")!, "First observation.");
      setValue(container.querySelector("select")!, "high");
    });
    const save = () =>
      [...container.querySelectorAll("button")]
        .find((button) =>
          /Save feedback|Retry save/.test(button.textContent ?? ""),
        )!
        .click();
    await act(async () => save());
    await act(async () =>
      setValue(container.querySelector("textarea")!, "Revised observation."),
    );
    await act(async () => save());
    expect(onSubmit.mock.calls[0]?.[1]).not.toBe(onSubmit.mock.calls[1]?.[1]);
    expect(onSubmit.mock.calls[1]?.[0].feedback).toBe("Revised observation.");
    expect(document.activeElement?.textContent).toContain("Feedback saved.");
  });

  it("rechecks audio access and preserves a dirty draft when it is revoked", async () => {
    const verifyAudioAccess = vi
      .fn()
      .mockRejectedValue(new Error("This review has expired or been revoked."));
    await act(async () =>
      root.render(
        <AssignedReviewForm
          assignment={assignment}
          onSubmit={vi.fn()}
          verifyAudioAccess={verifyAudioAccess}
        />,
      ),
    );
    await act(async () =>
      setValue(container.querySelector("textarea")!, "Keep this draft."),
    );
    await act(async () =>
      container.querySelector("audio")!.dispatchEvent(new Event("error")),
    );
    expect(verifyAudioAccess).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("expired or been revoked");
    expect(container.querySelector("textarea")?.value).toBe("Keep this draft.");
  });

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
    const confidence = container.querySelector("select")!;
    await act(async () => {
      setValue(feedback, "Correct the next-step attribution.");
      setValue(confidence, "high");
    });
    await act(async () =>
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent?.includes("Save feedback"))
        ?.click(),
    );

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(submitted).toMatchObject({
      assignment_id: "assignment-7",
      reviewer_id: "person-7",
      lens: "sales",
      clip: { segment_id: "segment-1", start_ms: 42_000, end_ms: 68_000 },
    });
    expect(container.textContent).toContain("Feedback saved.");
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
    const confidence = container.querySelector("select")!;
    await act(async () => {
      setValue(feedback, "Keep the original evidence immutable.");
      setValue(confidence, "medium");
    });
    const submit = () =>
      [...container.querySelectorAll("button")]
        .find((button) =>
          /Save feedback|Retry save/.test(button.textContent ?? ""),
        )
        ?.click();
    await act(async () => submit());
    expect(container.textContent).toContain("temporary review API failure");
    expect(feedback.value).toBe("Keep the original evidence immutable.");
    await act(async () => submit());
    expect(onSubmit).toHaveBeenCalledTimes(2);
    expect(onSubmit.mock.calls[0]?.[1]).toBe(onSubmit.mock.calls[1]?.[1]);
    expect(container.textContent).toContain("Feedback saved.");
  });
});
