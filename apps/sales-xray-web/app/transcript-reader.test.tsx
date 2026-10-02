import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  SalesReport,
  Transcript,
  TranscriptSegment,
} from "./report-contract";
import { TranscriptReader } from "./transcript-reader";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;

function createSampleTranscript(): Transcript {
  const segments: TranscriptSegment[] = [
    {
      id: "seg-1",
      speaker_id: "rep",
      start_ms: 0,
      end_ms: 3000,
      text: "Hello and welcome to Authority Closers.",
    },
    {
      id: "seg-2",
      speaker_id: "prospect",
      start_ms: 3500,
      end_ms: 6000,
      text: "Thanks, our timing is uncertain on this side.",
    },
    {
      id: "seg-3",
      speaker_id: "rep",
      start_ms: 6500,
      end_ms: 9500,
      text: "I understand. Let us confirm the follow-up time for next Tuesday.",
    },
    {
      id: "seg-4",
      speaker_id: "prospect",
      start_ms: 10000,
      end_ms: 12000,
      text: "Tuesday at two works for me.",
    },
  ];

  return {
    source_sha256: "0".repeat(64),
    revision: "test-r1",
    timebase_id: "1ms",
    duration_ms: 12000,
    segments,
  };
}

function createSampleReport(): SalesReport {
  return {
    summary: "Test call report summary",
    verdict: "Good follow-up agreed.",
    review_status: "draft_not_dipak_adjudicated",
    source_label: "sample.mp3",
    source_sha256: "0".repeat(64),
    transcript_revision: "test-r1",
    dimensions: [],
    report_sections: [],
    strengths: [
      {
        title: "Confirm the follow-up time",
        explanation: "Rep clearly locked down the next conversation.",
        evidence: [
          {
            segment_id: "seg-3",
            quote: "Let us confirm the follow-up time for next Tuesday.",
            start_ms: 6500,
            end_ms: 9500,
          },
        ],
      },
    ],
    objection_analysis: [
      {
        title: "Timing uncertainty",
        explanation: "Prospect expressed hesitation around timeline.",
        evidence: [
          {
            segment_id: "seg-2",
            quote: "our timing is uncertain on this side.",
            start_ms: 3500,
            end_ms: 6000,
          },
        ],
      },
    ],
    missed_opportunities: [
      {
        title: "Ask why timeline is uncertain",
        explanation: "Could have dug deeper into underlying blockers.",
        evidence: [
          {
            segment_id: "seg-2",
            quote: "our timing is uncertain on this side.",
            start_ms: 3500,
            end_ms: 6000,
          },
        ],
      },
    ],
    improvements: [],
  };
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  // Clear modal portals
  document
    .querySelectorAll("[data-transcript-reader]")
    .forEach((el) => el.remove());
  document.body.style.overflow = "";
});

describe("TranscriptReader", () => {
  it("renders when open and unmounts when closed", async () => {
    const transcript = createSampleTranscript();
    const onClose = vi.fn();

    await act(async () =>
      root.render(
        <TranscriptReader
          isOpen={true}
          onClose={onClose}
          transcript={transcript}
        />,
      ),
    );

    const reader = document.querySelector("[data-transcript-reader]");
    expect(reader).not.toBeNull();
    expect(reader?.getAttribute("role")).toBe("dialog");
    expect(reader?.getAttribute("aria-modal")).toBe("true");

    await act(async () =>
      root.render(
        <TranscriptReader
          isOpen={false}
          onClose={onClose}
          transcript={transcript}
        />,
      ),
    );

    expect(document.querySelector("[data-transcript-reader]")).toBeNull();
  });

  it("closes on Close button click and Escape key", async () => {
    const transcript = createSampleTranscript();
    const onClose = vi.fn();

    await act(async () =>
      root.render(
        <TranscriptReader
          isOpen={true}
          onClose={onClose}
          transcript={transcript}
        />,
      ),
    );

    const closeBtn = document.querySelector<HTMLButtonElement>(
      'button[aria-label="Close transcript reader"]',
    );
    expect(closeBtn).not.toBeNull();

    await act(async () => closeBtn?.click());
    expect(onClose).toHaveBeenCalledOnce();

    await act(async () => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Escape",
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("supports text search with live match count and highlight navigation", async () => {
    const transcript = createSampleTranscript();
    const onClose = vi.fn();

    await act(async () =>
      root.render(
        <TranscriptReader
          isOpen={true}
          onClose={onClose}
          transcript={transcript}
        />,
      ),
    );

    const searchInput = document.querySelector<HTMLInputElement>(
      'input[aria-label="Search transcript"]',
    );
    expect(searchInput).not.toBeNull();

    await act(async () => {
      searchInput!.value = "timing";
      searchInput!.dispatchEvent(new Event("input", { bubbles: true }));
      searchInput!.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const matchBadge = document.querySelector('[role="status"]');
    expect(matchBadge?.textContent).toContain("1 match");

    const highlights = document.querySelectorAll("mark");
    expect(highlights.length).toBeGreaterThan(0);
    expect(highlights[0].textContent?.toLowerCase()).toBe("timing");
  });

  it("highlights report findings in context: done well, pushback, missed chance", async () => {
    const transcript = createSampleTranscript();
    const report = createSampleReport();
    const onClose = vi.fn();

    await act(async () =>
      root.render(
        <TranscriptReader
          isOpen={true}
          onClose={onClose}
          transcript={transcript}
          report={report}
        />,
      ),
    );

    // Done well callout
    const strengthCallout = document.querySelector('aside[data-kind="good"]');
    expect(strengthCallout).not.toBeNull();
    expect(strengthCallout?.textContent).toContain("Done well");
    expect(strengthCallout?.textContent).toContain(
      "Confirm the follow-up time",
    );

    // Pushback callout
    const objectionCallout = document.querySelector(
      'aside[data-kind="objection"]',
    );
    expect(objectionCallout).not.toBeNull();
    expect(objectionCallout?.textContent).toContain("Pushback");
    expect(objectionCallout?.textContent).toContain("Timing uncertainty");

    // Missed chance callout
    const missedCallout = document.querySelector('aside[data-kind="missed"]');
    expect(missedCallout).not.toBeNull();
    expect(missedCallout?.textContent).toContain("Missed chance");
    expect(missedCallout?.textContent).toContain(
      "Ask why timeline is uncertain",
    );
  });

  it("provides jump to moment selector that targets specific segments", async () => {
    const transcript = createSampleTranscript();
    const report = createSampleReport();
    const onClose = vi.fn();

    const scrollIntoViewMock = vi.fn();
    const originalScroll = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrollIntoViewMock;

    try {
      await act(async () =>
        root.render(
          <TranscriptReader
            isOpen={true}
            onClose={onClose}
            transcript={transcript}
            report={report}
          />,
        ),
      );

      const jumpSelect = document.querySelector<HTMLSelectElement>(
        'select[aria-label="Jump to moment"]',
      );
      expect(jumpSelect).not.toBeNull();
      expect(jumpSelect?.options.length).toBeGreaterThan(1);

      // Select the strength moment (start_ms: 6500)
      await act(async () => {
        jumpSelect!.value = "6500";
        jumpSelect!.dispatchEvent(new Event("change", { bubbles: true }));
      });

      expect(scrollIntoViewMock).toHaveBeenCalled();
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScroll;
    }
  });

  it("plays audio from turn when onSeek is provided", async () => {
    const transcript = createSampleTranscript();
    const onSeek = vi.fn();

    await act(async () =>
      root.render(
        <TranscriptReader
          isOpen={true}
          onClose={() => {}}
          transcript={transcript}
          onSeek={onSeek}
          audioAvailable={true}
        />,
      ),
    );

    const playButtons = document.querySelectorAll<HTMLButtonElement>(
      'button[aria-label^="Play audio from"]',
    );
    expect(playButtons.length).toBeGreaterThan(0);

    await act(async () => playButtons[0].click());
    expect(onSeek).toHaveBeenCalledWith(0);
  });

  it("renders skeletons without layout shift when transcript is loading", async () => {
    await act(async () =>
      root.render(
        <TranscriptReader isOpen={true} onClose={() => {}} transcript={null} />,
      ),
    );

    const skeletons = document.querySelectorAll(
      '[aria-label="Loading transcript"]',
    );
    expect(skeletons.length).toBe(1);
  });
});
