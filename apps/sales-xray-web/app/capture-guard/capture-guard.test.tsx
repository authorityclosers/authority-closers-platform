import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { CaptureAttention, CaptureHealthView } from "./capture-health";
import { CaptureRatesView } from "./capture-rates";
import {
  AutoCaptureState,
  CallTrack,
  CaptureStateLabel,
  trackFor,
} from "../leads/auto-capture-state";
import type { CaptureCall } from "../leads/capture-guard-client";
import { parseSetup, parseRecorder } from "../leads/native-phone";
import { readCaptureGuard } from "../leads/capture-guard-client";
import {
  autoCaptureSetup,
  autoCaptureStates,
  autoCaptureStatus,
} from "../leads/native-phone";
import { AutoCapturePanel } from "../settings/auto-capture-panel";

vi.mock("../leads/capture-guard-client", () => ({ readCaptureGuard: vi.fn() }));
vi.mock("../leads/native-phone", async (original) => ({
  ...(await original<typeof import("../leads/native-phone")>()),
  autoCaptureStates: vi.fn(async () => []),
  autoCaptureStatus: vi.fn(async () => null),
  autoCaptureSetup: vi.fn(),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
let host: HTMLDivElement;
async function render(view: React.ReactNode) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root?.render(view);
  });
}
afterEach(async () => {
  await act(async () => root?.unmount());
  host?.remove();
  vi.clearAllMocks();
});

it("shows the red missing state, and its fix opens the recording check over the call", async () => {
  await render(<CaptureStateLabel state="missing" />);
  expect(host.textContent).toContain("No recording after 30 minutes");
  expect(host.querySelector('[data-missing="true"]')).not.toBeNull();
  // Phone personas, v1.21, 1 Nov 2026: the link opened Settings at Usage
  // analytics, and Back went to Leads instead of the call.
  expect(host.querySelector("a")).toBeNull();
  const fix = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Fix recording",
  );
  expect(host.textContent).not.toContain("Call recording check");
  await act(async () => fix?.click());
  expect(host.textContent).toContain("Call recording check");
});
it("brings the recording check into view when a link asks for it", async () => {
  const scrolled = vi.fn();
  HTMLElement.prototype.scrollIntoView = scrolled;
  window.history.replaceState(null, "", "/settings/privacy#calls-setup");
  await render(
    <CaptureHealthView
      setup={null}
      status={null}
      consentOn
      onRecorder={() => {}}
      onFolder={() => {}}
      onRefresh={() => {}}
    />,
  );
  expect(scrolled).toHaveBeenCalledWith({ block: "start" });
  window.history.replaceState(null, "", "/");
});
it("server missing and report receipts outrank a stale native queue", async () => {
  vi.mocked(autoCaptureStates).mockResolvedValue([
    { eventId: "event", state: "waiting" },
  ]);
  vi.mocked(readCaptureGuard).mockResolvedValue({
    generated_at: "2026-10-29",
    rates: [],
    calls: [
      {
        event_id: "event",
        lead_id: "lead",
        person_id: "person",
        at: "2026-10-29",
        state: "missing",
        submission_id: null,
        attention: false,
      },
    ],
  });
  await render(<AutoCaptureState eventId="event" />);
  // Competitor teardown, item 7: the row says where the recording is, then its fix.
  expect(host.textContent).toContain("Recording: not found");
  expect(host.textContent).toContain("Fix recording");
});
it("keeps an older app's native state when server evidence is unavailable", async () => {
  vi.mocked(autoCaptureStates).mockResolvedValue([
    { eventId: "event", state: "uploading" },
  ]);
  vi.mocked(readCaptureGuard).mockResolvedValue(null);
  await render(<AutoCaptureState eventId="event" />);
  expect(host.textContent).toContain("Uploading");
});
it("does not claim private recordings are accessible and fixes open the native controls", async () => {
  const recorder = vi.fn(),
    folder = vi.fn();
  const setup = parseSetup({
    checks: {},
    recorderProfile: { kind: "private", recording: "private", folders: [] },
    folderPicked: false,
  });
  await render(
    <CaptureHealthView
      setup={setup}
      status={null}
      consentOn={false}
      onRecorder={recorder}
      onFolder={folder}
      onRefresh={() => {}}
    />,
  );
  expect(host.textContent).toContain("keeps recordings private");
  expect(host.textContent).toContain("has not reported");
  expect(host.textContent).toContain("Standing consent needed");
  await act(async () => {
    (host.querySelector("button") as HTMLButtonElement).click();
  });
  expect(recorder).toHaveBeenCalledOnce();
  await act(async () => {
    (host.querySelectorAll("button")[1] as HTMLButtonElement).click();
  });
  expect(folder).toHaveBeenCalledOnce();
});
it("counts the last recording's age from when the phone answered", async () => {
  const setup = parseSetup({
    checks: {},
    recorderProfile: {
      kind: "folder",
      maker: "Xiaomi",
      dialerLabel: "Phone",
      recording: "on",
      folders: [],
      switchTo: null,
    },
    folderPicked: true,
  });
  const answered = Date.UTC(2026, 9, 30, 0, 0);
  await render(
    <CaptureHealthView
      setup={setup}
      status={{
        supported: true,
        on: true,
        wifiOnly: true,
        lastRecordingSeenMs: answered - 5 * 60_000,
      }}
      consentOn
      checkedAt={answered}
      onRecorder={() => {}}
      onFolder={() => {}}
      onRefresh={() => {}}
    />,
  );
  expect(host.textContent).toContain("saved 5 minutes ago");
});
it("shows daily counts with no seller ranking", async () => {
  await render(
    <CaptureRatesView
      rates={[
        {
          person_id: "a",
          name: "Alex Example",
          day: "2026-10-29",
          calls: 10,
          received: 9,
          analysed: 8,
          rate: 90,
          needs_fix: false,
        },
        {
          person_id: "b",
          name: "Sam Example",
          day: "2026-10-29",
          calls: 10,
          received: 3,
          analysed: 2,
          rate: 30,
          needs_fix: true,
        },
      ]}
    />,
  );
  expect(host.textContent).toContain("10 calls · 9 recordings · 8 analysed");
  expect(host.querySelectorAll('[data-missing="true"]')).toHaveLength(1);
  expect(host.textContent).not.toMatch(/rank|score|best|worst/i);
});

// Redmi real-call test, 30 Oct 2026: a profile 403 and a used-up allowance lost calls silently.
it("says why calls wait and opens the fix for an incomplete profile", async () => {
  await render(
    <CaptureAttention
      status={{
        supported: true,
        on: true,
        wifiOnly: true,
        health: "profile",
        healthCalls: 2,
      }}
      onFolder={() => {}}
    />,
  );
  expect(host.textContent).toContain("Add your name and phone");
  expect(host.textContent).toContain("2 lead calls wait on this phone.");
  expect(host.textContent).toContain("upload by themselves");
  expect(host.querySelector("a")?.getAttribute("href")).toBe(
    "/settings/profile",
  );
});
it("used-up minutes wait for minutes and Try again asks the phone", async () => {
  const retry = vi.fn();
  await render(
    <CaptureAttention
      status={{
        supported: true,
        on: true,
        wifiOnly: true,
        health: "allowance",
        healthCalls: 1,
      }}
      onRetry={retry}
      onFolder={() => {}}
    />,
  );
  expect(host.textContent).toContain("Call minutes used up");
  expect(host.textContent).toContain("1 lead call waits on this phone.");
  await act(async () => {
    (host.querySelector("button") as HTMLButtonElement).click();
  });
  expect(retry).toHaveBeenCalledOnce();
});
it("a blocked background network offers the battery fix", async () => {
  const battery = vi.fn();
  await render(
    <CaptureAttention
      status={{
        supported: true,
        on: true,
        wifiOnly: true,
        health: "network",
        healthCalls: 1,
      }}
      onFolder={() => {}}
      onBattery={battery}
    />,
  );
  expect(host.textContent).toContain("No restrictions");
  await act(async () => {
    (host.querySelector("button") as HTMLButtonElement).click();
  });
  expect(battery).toHaveBeenCalledOnce();
});
it("says nothing when all is well, uploads are off or the app is older", async () => {
  for (const health of ["ok", "off", undefined]) {
    await render(
      <CaptureAttention
        status={{
          supported: true,
          on: true,
          wifiOnly: true,
          ...(health ? { health } : {}),
        }}
        onFolder={() => {}}
      />,
    );
    expect(host.textContent).toBe("");
    await act(async () => root?.unmount());
    host.remove();
  }
  root = undefined;
});
it("names the hold on a call and links its fix", async () => {
  await render(<CaptureStateLabel state="held" hold="allowance" />);
  expect(host.textContent).toContain("Waiting for call minutes");
  await act(async () => root?.unmount());
  host.remove();
  await render(<CaptureStateLabel state="held" hold="profile" />);
  expect(host.querySelector("a")?.getAttribute("href")).toBe(
    "/settings/profile",
  );
  await act(async () => root?.unmount());
  host.remove();
  // An older app's held call keeps the review wording.
  await render(<CaptureStateLabel state="held" />);
  expect(host.textContent).toContain("Upload paused · review this call");
});
it("carries the phone's hold reason into a lead's call row", async () => {
  vi.mocked(autoCaptureStates).mockResolvedValue([
    { eventId: "event", state: "held", hold: "profile" },
  ]);
  vi.mocked(readCaptureGuard).mockResolvedValue(null);
  await render(<AutoCaptureState eventId="event" />);
  expect(host.textContent).toContain("Waiting · complete your profile");
});

it("turning uploads on with an incomplete profile says so and links Profile", async () => {
  vi.mocked(autoCaptureStatus).mockResolvedValue({
    supported: true,
    on: false,
    wifiOnly: true,
  });
  vi.mocked(autoCaptureSetup).mockRejectedValue(new Error("profile_required"));
  await render(<AutoCapturePanel consentOn />);
  await act(async () => {});
  const turnOn = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Turn uploads on",
  );
  await act(async () => {
    turnOn?.click();
  });
  expect(autoCaptureSetup).toHaveBeenCalledWith(true, true);
  expect(host.textContent).toContain("Complete your profile first");
  expect(host.querySelector('a[href="/settings/profile"]')).not.toBeNull();
});

const serverCall = (extra: Partial<CaptureCall>): CaptureCall => ({
  event_id: "event",
  lead_id: "lead",
  person_id: "person",
  at: "2026-10-30",
  state: "waiting",
  submission_id: null,
  attention: false,
  ...extra,
});
// Owner, 30 Oct 2026: "I need each single call getting tracked".
it("tracks each call from dialled to its report, or where it is stuck", () => {
  const held = { eventId: "event", state: "held", hold: "allowance" };
  expect(trackFor(held, null)).toMatchObject({
    done: 2,
    stuck: true,
    label: "Waiting for call minutes",
    fix: { label: "Fix uploads" },
  });
  // The hold says why, even after the server's 30-minute deadline.
  expect(trackFor(held, serverCall({ state: "missing" }))?.label).toBe(
    "Waiting for call minutes",
  );
  // A call with no recording 30 minutes on ended without one: calm, with its fix, never
  // "Stuck" in red (persona QA, 31 Oct 2026).
  expect(trackFor(null, serverCall({ state: "missing" }))).toMatchObject({
    done: 0,
    stuck: false,
    ended: true,
    fix: { href: "/settings/privacy#calls-setup" },
  });
  expect(trackFor({ eventId: "event", state: "waiting" }, null)).toMatchObject({
    done: 2,
    stuck: false,
  });
  expect(trackFor({ eventId: "event", state: "uploading" }, null)?.done).toBe(
    3,
  );
  // Server receipts outrank a stale phone queue.
  expect(
    trackFor(
      { eventId: "event", state: "waiting" },
      serverCall({ state: "analysing" }),
    ),
  ).toMatchObject({ done: 4, label: "Analysing" });
  expect(trackFor(null, serverCall({ state: "report_ready" }))?.done).toBe(6);
  // A short call is done with its transcript: not stuck, and no report is coming.
  expect(
    trackFor(
      { eventId: "event", state: "analysing" },
      serverCall({ state: "short_call" }),
    ),
  ).toMatchObject({
    done: 5,
    stuck: false,
    ended: true,
    label: "Short call · transcript and lead details",
  });
  expect(
    trackFor(null, serverCall({ state: "uploaded", attention: true })),
  ).toMatchObject({ done: 4, stuck: true });
  expect(trackFor(null, null, true)?.done).toBe(-1);
  expect(trackFor(null, null)).toBeNull();
});
it("shows the seven steps, the stuck one and its fix", async () => {
  await render(
    <CallTrack
      track={{
        done: 2,
        stuck: true,
        label: "Waiting for call minutes",
        fix: { label: "Fix uploads", href: "/settings/privacy#calls-setup" },
      }}
    />,
  );
  expect(host.querySelectorAll("i")).toHaveLength(7);
  expect(host.querySelectorAll("i[data-done]")).toHaveLength(3);
  expect(host.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe(
    "Stuck at Waiting, step 4 of 7",
  );
  expect(host.textContent).toContain("Stuck · Waiting for call minutes");
  expect(host.querySelector("a")?.textContent).toBe("Fix uploads");
  await act(async () => root?.unmount());
  host.remove();
  // Inside a row that is a link: no second link.
  await render(
    <CallTrack
      track={{ done: 4, stuck: false, label: "Analysing" }}
      links={false}
    />,
  );
  expect(host.querySelector("a")).toBeNull();
  expect(host.textContent).toContain("Analysing");
  await act(async () => root?.unmount());
  host.remove();
  // A short call ends after Analysing: no dot waits on a report.
  await render(
    <CallTrack
      track={{
        done: 5,
        stuck: false,
        ended: true,
        label: "Short call · transcript and lead details",
      }}
    />,
  );
  expect(host.querySelectorAll("i[data-done]")).toHaveLength(6);
  expect(host.querySelector("i[data-now]")).toBeNull();
  expect(host.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe(
    "Done after Analysing, no report",
  );
});
it("a list row with no capture evidence says nothing", async () => {
  vi.mocked(autoCaptureStates).mockResolvedValue([]);
  vi.mocked(readCaptureGuard).mockResolvedValue(null);
  await render(<AutoCaptureState eventId="event" links={false} />);
  await act(async () => {});
  expect(host.textContent).toBe("");
});

it("retains measured recording time and ignores invalid timestamps", () => {
  const base = { kind: "folder", recording: "on", folders: [] };
  expect(parseRecorder({ ...base, newestMs: 12345 })?.newestMs).toBe(12345);
  expect(parseRecorder({ ...base, newestMs: -1 })?.newestMs).toBeUndefined();
  expect(parseRecorder(base)?.newestMs).toBeUndefined();
});
it("says a call's recording arrived, is waiting or wasn't found", async () => {
  // Competitor teardown, item 7, 1 Nov 2026.
  expect(trackFor(null, serverCall({ state: "waiting" }))?.recording).toBe(
    "waiting",
  );
  expect(trackFor(null, serverCall({ state: "missing" }))?.recording).toBe(
    "not found",
  );
  expect(trackFor(null, serverCall({ state: "report_ready" }))?.recording).toBe(
    "arrived",
  );
  await render(
    <CallTrack
      track={{ done: 0, stuck: false, label: "Waiting", recording: "waiting" }}
    />,
  );
  expect(host.querySelector("small")?.textContent).toBe("Recording: waiting");
  await act(async () => root?.unmount());
  host.remove();
  await render(
    <CallTrack
      track={{
        done: 6,
        stuck: false,
        label: "Report ready",
        recording: "arrived",
      }}
    />,
  );
  expect(host.querySelector("small")?.textContent).toBe(
    "Recording: arrived · Report ready",
  );
});
