import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { resetBackCloseForTests } from "../ui/back-close";
import type { Desk, LeadDetail } from "./leads-client";
import {
  checkWarning,
  parseCheck,
  parsePending,
  type PendingRecording,
} from "./native-phone";
import {
  hiddenRecordings,
  readyCalls,
  RecordedCallsCard,
  recordedLine,
  silentCalls,
} from "./recorded-calls";
import { runRecordingUpload } from "./simulated-call";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
}));

vi.mock("./leads-client", async (original) => ({
  ...(await original<typeof import("./leads-client")>()),
  readLead: vi.fn(async (leadId: string) => ({
    lead: { lead_id: leadId, name: "kavya rao" },
    events: [],
  })),
}));

vi.mock("./simulated-call", async (original) => ({
  ...(await original<typeof import("./simulated-call")>()),
  readUploadPolicy: vi.fn(async () => ({
    title: "Recording terms",
    description: "Fictional terms for the test.",
    policy_sha256: "a".repeat(64),
  })),
  runRecordingUpload: vi.fn(async ({ lead }: { lead: LeadDetail }) => lead),
}));

type Listener = (event: { data: unknown }) => void;
type Sent = { method: string; args: Record<string, unknown> };

function fakePhone(answer: (message: Sent) => unknown) {
  const listeners: Listener[] = [];
  const sent: Sent[] = [];
  vi.stubGlobal("SXPhone", {
    addEventListener: (_: string, listener: Listener) =>
      listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as Sent & { id: string };
      sent.push({ method: message.method, args: message.args });
      const result = answer(message);
      queueMicrotask(() =>
        listeners.forEach((listener) =>
          listener({
            data: JSON.stringify({ id: message.id, ok: true, result }),
          }),
        ),
      );
    },
  });
  return sent;
}

const now = Date.now();
const recording = (name: string, verdict = "ok") => ({
  source: `file:/storage/emulated/0/MIUI/sound_recorder/call_rec/${name}`,
  name,
  size: 21_000,
  durationMs: 0,
  ext: "mp3",
  mime: "audio/mpeg",
  supported: true,
  captured: "dialer",
  check: { verdict, speechSeconds: 40, measuredSeconds: 134 },
});
const PENDING = {
  items: [
    {
      eventId: "e1",
      leadId: "lead-1",
      startedMs: now - 3_600_000,
      seconds: 134,
      direction: "outgoing",
      recording: recording("(00919000000001)_20261022024421.mp3"),
      looking: false,
    },
    {
      eventId: "e2",
      leadId: "lead-2",
      startedMs: now - 1_800_000,
      seconds: 61,
      direction: "incoming",
      recording: recording("(00919000000002)_20261022031602.mp3", "silent"),
      looking: false,
    },
    {
      eventId: "e3",
      leadId: "lead-3",
      startedMs: now - 600_000,
      seconds: 20,
      direction: "outgoing",
      recording: null,
      looking: true,
    },
    { eventId: "bad", leadId: "", direction: "missed" },
  ],
  needsAllFiles: false,
  allFilesSupported: true,
};
const ME: Desk["me"] = {
  person_id: "p1",
  name: "Test Seller",
  role: "member",
  can_manage: false,
};

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close() {
    this.removeAttribute("open");
  };
  vi.mocked(runRecordingUpload).mockClear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  resetBackCloseForTests();
});

const button = (label: string) =>
  [...document.querySelectorAll("button")].find(
    (item) => item.textContent === label,
  );

it("reads the phone's waiting calls and drops odd rows", () => {
  const pending = parsePending(PENDING)!;
  expect(pending.items.map((item) => item.eventId)).toEqual(["e1", "e2", "e3"]);
  expect(pending.items[0].recording?.check?.verdict).toBe("ok");
  expect(parsePending(null)).toBeNull();
  expect(parsePending({ items: "no" })).toBeNull();
  expect(parseCheck({ verdict: "loud" })).toBeNull();
  // Only found, readable, not silent recordings can be analysed.
  expect(readyCalls(pending).map((item) => item.eventId)).toEqual(["e1"]);
  expect(silentCalls(pending).map((item) => item.eventId)).toEqual(["e2"]);
  expect(hiddenRecordings(pending)).toBe(false);
  expect(hiddenRecordings({ ...pending, needsAllFiles: true })).toBe(true);
  expect(
    hiddenRecordings({
      ...pending,
      needsAllFiles: true,
      allFilesSupported: false,
    }),
  ).toBe(false);
});

it("says when a recording is silent or may be one-sided", () => {
  const pending = parsePending(PENDING)!;
  expect(checkWarning(pending.items[0].recording)).toBeNull();
  expect(checkWarning(pending.items[1].recording)).toContain("silent");
  const oneSided = {
    ...pending.items[0].recording!,
    check: {
      verdict: "one_sided" as const,
      speechSeconds: 9,
      measuredSeconds: 60,
    },
  };
  expect(checkWarning(oneSided)).toContain("Only one voice");
  expect(checkWarning(null)).toBeNull();
});

it("describes each call the way the call log does", () => {
  const call = parsePending(PENDING)!.items[0] as PendingRecording;
  expect(recordedLine(call)).toMatch(/^You called · 2:14 · /);
  expect(recordedLine({ ...call, direction: "incoming" })).toMatch(
    /^They called · /,
  );
});

it("shows nothing in a browser", async () => {
  await act(async () => root.render(<RecordedCallsCard me={ME} />));
  expect(host.innerHTML).toBe("");
});

it("analyses a recorded dialer call on its own call, after the terms are agreed", async () => {
  let pending = PENDING;
  const sent = fakePhone((message) => {
    if (message.method === "recordingHandled")
      pending = {
        ...pending,
        items: pending.items.filter(
          (item) => item.eventId !== message.args.eventId,
        ),
      };
    if (message.method === "read")
      return { data: btoa("ID3 fake audio"), eof: true };
    return pending;
  });
  await act(async () => root.render(<RecordedCallsCard me={ME} />));
  expect(host.textContent).toContain("1 lead call recorded");
  await act(async () => button("Analyse")!.click());
  // Names show with capitals; the silent one is flagged, not offered.
  expect(document.body.textContent).toContain("Kavya Rao");
  expect(document.body.textContent).toContain("This recording is silent");
  const analyse = button("Analyse the call")!;
  expect(analyse.disabled).toBe(true);
  const agree = document.querySelector<HTMLInputElement>(
    'input[type="checkbox"]',
  )!;
  await act(async () => agree.click());
  await act(async () => button("Analyse the call")!.click());
  expect(runRecordingUpload).toHaveBeenCalledTimes(1);
  expect(vi.mocked(runRecordingUpload).mock.calls[0][0]).toMatchObject({
    callEventId: "e1",
    attempt: "e1",
    me: { person_id: "p1" },
  });
  expect(
    sent
      .filter((item) => item.method === "recordingHandled")
      .map((item) => item.args),
  ).toEqual([{ eventId: "e1" }]);
  expect(document.body.textContent).toContain("Analysis started");
});

it("asks for All files access when the phone hides its recordings", async () => {
  const sent = fakePhone(() => ({
    items: [PENDING.items[2]],
    needsAllFiles: true,
    allFilesSupported: true,
  }));
  await act(async () => root.render(<RecordedCallsCard me={ME} />));
  expect(host.textContent).toContain("Your phone hides its call recordings");
  await act(async () => button("Allow")!.click());
  expect(
    sent.some(
      (item) => item.method === "setupOpen" && item.args.what === "allFiles",
    ),
  ).toBe(true);
});
