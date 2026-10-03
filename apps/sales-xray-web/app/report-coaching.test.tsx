import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReportCoaching } from "./report-coaching";
import type { SalesReport } from "./report-contract";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;

const sampleReport: SalesReport = {
  summary: "Sample call summary.",
  strengths: [
    {
      title: "Strong opening question",
      explanation: "Asked clear open question early.",
      evidence: [
        {
          segment_id: "s1",
          start_ms: 1000,
          end_ms: 2000,
          quote: "How does your team handle this today?",
        },
      ],
    },
  ],
  missed_opportunities: [],
  improvements: [
    {
      title: "Check budget earlier",
      explanation: "Waited until late in the call.",
      evidence: [
        {
          segment_id: "s2",
          start_ms: 5000,
          end_ms: 6000,
          quote: "We haven't discussed pricing yet.",
        },
      ],
    },
  ],
  objection_analysis: [],
  closing_analysis: [],
  verdict: "Promising discovery with clear next steps.",
  review_status: "draft_not_dipak_adjudicated",
  source_label: "Test",
  source_sha256: "00".repeat(32),
  transcript_revision: "test-rev-1",
  dimensions: [],
  report_sections: [],
};

beforeEach(() => {
  sessionStorage.clear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  sessionStorage.clear();
});

it("shows only the prompt card and 'Coach me on this call' button initially", async () => {
  await act(async () => {
    root.render(
      <ReportCoaching report={sampleReport} callId="test-call-123" />,
    );
  });

  expect(container.querySelector("[data-coaching-gate]")).not.toBeNull();
  expect(container.textContent).toContain("Want tips for your next call?");
  expect(container.textContent).toContain("Coach me on this call");

  // Coaching details should NOT be visible
  expect(container.querySelector("[data-coaching-content]")).toBeNull();
  expect(container.querySelector('[data-coaching-card="keep"]')).toBeNull();
  expect(container.querySelector('[data-coaching-card="change"]')).toBeNull();
  expect(container.querySelector('[data-coaching-card="next"]')).toBeNull();
});

it("reveals Keep doing, Change first, Next call and Next-call plan when Coach me is clicked", async () => {
  await act(async () => {
    root.render(
      <ReportCoaching report={sampleReport} callId="test-call-123" />,
    );
  });

  const button = container.querySelector<HTMLButtonElement>(
    "button[data-coach-trigger]",
  )!;
  expect(button).not.toBeNull();

  await act(async () => {
    button.click();
  });

  // Prompt card is gone
  expect(container.querySelector("[data-coaching-gate]")).toBeNull();

  // Coaching content is now visible
  expect(container.querySelector("[data-coaching-content]")).not.toBeNull();
  expect(container.querySelector('[data-coaching-card="keep"]')).not.toBeNull();
  expect(container.querySelector('[data-coaching-card="change"]')).not.toBeNull();
  expect(container.querySelector('[data-coaching-card="next"]')).not.toBeNull();

  expect(container.textContent).toContain("Strong opening question");
  expect(container.textContent).toContain("Check budget earlier");

  // Verified in sessionStorage for the session
  expect(sessionStorage.getItem("ac:coaching:test-call-123")).toBe("true");
});

it("remembers coaching choice across re-renders in the same session", async () => {
  sessionStorage.setItem("ac:coaching:persisted-call-456", "true");

  await act(async () => {
    root.render(
      <ReportCoaching report={sampleReport} callId="persisted-call-456" />,
    );
  });

  // Gate card is not shown because session is unlocked
  expect(container.querySelector("[data-coaching-gate]")).toBeNull();
  expect(container.querySelector("[data-coaching-content]")).not.toBeNull();
  expect(container.querySelector('[data-coaching-card="keep"]')).not.toBeNull();
});
