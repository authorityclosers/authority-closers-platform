import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { MissingCall } from "../../capture-setup/capture-setup-client";
import { runRecordingUpload } from "../../leads/simulated-call";
import { readAutoAnalysis } from "../../settings/auto-analysis-client";
import { track } from "../../telemetry";
import { resetBackCloseForTests } from "../../ui/back-close";
import { scanOldCalls } from "./old-calls-client";
import {
  autoCalls,
  buckets,
  cardWords,
  consentPath,
  joinFound,
  lookBackDays,
  mergeMissing,
  parseFound,
  quietLookDue,
  type OldCallsScan,
} from "./old-calls-rules";
import { OldCallsSheet } from "./old-calls-sheet";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Fictional calls and leads only.
const rec = (name: string, extra: Record<string, unknown> = {}) => ({
  source: `media:${name}`,
  name,
  size: 1_000,
  durationMs: 60_000,
  ext: "m4a",
  mime: "audio/mp4",
  supported: true,
  ...extra,
});
const missing: MissingCall[] = [
  {
    event_id: "e1",
    lead_id: "l1",
    lead_name: "asha fictional",
    at: "2026-11-19T06:00:00Z",
    seconds: 120,
  },
  {
    event_id: "e2",
    lead_id: "l2",
    lead_name: "ravi fictional",
    at: "2026-11-18T06:00:00Z",
    seconds: 60,
  },
  {
    event_id: "e3",
    lead_id: "l3",
    lead_name: "meera fictional",
    at: "2026-11-17T06:00:00Z",
    seconds: 90,
  },
];
const reply = {
  access: "ok",
  scanned: 47,
  items: [
    { eventId: "e1", fit: "number", recording: rec("a.m4a") },
    { eventId: "e2", fit: "contact", recording: rec("b.m4a") },
    { eventId: "e3", fit: "time", recording: rec("c.m4a") },
    { eventId: "gone", fit: "number", recording: rec("d.m4a") },
  ],
  unmatched: [{ startedMs: 1, seconds: 30, recording: rec("e.m4a") }],
};

it("joins only the server's calls without a recording to the phone's matches", () => {
  const found = parseFound(reply)!;
  const calls = joinFound(missing, found);
  expect(calls.map((call) => call.eventId)).toEqual(["e1", "e2", "e3"]);
  expect(buckets(calls)).toEqual({ sure: 1, likely: 1, time: 1 });
  // A time-only match never goes up by itself.
  expect(autoCalls(calls).map((call) => call.eventId)).toEqual(["e1", "e2"]);
  // A silent recording is never offered.
  const silent = parseFound({
    ...reply,
    items: [
      {
        eventId: "e1",
        fit: "number",
        recording: rec("a.m4a", {
          check: { verdict: "silent", speechSeconds: 0, measuredSeconds: 60 },
        }),
      },
    ],
  })!;
  expect(joinFound(missing, silent)).toEqual([]);
  expect(parseFound({ nope: 1 })).toBeNull();
});

it("looks back 14 India days and keeps each missing call once", () => {
  const days = lookBackDays(new Date("2026-11-20T20:00:00Z"));
  expect(days[0]).toBe("2026-11-21");
  expect(days).toHaveLength(14);
  expect(mergeMissing([missing, missing.slice(0, 1), null])).toHaveLength(3);
});

it("goes by itself only under standing consent", () => {
  expect(consentPath(null)).toBe("ask");
  expect(
    consentPath({
      schema: "sales-xray-auto-analysis/1",
      state: "on",
      can_start: true,
    }),
  ).toBe("auto");
  expect(
    consentPath({
      schema: "sales-xray-auto-analysis/1",
      state: "off",
      can_start: false,
    }),
  ).toBe("ask");
});

it("words the card for a first look, new calls and nothing new", () => {
  expect(cardWords({ scannedAt: null, fresh: 0 }).button).toBe("Look now");
  expect(cardWords({ scannedAt: 1, fresh: 3 }).title).toBe(
    "3 new recorded calls found",
  );
  expect(cardWords({ scannedAt: 1, fresh: 0 }).quiet).toBe(true);
  expect(quietLookDue(null, 0)).toBe(true);
  expect(quietLookDue(1_000, 2_000)).toBe(false);
});

vi.mock("./old-calls-client", async (original) => ({
  ...(await original<typeof import("./old-calls-client")>()),
  scanOldCalls: vi.fn(),
}));
vi.mock("../../settings/auto-analysis-client", async (original) => ({
  ...(await original<typeof import("../../settings/auto-analysis-client")>()),
  readAutoAnalysis: vi.fn(),
}));
vi.mock("../../leads/simulated-call", async (original) => ({
  ...(await original<typeof import("../../leads/simulated-call")>()),
  readUploadPolicy: vi.fn(async () => ({
    title: "Recording terms",
    description: "Fictional terms for the test.",
    policy_sha256: "a".repeat(64),
  })),
  runRecordingUpload: vi.fn(async ({ lead }: { lead: unknown }) => lead),
}));
vi.mock("../../leads/native-phone", async (original) => ({
  ...(await original<typeof import("../../leads/native-phone")>()),
  readPhoneRecording: vi.fn(async () => new File(["x"], "a.m4a")),
}));
vi.mock("../../telemetry", async (original) => ({
  ...(await original<typeof import("../../telemetry")>()),
  track: vi.fn(),
}));

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(runRecordingUpload).mockClear();
  vi.mocked(track).mockClear();
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.open = false;
  };
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  resetBackCloseForTests();
});

function scanned(): { scan: OldCallsScan; leads: Record<string, never> } {
  const found = parseFound(reply)!;
  const leads = Object.fromEntries(
    missing.map((call) => [
      call.lead_id,
      { lead: { lead_id: call.lead_id, name: call.lead_name }, events: [] },
    ]),
  );
  return {
    scan: {
      access: "ok",
      scanned: 47,
      missing: 3,
      calls: joinFound(missing, found),
      unplaced: found.unmatched,
    },
    leads: leads as never,
  };
}

async function settle() {
  for (let i = 0; i < 8; i++) await act(async () => await Promise.resolve());
}

const button = (name: RegExp) =>
  [...document.querySelectorAll("button")].find((item) =>
    name.test(item.textContent ?? ""),
  ) as HTMLButtonElement | undefined;

it("asks once, with nothing ticked, when automatic analysis is off", async () => {
  vi.mocked(scanOldCalls).mockResolvedValue(scanned());
  vi.mocked(readAutoAnalysis).mockResolvedValue({
    schema: "sales-xray-auto-analysis/1",
    state: "off",
    can_start: false,
  });
  act(() =>
    root.render(<OldCallsSheet open entry="calls" onClose={() => undefined} />),
  );
  await settle();
  const all = button(/Analyse all 3/);
  expect(all?.disabled).toBe(true);
  expect(button(/Pick calls/)).toBeTruthy();
  expect(button(/Not now/)).toBeTruthy();
  const terms = document.querySelector<HTMLInputElement>(
    'input[type="checkbox"]',
  )!;
  expect(terms.checked).toBe(false);
  expect(runRecordingUpload).not.toHaveBeenCalled();
  act(() => terms.click());
  act(() => all!.click());
  await settle();
  expect(runRecordingUpload).toHaveBeenCalledTimes(3);
  expect(vi.mocked(runRecordingUpload).mock.calls[0]![0]).toMatchObject({
    callEventId: "e1",
    consent: "accepted",
  });
  const stages = vi
    .mocked(track)
    .mock.calls.map((call) => (call[1] as { stage: string }).stage);
  expect(stages).toEqual(
    expect.arrayContaining([
      "scan_started",
      "scan_done",
      "asked",
      "chose_all",
      "done",
    ]),
  );
});

it("analyses sure and likely matches by itself under standing consent, never the time-only one", async () => {
  vi.mocked(scanOldCalls).mockResolvedValue(scanned());
  vi.mocked(readAutoAnalysis).mockResolvedValue({
    schema: "sales-xray-auto-analysis/1",
    state: "on",
    can_start: true,
  });
  act(() =>
    root.render(<OldCallsSheet open entry="card" onClose={() => undefined} />),
  );
  await settle();
  expect(
    vi.mocked(runRecordingUpload).mock.calls.map((call) => call[0].callEventId),
  ).toEqual(["e1", "e2"]);
  expect(vi.mocked(runRecordingUpload).mock.calls[0]![0].consent).toBe(
    "standing",
  );
});
