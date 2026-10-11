// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { normalizeBundle, normalizeCall } from "./call-data";
import { ReviewScreen } from "./review-screen";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
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

async function render() {
  await act(async () =>
    root.render(
      <ReviewScreen
        call={call}
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
