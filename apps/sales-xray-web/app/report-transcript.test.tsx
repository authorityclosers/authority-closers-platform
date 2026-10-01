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
import { saveSpeakerProfiles } from "./speaker-profiles";

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
  inline = reading,
  callId: string | null = null,
) {
  await act(async () =>
    root.render(
      <ReportReadingProvider reading={reading} inline={inline}>
        <ReportTranscript
          key={language}
          transcript={transcript}
          onSelect={onSelect}
          language={language}
          callId={callId}
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
  it("opens the transcript in a section tab without losing phrase search or source selection", async () => {
    const transcript = transcriptWithSegments(3);
    const onSelect = await render(transcript, undefined, "en", false, true);
    expect(container.querySelector("details")?.open).toBe(true);
    expect(container.querySelector("summary")?.hidden).toBe(true);
    const search = container.querySelector<HTMLInputElement>(
      'input[aria-label="Search transcript phrases"]',
    )!;
    expect(search.closest("[hidden]")).toBeNull();
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set?.call(search, "phrase 2");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(container.querySelectorAll("[data-segment-id]")).toHaveLength(1);
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-segment-id="segment-2"]')!
        .click(),
    );
    expect(onSelect).toHaveBeenCalledWith(transcript.segments[1]);
  });

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
    // Visible clocks never show milliseconds; long calls read as h:mm:ss.
    expect(formatTranscriptTime(61_234)).toBe("01:01");
    expect(formatTranscriptTime(3_597_994)).toBe("59:57");
    expect(formatTranscriptTime(3_723_000)).toBe("1:02:03");

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

it("shows the names and colours set on the call map", async () => {
  localStorage.clear();
  const callId = "3d2c1b0a-9f8e-4d7c-8b6a-5f4e3d2c1b0a";
  saveSpeakerProfiles(callId, {
    "speaker-2": { name: "Nandlal ji", role: "prospect", icon: null },
  });
  await act(async () =>
    root.render(
      <ReportReadingProvider reading inline>
        <ReportTranscript
          transcript={transcriptWithSegments(2)}
          onSelect={vi.fn()}
          callId={callId}
        />
      </ReportReadingProvider>,
    ),
  );
  const names = [...container.querySelectorAll<HTMLElement>("[data-named]")];
  expect(names.map((name) => name.textContent)).toEqual([
    "Speaker 1",
    "Nandlal ji",
  ]);
  expect(names[1].style.getPropertyValue("--voice")).not.toBe("");
  expect(container.textContent).toContain("Names come from the call map");
  expect(
    [...container.querySelectorAll("option")].map(
      (option) => option.textContent,
    ),
  ).toEqual(["All speakers", "Speaker 1", "Nandlal ji"]);
  localStorage.clear();
});

it("shows brand logos only for a confirmed prospect mention", async () => {
  localStorage.clear();
  const callId = "fictional-brand-attribution-test";
  saveSpeakerProfiles(callId, {
    "speaker-1": { name: "Seller", role: "salesperson", icon: null },
    "speaker-2": { name: "Prospect", role: "prospect", icon: null },
  });
  const source = transcriptWithSegments(2);
  source.segments[0].text = "We use WhatsApp.";
  source.segments[1].text = "I use WhatsApp.";
  await render(source, undefined, "en", true, true, callId);
  const segments = [
    ...container.querySelectorAll<HTMLElement>("[data-segment-id]"),
  ];
  expect(segments[0].querySelector('[data-kind="brand"]')).toBeNull();
  expect(segments[1].querySelector('[data-kind="brand"]')).not.toBeNull();

  await act(async () => root.render(null));
  localStorage.clear();
  await render(source, undefined, "en", true, true, null);
  expect(container.querySelector('[data-kind="brand"]')).toBeNull();
  localStorage.removeItem(`ac.xray.speakers.v1:${callId}`);
});

it("keeps prospect brand mentions eligible while excluding unconfirmed voices", async () => {
  localStorage.clear();
  const callId = "fictional-brand-role-matrix";
  saveSpeakerProfiles(callId, {
    "speaker-1": { name: "Seller", role: "salesperson", icon: null },
    "speaker-2": { name: "Prospect", role: "prospect", icon: null },
  });
  const source = transcriptWithSegments(2);
  source.segments[0].text = "My colleague uses WhatsApp.";
  source.segments[1].text = "My brother uses WhatsApp.";
  await render(source, undefined, "en", true, true, callId);
  let segments = [
    ...container.querySelectorAll<HTMLElement>("[data-segment-id]"),
  ];
  expect(segments[0].querySelector('[data-kind="brand"]')).toBeNull();
  expect(segments[1].querySelector('[data-kind="brand"]')).not.toBeNull();

  await act(async () => root.render(null));
  localStorage.clear();
  saveSpeakerProfiles(callId, {
    "speaker-1": { name: "Seller", role: "salesperson", icon: null },
    "speaker-2": { name: "Prospect", role: "prospect", icon: null },
  });
  const threeVoices = transcriptWithSegments(3);
  threeVoices.segments[0].text = "We can discuss the next step.";
  threeVoices.segments[1].text = "I will review the details.";
  threeVoices.segments[2].speaker_id = "speaker-3";
  threeVoices.segments[2].text = "My friend uses WhatsApp.";
  await render(threeVoices, undefined, "en", true, true, callId);
  segments = [...container.querySelectorAll<HTMLElement>("[data-segment-id]")];
  expect(segments[2].textContent).toContain("My friend uses WhatsApp.");
  expect(segments[2].querySelector('[data-kind="brand"]')).toBeNull();

  await act(async () => root.render(null));
  localStorage.clear();
  saveSpeakerProfiles(callId, {
    "speaker-1": { name: "Speaker 1", role: null, icon: null },
    "speaker-2": { name: "Speaker 2", role: null, icon: null },
  });
  const unknownRole = transcriptWithSegments(2);
  unknownRole.segments[0].text = "We can discuss the next step.";
  unknownRole.segments[1].text = "My brother uses WhatsApp.";
  await render(unknownRole, undefined, "en", true, true, callId);
  segments = [...container.querySelectorAll<HTMLElement>("[data-segment-id]")];
  expect(segments[1].textContent).toContain("My brother uses WhatsApp.");
  expect(segments[1].querySelector('[data-kind="brand"]')).toBeNull();
  localStorage.removeItem(`ac.xray.speakers.v1:${callId}`);
});
