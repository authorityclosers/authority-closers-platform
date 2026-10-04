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
    closing_analysis: [],
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
  it("resets speaker and search state when a different call opens", async () => {
    const transcript = createSampleTranscript();
    const renderCall = async (callId: string, value = transcript) => {
      await act(async () =>
        root.render(
          <TranscriptReader
            isOpen={true}
            onClose={() => {}}
            callId={callId}
            transcript={value}
          />,
        ),
      );
    };
    await renderCall("11111111-1111-4111-8111-111111111111");
    const filter = document.querySelector<HTMLSelectElement>(
      '[aria-label="Filter by speaker"]',
    )!;
    const search = document.querySelector<HTMLInputElement>(
      '[aria-label="Search transcript"]',
    )!;
    await act(async () => {
      filter.value = "prospect";
      filter.dispatchEvent(new Event("change", { bubbles: true }));
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(search, "timing");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(document.querySelectorAll("[data-segment-id]")).toHaveLength(2);
    expect(document.querySelector("[role='status']")?.textContent).toContain(
      "1 match",
    );
    await renderCall("11111111-1111-4111-8111-111111111111");
    expect(filter.value).toBe("prospect");
    expect(search.value).toBe("timing");

    const nextTranscript = {
      ...transcript,
      segments: transcript.segments.map((segment) => ({
        ...segment,
        speaker_id: `next-${segment.speaker_id}`,
      })),
    };
    await renderCall("22222222-2222-4222-8222-222222222222", nextTranscript);
    expect(
      document.querySelector<HTMLSelectElement>(
        '[aria-label="Filter by speaker"]',
      )!.value,
    ).toBe("all");
    expect(
      document.querySelector<HTMLInputElement>(
        '[aria-label="Search transcript"]',
      )!.value,
    ).toBe("");
    expect(document.querySelectorAll("[data-segment-id]")).toHaveLength(4);
    expect(
      document.querySelector("[aria-label='Search match navigation']"),
    ).toBeNull();
  });

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
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set?.call(searchInput, "timing");
      searchInput!.dispatchEvent(new Event("input", { bubbles: true }));
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

  it("focuses search on open, keeps Tab inside and restores focus on close", async () => {
    const transcript = createSampleTranscript();
    const opener = document.createElement("button");
    opener.textContent = "Transcript";
    document.body.appendChild(opener);
    opener.focus();

    try {
      await act(async () =>
        root.render(
          <TranscriptReader
            isOpen={true}
            onClose={() => {}}
            transcript={transcript}
            onSeek={() => {}}
          />,
        ),
      );

      const reader = document.querySelector<HTMLElement>(
        "[data-transcript-reader]",
      )!;
      const search = reader.querySelector<HTMLInputElement>(
        'input[aria-label="Search transcript"]',
      );
      expect(document.activeElement).toBe(search);

      const tab = (shiftKey = false) =>
        act(async () => {
          window.dispatchEvent(
            new KeyboardEvent("keydown", {
              key: "Tab",
              shiftKey,
              bubbles: true,
              cancelable: true,
            }),
          );
        });

      const close = reader.querySelector<HTMLElement>(
        'button[aria-label="Close transcript reader"]',
      )!;
      close.focus();
      await tab(true);
      const lastPlay = Array.from(
        reader.querySelectorAll<HTMLElement>(
          'button[aria-label^="Play audio from"]',
        ),
      ).at(-1);
      expect(document.activeElement).toBe(lastPlay);
      await tab();
      expect(document.activeElement).toBe(close);

      opener.focus();
      await tab();
      expect(reader.contains(document.activeElement)).toBe(true);

      await act(async () =>
        root.render(
          <TranscriptReader
            isOpen={false}
            onClose={() => {}}
            transcript={transcript}
          />,
        ),
      );
      expect(document.activeElement).toBe(opener);
    } finally {
      opener.remove();
    }
  });

  it("returns focus to the menu summary when opened from a closed menu", async () => {
    const menu = document.createElement("details");
    menu.open = true;
    const summary = document.createElement("summary");
    summary.textContent = "More";
    const item = document.createElement("button");
    item.textContent = "Transcript";
    menu.append(summary, item);
    document.body.appendChild(menu);
    item.focus();

    try {
      await act(async () =>
        root.render(
          <TranscriptReader
            isOpen={true}
            onClose={() => {}}
            transcript={createSampleTranscript()}
          />,
        ),
      );
      menu.open = false;
      await act(async () =>
        root.render(
          <TranscriptReader
            isOpen={false}
            onClose={() => {}}
            transcript={createSampleTranscript()}
          />,
        ),
      );
      expect(document.activeElement).toBe(summary);
    } finally {
      menu.remove();
    }
  });

  it("scrolls only the reader's own segment when the page has the same id", async () => {
    const transcript = createSampleTranscript();
    const outside = document.createElement("button");
    outside.setAttribute("data-segment-id", "seg-2");
    const outsideScroll = vi.fn();
    outside.scrollIntoView = outsideScroll;
    const scrollIntoViewMock = vi.fn();
    const originalScroll = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrollIntoViewMock;
    document.body.insertBefore(outside, document.body.firstChild);

    try {
      await act(async () =>
        root.render(
          <TranscriptReader
            isOpen={true}
            onClose={() => {}}
            transcript={transcript}
          />,
        ),
      );
      const searchInput = document.querySelector<HTMLInputElement>(
        'input[aria-label="Search transcript"]',
      )!;
      await act(async () => {
        Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )?.set?.call(searchInput, "timing");
        searchInput.dispatchEvent(new Event("input", { bubbles: true }));
      });
      await act(async () =>
        document
          .querySelector<HTMLButtonElement>('button[aria-label="Next match"]')!
          .click(),
      );

      expect(outsideScroll).not.toHaveBeenCalled();
      expect(scrollIntoViewMock).toHaveBeenCalledOnce();
      const scrolled = scrollIntoViewMock.mock.contexts[0] as HTMLElement;
      expect(scrolled.closest("[data-transcript-reader]")).not.toBeNull();
      expect(scrolled.getAttribute("data-segment-id")).toBe("seg-2");
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScroll;
      outside.remove();
    }
  });

  it("counts and navigates only matches the speaker filter shows", async () => {
    const transcript = createSampleTranscript();

    await act(async () =>
      root.render(
        <TranscriptReader
          isOpen={true}
          onClose={() => {}}
          transcript={transcript}
        />,
      ),
    );
    const searchInput = document.querySelector<HTMLInputElement>(
      'input[aria-label="Search transcript"]',
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set?.call(searchInput, "timing");
      searchInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(document.querySelector('[role="status"]')?.textContent).toBe(
      "1 match",
    );

    const filter = document.querySelector<HTMLSelectElement>(
      'select[aria-label="Filter by speaker"]',
    )!;
    await act(async () => {
      filter.value = "rep";
      filter.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(document.querySelector('[role="status"]')?.textContent).toBe(
      "No matches",
    );
    expect(
      document.querySelector('button[aria-label="Next match"]'),
    ).toBeNull();
    expect(document.querySelectorAll("mark")).toHaveLength(0);

    await act(async () => {
      filter.value = "prospect";
      filter.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(document.querySelector('[role="status"]')?.textContent).toBe(
      "1 match",
    );
    expect(document.querySelectorAll("mark").length).toBeGreaterThan(0);
  });

  it("reveals a jump-to-moment target hidden by the speaker filter", async () => {
    const scrollIntoViewMock = vi.fn();
    const originalScroll = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scrollIntoViewMock;

    try {
      await act(async () =>
        root.render(
          <TranscriptReader
            isOpen={true}
            onClose={() => {}}
            transcript={createSampleTranscript()}
            report={createSampleReport()}
          />,
        ),
      );
      const filter = document.querySelector<HTMLSelectElement>(
        'select[aria-label="Filter by speaker"]',
      )!;
      await act(async () => {
        filter.value = "prospect";
        filter.dispatchEvent(new Event("change", { bubbles: true }));
      });
      expect(document.querySelector('[data-segment-id="seg-3"]')).toBeNull();

      const jumpSelect = document.querySelector<HTMLSelectElement>(
        'select[aria-label="Jump to moment"]',
      )!;
      await act(async () => {
        jumpSelect.value = "6500";
        jumpSelect.dispatchEvent(new Event("change", { bubbles: true }));
      });

      expect(filter.value).toBe("all");
      const scrolled = scrollIntoViewMock.mock.contexts.at(-1) as HTMLElement;
      expect(scrolled.getAttribute("data-segment-id")).toBe("seg-3");
    } finally {
      HTMLElement.prototype.scrollIntoView = originalScroll;
    }
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
