import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { resetBackCloseForTests } from "../ui/back-close";
import { History } from "./lead-sheet";
import type { LeadEvent } from "./leads-client";
import { parseCallLog, parseRecorder, parseSetup } from "./native-phone";
import {
  lineTodo,
  needsAllFiles,
  needsFolderPick,
  PhoneSetupBar,
  setupLines,
} from "./phone-setup";
import {
  ALL_FILES_EXPLAINER,
  CHECK_TODO,
  FOLDER_TODO,
  HIDDEN_TODO,
  recorderGuide,
} from "./phone-setup-words";

/**
 * Xiaomi's hidden recordings folder (Redmi audit #49), Truecaller's note
 * (#48), and a dialer call's recording joining its own row on the lead (#55).
 */

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ children }: { children: unknown }) => children,
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

const CHECKS = {
  calls: true,
  recordings: false,
  notifications: true,
  recorder: true,
  folder: false,
  battery: true,
  autostart: true,
  testCall: false,
  callLog: true,
};

/** The Redmi 13: HyperOS hides MIUI/sound_recorder until All files access is on. */
const HYPEROS = {
  checks: CHECKS,
  family: "xiaomi",
  model: "Redmi 13 5G",
  autostartNeeded: true,
  version: "0.3.80",
  device: "5c0de5a7-0000-4000-8000-00000000d5c6",
  needsAllFiles: true,
  allFilesSupported: true,
  truecaller: true,
  recorderProfile: {
    kind: "folder",
    maker: "xiaomi",
    dialerLabel: "Phone",
    recording: "unknown",
    folders: [{ path: "MIUI/sound_recorder/call_rec", state: "hidden" }],
    otherDialers: [],
  },
};

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  localStorage.clear();
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close() {
    this.removeAttribute("open");
  };
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () => new Response("{}")),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  resetBackCloseForTests();
});

const button = (label: string) =>
  [...document.querySelectorAll("button")].find((item) =>
    item.textContent?.startsWith(label),
  );

const lines = () => [
  ...document.querySelectorAll('ol[aria-label="Phone setup"] li'),
];

it("reads the new setup fields, and an older app sends none", () => {
  const status = parseSetup(HYPEROS)!;
  expect(status).toMatchObject({
    needsAllFiles: true,
    allFilesSupported: true,
    truecaller: true,
  });
  const old = parseSetup({ checks: CHECKS, family: "xiaomi" })!;
  expect(old).toMatchObject({
    needsAllFiles: false,
  });
  expect(lineTodo("recordings", status)).toBe(HIDDEN_TODO);
});

it("asks the Play build to pick the recordings folder, which then clears it (S8)", () => {
  const play = parseSetup({
    ...HYPEROS,
    allFilesSupported: false,
    folderPickSupported: true,
    store: "play",
  })!;
  expect(play).toMatchObject({
    folderPickSupported: true,
    folderPicked: false,
  });
  expect(needsAllFiles(play)).toBe(false);
  expect(needsFolderPick(play)).toBe(true);
  expect(lineTodo("recordings", play)).toBe(FOLDER_TODO);
  const picked = parseSetup({
    ...HYPEROS,
    allFilesSupported: false,
    folderPickSupported: true,
    folderPicked: true,
    needsAllFiles: false,
  })!;
  expect(needsFolderPick(picked)).toBe(false);
  expect(lineTodo("recordings", picked)).toBe(CHECK_TODO.recordings);
  // An older Play build without the picker says nothing it can't do.
  const older = parseSetup({ ...HYPEROS, allFilesSupported: false })!;
  expect(needsFolderPick(older)).toBe(false);
});

it("leaves out work-call logging in the Play build of the app", () => {
  const play = parseSetup({
    ...HYPEROS,
    callLogSupported: false,
    store: "play",
  })!;
  expect(play.store).toBe("play");
  expect(setupLines(play)).not.toContain("callLog");
  const direct = parseSetup(HYPEROS)!;
  expect(direct.store).toBe("direct");
  expect(setupLines(direct)).toContain("callLog");
  // The Play build's call-log status says it's unsupported: no logging card.
  expect(parseCallLog({ on: false, supported: false, sims: [] })).toBeNull();
  expect(parseCallLog({ on: false, sims: [] })?.on).toBe(false);
});

it("says the recorder folder is hidden, not empty", () => {
  const guide = recorderGuide(parseRecorder(HYPEROS.recorderProfile), "xiaomi");
  expect(guide.lead).toContain("hides from other apps");
  expect(guide.lead).toContain("All files access");
});

it("asks a Xiaomi phone for All files access on the Call recordings line", async () => {
  const sent = fakePhone((message) =>
    message.method === "setupStatus" || message.method === "setupOpen"
      ? message.method === "setupOpen"
        ? { opened: true }
        : HYPEROS
      : {},
  );
  window.history.replaceState(null, "", "/leads#phone-setup");
  await act(async () => root.render(<PhoneSetupBar />));
  for (let i = 0; i < 10; i++) await act(async () => await Promise.resolve());
  const recordings = lines()[1];
  expect(recordings.textContent).toContain(HIDDEN_TODO);
  await act(async () => recordings.querySelector("button")!.click());
  for (let i = 0; i < 10; i++) await act(async () => await Promise.resolve());
  // The flow's screen keeps Google Play's words before Android's screen opens.
  expect(document.body.textContent).toContain(ALL_FILES_EXPLAINER.reads);
  await act(async () => button("Open All files access")!.click());
  for (let i = 0; i < 10; i++) await act(async () => await Promise.resolve());
  expect(
    sent.filter((item) => item.method === "setupOpen").map((item) => item.args),
  ).toEqual([{ what: "allFiles" }]);
  // Truecaller is on this phone: the checklist says how to get past its screen.
  await act(async () => button("Later")!.click());
  for (let i = 0; i < 10; i++) await act(async () => await Promise.resolve());
  expect(document.body.textContent).toContain("Truecaller");
  window.history.replaceState(null, "", "/leads");
});

const phoneCall = (extra: Partial<LeadEvent>): LeadEvent => ({
  kind: "call",
  at: "2026-10-22T02:44:21Z",
  actor_name: "Asha",
  stage: null,
  stage_label: null,
  reason: null,
  reason_label: null,
  connected: true,
  note: null,
  next_action_at: null,
  owner_name: null,
  previous_owner_name: null,
  allocation_reason: null,
  source_label: null,
  submission_id: null,
  simulated: null,
  duration_seconds: 134,
  via: "phone",
  direction: "outgoing",
  event_id: "22222222-2222-4222-8222-222222222222",
  can_hide: true,
  private: false,
  ...extra,
});

it("shows a dialer call with its recording as one row with its Report", async () => {
  await act(async () =>
    root.render(
      <History
        events={[
          phoneCall({
            recording: true,
            submission_id: "33333333-3333-4333-8333-333333333333",
          }),
        ]}
      />,
    ),
  );
  // The first event's row (a day header sits above it since 22 Oct 2026).
  const row = host.querySelector("li:not([aria-hidden])")!;
  expect(row.textContent).toContain("Asha called · 2:14");
  expect(row.textContent).toContain("From the phone dialer · recorded");
  expect(row.textContent).toContain("Open the call's Report");
  expect(row.textContent).not.toContain("added the call recording");
});
