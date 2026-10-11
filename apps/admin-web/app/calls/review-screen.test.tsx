// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { normalizeBundle, normalizeCall } from "./call-data";
import { ReviewScreen } from "./review-screen";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const call = normalizeCall({
  recording_id: "rec-1",
  organisation: { id: "o1", name: "Synthetic Team" },
  rep: { label: "Asha Synthetic", person_id: "p1" },
  status: "ready",
  runs: [
    {
      id: "run-1",
      state: "completed",
      report_id: "rep-1",
      prompt_revision: "coaching-v5",
      model: "pro",
    },
    {
      id: "run-0",
      state: "completed",
      report_id: "rep-0",
      prompt_revision: "coaching-v4",
    },
  ],
});
const bundle = normalizeBundle({
  run_id: "run-1",
  report: {
    summary: "Opened warmly; no dated next step.",
    summary_evidence: [
      {
        segment_id: "s2",
        quote: "कितने का पड़ेगा?",
        start_ms: 4000,
        end_ms: 6000,
      },
    ],
    verdict: "Follow-up without a date.",
    strengths: [],
    improvements: [],
    dimensions: [],
    call_map: {
      speakers: [
        { speaker_id: "A", role: "seller" },
        { speaker_id: "B", role: "prospect" },
      ],
    },
  },
  transcript: {
    segments: [
      {
        id: "s1",
        speaker_id: "A",
        start_ms: 0,
        end_ms: 4000,
        text: "Namaste, kaise hain?",
      },
      {
        id: "s2",
        speaker_id: "B",
        start_ms: 4000,
        end_ms: 6000,
        text: "कितने का पड़ेगा?",
      },
    ],
  },
  waveform: {
    duration_ms: 10_000,
    points: [
      { start_ms: 0, level: 0.5 },
      { start_ms: 5000, level: 1 },
    ],
  },
  metrics: {
    time_used_ms: 6000,
    speakers: {
      A: { talk_ms: 4000, talk_share: 0.67, questions: 1, cut_ins: 0 },
      B: { talk_ms: 2000, talk_share: 0.33, questions: 1, cut_ins: 0 },
    },
  },
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  push.mockReset();
  Object.defineProperty(HTMLMediaElement.prototype, "paused", {
    configurable: true,
    get: () => true,
  });
  HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
  HTMLMediaElement.prototype.pause = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

async function render(shown = call, startMs: number | null = null) {
  await act(async () =>
    root.render(
      <ReviewScreen
        startMs={startMs}
        call={shown}
        bundle={bundle}
        compare={null}
        compareBundle={null}
        back="status=ready"
        neighbours={{ previous: null, next: "rec-2" }}
      />,
    ),
  );
}
const key = (value: string) =>
  act(async () => {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: value, bubbles: true }),
    );
  });

it("shows the call whole: rep, organisation, speakers, report and the admin audio route", async () => {
  await render();
  expect(host.querySelector("h1")?.textContent).toBe("Asha Synthetic");
  expect(host.textContent).toContain("Synthetic Team");
  expect(host.textContent).toContain("Rep");
  expect(host.textContent).toContain("Prospect");
  expect(host.textContent).toContain("Opened warmly");
  expect(host.querySelector("audio")?.getAttribute("src")).toBe(
    "/v1/admin/conversation/runs/run-1/source",
  );
  expect(
    host.querySelectorAll(".lines li, ol[aria-label='Transcript'] li"),
  ).toHaveLength(2);
  expect(host.querySelector('a[href^="/calls?status=ready"]')).not.toBeNull();
});

it("plays from a transcript line and from a report quote", async () => {
  await render();
  const audio = host.querySelector("audio")!;
  const second = host.querySelector<HTMLButtonElement>(
    '[data-segment="s2"] button',
  )!;
  await act(async () => second.click());
  expect(audio.currentTime).toBe(4);
  await act(async () => (audio.currentTime = 0));
  const quote = Array.from(host.querySelectorAll("button")).find(
    (button) => button.title === "Play from 0:04",
  )!;
  await act(async () => quote.click());
  expect(audio.currentTime).toBe(4);
  expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  expect(
    host.querySelector('[data-segment="s2"][data-focused]'),
  ).not.toBeNull();
});

it("is keyboard-first: views, seeking, help and the next call", async () => {
  await render();
  await key("s");
  expect(host.textContent).toContain("The Big Picture");
  await key("c");
  expect(host.textContent).toContain("has no coaching section");
  await key("u");
  expect(host.textContent).toContain("Compare with open run");
  await key("ArrowRight");
  expect(host.querySelector("audio")!.currentTime).toBe(5);
  await key("?");
  expect(host.textContent).toContain("Play or pause");
  await key("n");
  expect(push).toHaveBeenCalledWith("/calls/rec-2?back=status%3Dready");
});

it("never acts on keys typed into a field", async () => {
  await render();
  const input = document.createElement("input");
  host.append(input);
  input.focus();
  await act(async () => {
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "s", bubbles: true }),
    );
  });
  expect(host.textContent).not.toContain("The Big Picture");
});

it("finds lines in the transcript and counts them", async () => {
  await render();
  const find = host.querySelector<HTMLInputElement>(
    'input[aria-label="Find in transcript"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(find, "कितने");
    find.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(
    host.querySelector('[data-segment="s1"]')?.hasAttribute("hidden"),
  ).toBe(true);
  expect(
    host.querySelector('[data-segment="s2"]')?.hasAttribute("hidden"),
  ).toBe(false);
  expect(host.textContent).toContain("1 line");
});

it("points to a failed step and offers the admin retry only where it is safe", async () => {
  await render({
    ...call,
    failedJobs: [
      {
        jobId: "job-1",
        stage: "C5",
        recordingId: "rec-1",
        attempts: 3,
        code: "provider_timeout",
        failedAt: "2026-10-11T03:00:00Z",
        retryable: true,
      },
      {
        jobId: "job-2",
        stage: "C2",
        recordingId: "rec-1",
        attempts: 1,
        code: "withheld",
        failedAt: null,
        retryable: false,
      },
    ],
  });
  const chip = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "2 failed steps",
  );
  expect(chip).toBeTruthy();
  await act(async () => chip!.click());
  const failed = host.querySelector('[aria-label="Failed steps"]');
  expect(failed?.textContent).toContain("Report");
  expect(failed?.textContent).toContain("provider_timeout");
  expect(failed?.textContent).toContain("reached a provider");
  // Only the step that never reached a provider gets a Retry button.
  expect(
    [...failed!.querySelectorAll("button")].map((item) => item.textContent),
  ).toEqual(["Retry"]);
  // Re-running a finished call stays an unbuilt, disabled command.
  const rerun = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Re-run",
  );
  expect(rerun?.disabled).toBe(true);
});

it("shows no failed-step chip when nothing failed", async () => {
  await render();
  expect(host.textContent).not.toContain("failed step");
});

it("opens a shared link at its moment, paused, with that line marked", async () => {
  await render(call, 4500);
  expect(
    host.querySelector('[data-segment="s2"]')?.hasAttribute("data-focused"),
  ).toBe(true);
  expect(host.textContent).toContain("0:04");
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
});

it("copies a link to this moment with Y, without the personal queue filters", async () => {
  const writeText = vi.fn<(text: string) => Promise<void>>(() =>
    Promise.resolve(),
  );
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  await render(call, 4500);
  await key("y");
  expect(writeText).toHaveBeenCalledTimes(1);
  const url = new URL(writeText.mock.calls[0]![0]);
  expect(url.pathname).toBe("/calls/rec-1");
  expect(url.searchParams.get("at")).toBe("4500");
  expect(url.searchParams.get("run")).toBe("run-1");
  expect(url.searchParams.has("back")).toBe(false);
  expect(host.querySelector('[role="status"]')?.textContent).toBe(
    "Link to 0:04 copied",
  );
});

it("shows talk share as one bar, named by role, with the numbers beside it", async () => {
  await render();
  await key("m");
  expect(
    host
      .querySelector('[role="img"][aria-label^="Talk share"]')
      ?.getAttribute("aria-label"),
  ).toBe("Talk share: Rep 67%, Prospect 33%");
});

it("compares two runs word by word and can show only what changed", async () => {
  const older = normalizeBundle({
    run_id: "run-0",
    report: {
      summary: "Opened coldly; no dated next step.",
      verdict: "Follow-up without a date.",
    },
    transcript: { segments: [] },
  });
  await act(async () =>
    root.render(
      <ReviewScreen
        call={call}
        bundle={bundle}
        compare="run-0"
        compareBundle={older}
        back=""
        neighbours={{ previous: null, next: null }}
      />,
    ),
  );
  const table = host.querySelector('[aria-label="Run comparison"]')!;
  expect(
    [...table.querySelectorAll("mark")].map((mark) => mark.textContent),
  ).toEqual(["warmly; ", "coldly; "]);
  expect(host.textContent).toMatch(/\d+ of \d+ fields changed/);
  const rowsBefore = table.querySelectorAll("tbody tr").length;
  const only = [...host.querySelectorAll("label")]
    .find((label) => label.textContent?.includes("Only changed fields"))!
    .querySelector("input")!;
  await act(async () => only.click());
  const rowsAfter = table.querySelectorAll("tbody tr");
  expect(rowsAfter.length).toBeLessThan(rowsBefore);
  expect([...rowsAfter].every((row) => row.hasAttribute("data-changed"))).toBe(
    true,
  );
});
