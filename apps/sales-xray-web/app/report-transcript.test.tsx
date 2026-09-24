import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReportFactors } from "./report-factors";
import { formatTranscriptTime, ReportTranscript } from "./report-transcript";
import { ReportReadingProvider } from "./report-reading-context";
import type {
  ReportDimension,
  Transcript,
  TranscriptSegment,
} from "./report-contract";
import type { ReportDisplayLanguage } from "./report-ui-copy";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;

function transcriptWithSegments(count: number): Transcript {
  const segments: TranscriptSegment[] = Array.from(
    { length: count },
    (_, index) => ({
      id: `segment-${index + 1}`,
      speaker_id: index % 2 === 0 ? "speaker-1" : "speaker-2",
      start_ms: index * 1_000,
      end_ms: index * 1_000 + 800,
      text: `Literal source phrase ${index + 1}`,
    }),
  );
  return {
    source_sha256: "0".repeat(64),
    revision: "transcript-test-r1",
    timebase_id: "1ms",
    duration_ms: Math.max(1, count * 1_000),
    segments,
  };
}

async function render(
  transcript: Transcript,
  onSelect = vi.fn<(segment: TranscriptSegment) => void>(),
  language: ReportDisplayLanguage = "en",
  reading = false,
) {
  await act(async () =>
    root.render(
      <ReportReadingProvider reading={reading}>
        <ReportTranscript
          key={language}
          transcript={transcript}
          onSelect={onSelect}
          language={language}
        />
      </ReportReadingProvider>,
    ),
  );
  return onSelect;
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("ReportTranscript", () => {
  it("shows the full transcript in reading mode", async () => {
    await render(transcriptWithSegments(51), undefined, "en", true);

    expect(container.querySelector("details")?.open).toBe(true);
    expect(container.querySelectorAll("[data-segment-id]")).toHaveLength(51);
    expect(container.querySelector(".loadMore")).toBeNull();
  });

  it("expands, searches, filters by unverified speaker label, and returns the source segment", async () => {
    const transcript = transcriptWithSegments(3);
    const onSelect = await render(transcript);
    const details = container.querySelector("details");

    expect(details?.open).toBe(false);
    await act(async () =>
      container
        .querySelector("summary")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true })),
    );
    expect(details?.open).toBe(true);
    expect(container.querySelectorAll("[data-segment-id]")).toHaveLength(3);
    expect(container.textContent).toContain(
      "Speaker labels come from the source and are unverified",
    );
    expect(formatTranscriptTime(61_234)).toBe("01:01.234");

    const search = container.querySelector<HTMLInputElement>(
      'input[aria-label="Search transcript phrases"]',
    );
    expect(search).not.toBeNull();
    if (search) {
      await act(async () => {
        Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )?.set?.call(search, "phrase 2");
        search.dispatchEvent(new Event("input", { bubbles: true }));
      });
    }
    expect(container.querySelectorAll("[data-segment-id]")).toHaveLength(1);
    expect(
      container.querySelector("[data-segment-id=segment-2]"),
    ).not.toBeNull();
    expect(container.textContent).toContain("Literal source phrase 2");

    if (search) {
      await act(async () => {
        Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )?.set?.call(search, "");
        search.dispatchEvent(new Event("input", { bubbles: true }));
      });
    }
    const speaker = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Filter transcript by speaker"]',
    );
    expect(speaker).not.toBeNull();
    if (speaker) {
      await act(async () => {
        speaker.value = "speaker:speaker-2";
        speaker.dispatchEvent(new Event("change", { bubbles: true }));
      });
    }
    expect(container.querySelectorAll("[data-segment-id]")).toHaveLength(1);
    const segmentButton = container.querySelector<HTMLButtonElement>(
      "[data-segment-id=segment-2]",
    );
    expect(segmentButton?.dataset.startMs).toBe("1000");
    expect(segmentButton?.dataset.endMs).toBe("1800");
    await act(async () => segmentButton?.click());
    expect(onSelect).toHaveBeenCalledWith(transcript.segments[1]);
  });

  it("shows at most 50 source rows and loads the next bounded page", async () => {
    const transcript = transcriptWithSegments(51);
    await render(transcript);
    await act(async () =>
      container
        .querySelector("summary")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true })),
    );

    expect(container.querySelectorAll("[data-segment-id]")).toHaveLength(50);
    const loadMore = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Load 1 more",
    );
    expect(loadMore).not.toBeUndefined();
    await act(async () => loadMore?.click());
    expect(container.querySelectorAll("[data-segment-id]")).toHaveLength(51);
    expect(
      container.querySelector("[data-segment-id=segment-51]"),
    ).not.toBeNull();
  });

  it("localizes report controls while preserving source text, speaker IDs, and observations", async () => {
    const transcript = transcriptWithSegments(1);
    const dimension: ReportDimension = {
      dimension_id: "discovery",
      label: "Discovery",
      status: "observed",
      observation: "Literal server observation",
      citations: [],
    };
    const localizedCases: Array<{
      language: ReportDisplayLanguage;
      title: string;
      searchLabel: string;
      factorTitle: string;
      status: string;
    }> = [
      {
        language: "hi",
        title: "पूरा ट्रांसक्रिप्ट पढ़ें",
        searchLabel: "ट्रांसक्रिप्ट खोजें",
        factorTitle: "बिक्री के आयाम देखें",
        status: "साक्ष्य मिला",
      },
      {
        language: "mr",
        title: "संपूर्ण ट्रान्सक्रिप्ट वाचा",
        searchLabel: "ट्रान्सक्रिप्ट शोधा",
        factorTitle: "विक्रीचे आयाम पाहा",
        status: "पुरावा मिळाला",
      },
      {
        language: "en-hi-mixed",
        title: "Read full transcript · पूरा ट्रांसक्रिप्ट पढ़ें",
        searchLabel: "Search transcript · ट्रांसक्रिप्ट खोजें",
        factorTitle: "Explore sales factors · बिक्री के आयाम देखें",
        status: "Evidence found · साक्ष्य मिला",
      },
    ];

    for (const {
      language,
      title,
      searchLabel,
      factorTitle,
      status,
    } of localizedCases) {
      await render(transcript, vi.fn(), language);
      await act(async () =>
        container
          .querySelector("summary")
          ?.dispatchEvent(new MouseEvent("click", { bubbles: true })),
      );

      expect(container.textContent).toContain(title);
      expect(container.textContent).toContain("Literal source phrase 1");
      expect(container.textContent).toContain("speaker-1");
      expect(
        container.querySelector('[role="search"]')?.getAttribute("aria-label"),
      ).toBe(searchLabel);

      await act(async () =>
        root.render(
          <ReportFactors dimensions={[dimension]} language={language} />,
        ),
      );
      expect(container.textContent).toContain(factorTitle);
      expect(container.textContent).toContain(status);
      expect(container.textContent).toContain("Discovery");
      expect(container.textContent).toContain("Literal server observation");
    }
  });

  it("hides the interactive transcript from print output", () => {
    const css = readFileSync(
      join(
        dirname(fileURLToPath(import.meta.url)),
        "report-transcript.module.css",
      ),
      "utf8",
    );
    expect(css).toMatch(/@media print[\s\S]*\.root\s*\{[\s\S]*display:\s*none/);
  });
});
