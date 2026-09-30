// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { OverviewHook } from "./overview-hook";
import type { SalesReport, Transcript } from "./report-contract";
import { ReportReadingProvider } from "./report-reading-context";
import { saveSpeakerProfiles } from "./speaker-profiles";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const callId = "fictional-overview-test";
let root: Root;
let host: HTMLDivElement;

const transcript: Transcript = {
  source_sha256: "0".repeat(64),
  revision: "fictional-transcript-r1",
  timebase_id: "1ms",
  duration_ms: 120_000,
  segments: [
    {
      id: "before",
      speaker_id: "alex",
      start_ms: 10_000,
      end_ms: 20_000,
      text: "Is that right? And when?",
    },
    {
      id: "switch",
      speaker_id: "sam",
      start_ms: 25_000,
      end_ms: 30_000,
      text: "I need a different approach.",
    },
    {
      id: "after",
      speaker_id: "alex",
      start_ms: 40_000,
      end_ms: 50_000,
      text: "Let's look at another option.",
    },
    {
      id: "outcome",
      speaker_id: "sam",
      start_ms: 50_000,
      end_ms: 60_000,
      text: "That works for me.",
    },
  ],
};

const evidence = (segment_id: string, start_ms: number, end_ms: number) => ({
  segment_id,
  quote: "Fictional source phrase.",
  start_ms,
  end_ms,
});

const report = {
  overview: {
    version: "dipak-14-point-v1",
    diagnosis: {
      text: "A fictional call summary.",
      evidence: [evidence("before", 10_000, 20_000)],
    },
    outcome: {
      kind: "follow_up",
      text: "They agreed to review the option.",
      evidence: [evidence("outcome", 50_000, 60_000)],
    },
    strength_details: [],
    improvement_details: [],
    golden_moments: [],
    missed_details: [],
    prospect_interpretations: [],
    rewatch: [],
    conversation_change: {
      before: {
        text: "The call began with a question.",
        evidence: [evidence("before", 10_000, 20_000)],
      },
      change: {
        text: "The prospect raised a concern.",
        evidence: [evidence("switch", 25_000, 30_000)],
      },
      after: {
        text: "They considered another option.",
        evidence: [evidence("after", 40_000, 50_000)],
      },
      possible_effect: "The discussion moved to another option.",
      interpretation_kind: "inference",
    },
    ethics_notes: [],
    next_call_focus: null,
    practice: null,
    progress: null,
    final_assessment: {
      repeat: "Ask clear questions.",
      fix_first: "Keep the discussion focused.",
      next_focus: "Confirm the next step.",
      assessment: "Fictional assessment.",
    },
  },
  summary: "A fictional call summary.",
  strengths: [],
  missed_opportunities: [],
  improvements: [],
  objection_analysis: [],
  closing_analysis: [],
  verdict: "Fictional verdict.",
  review_status: "draft_not_dipak_adjudicated",
  source_label: "Fictional call",
  source_sha256: "0".repeat(64),
  transcript_revision: "fictional-transcript-r1",
  dimensions: [],
  report_sections: [],
} as unknown as SalesReport;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  saveSpeakerProfiles(callId, {
    alex: { name: "Alex", role: "salesperson", icon: null },
    sam: { name: "Sam", role: "prospect", icon: null },
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  localStorage.removeItem(`ac.xray.speakers.v1:${callId}`);
});

async function renderOverview() {
  await act(async () =>
    root.render(
      <ReportReadingProvider reading={false}>
        <OverviewHook
          report={report}
          transcript={transcript}
          callId={callId}
          onSeek={() => undefined}
        />
      </ReportReadingProvider>,
    ),
  );
}

describe("OverviewHook phase cards", () => {
  it("uses neutral phase titles and counts each seller question", async () => {
    await renderOverview();
    const before = host.querySelector('ol li[data-phase="before"]')!;
    const after = host.querySelector('ol li[data-phase="after"]')!;

    expect(before.textContent).toContain("Before the switch");
    expect(after.textContent).toContain("After the switch");
    const questionLabel = [...before.querySelectorAll("small")].find(
      (label) => label.textContent === "questions you asked",
    );
    expect(questionLabel?.previousElementSibling?.textContent).toBe("2");
    expect(host.textContent).not.toMatch(
      /They opened up|A real two-way talk|You did almost all the talking/,
    );
    expect(
      host.querySelectorAll(
        'ol li[data-feel="good"], ol li[data-feel="ok"], ol li[data-feel="bad"]',
      ),
    ).toHaveLength(0);
  });

  it("names the outcome marker with its playback time", async () => {
    await renderOverview();
    const button = host.querySelector<HTMLButtonElement>(
      'button[aria-label^="Play the outcome ·"]',
    )!;

    expect(button.getAttribute("aria-label")).toBe("Play the outcome · 00:50");
    expect(button.title).toBe("Play the outcome · 00:50");
  });
});
