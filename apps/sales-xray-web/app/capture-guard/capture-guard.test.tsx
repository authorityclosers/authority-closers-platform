import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { CaptureAttention, CaptureHealthView } from "./capture-health";
import { CaptureRatesView } from "./capture-rates";
import {
  AutoCaptureState,
  CallTrack,
  CaptureStateLabel,
  folderRecorder,
  forgetRecorder,
  PRIVATE_LABEL,
  trackFor,
} from "../leads/auto-capture-state";
import type { CaptureCall } from "../leads/capture-guard-client";
import { parseSetup, parseRecorder } from "../leads/native-phone";
import { readCaptureGuard } from "../leads/capture-guard-client";
import {
  autoCaptureSetup,
  autoCaptureStates,
  autoCaptureStatus,
  openDialer,
  pickRecordingsFolder,
  recorderOpen,
  setupStatus,
} from "../leads/native-phone";
import { AutoCapturePanel } from "../settings/auto-capture-panel";

vi.mock("../leads/capture-guard-client", () => ({ readCaptureGuard: vi.fn() }));
vi.mock("../leads/native-phone", async (original) => ({
  ...(await original<typeof import("../leads/native-phone")>()),
  autoCaptureStates: vi.fn(async () => []),
  autoCaptureStatus: vi.fn(async () => null),
  autoCaptureSetup: vi.fn(),
  setupStatus: vi.fn(async () => null),
  recorderOpen: vi.fn(async () => true),
  openDialer: vi.fn(),
  pickRecordingsFolder: vi.fn(async () => null),
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
  forgetRecorder();
});

it("shows the red missing state, and its fix opens the recording check over the call", async () => {
  await render(<CaptureStateLabel state="missing" />);
  expect(host.textContent).toContain("No recording after 30 minutes");
  expect(host.querySelector('[data-missing="true"]')).not.toBeNull();
  // Phone personas ph2-09 and ph2-31 (v1.22, 1 Nov 2026): the link opened
  // Settings at Usage analytics, and Back closed the lead. Fix opens the
  // checked list at its failing step, a dialog over the call ("phone" on the web).
  expect(host.querySelector("a")).toBeNull();
  const fix = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Fix recording",
  );
  const asked: unknown[] = [];
  const listen = (event: Event) =>
    asked.push((event as CustomEvent<unknown>).detail);
  window.addEventListener("sx-capture-setup-open", listen);
  const before = window.location.href;
  await act(async () => fix?.click());
  window.removeEventListener("sx-capture-setup-open", listen);
  expect(asked).toEqual(["phone"]);
  expect(window.location.href).toBe(before);
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
  expect(host.textContent).toContain("has not seen a recording yet");
  expect(host.textContent).toContain("Analyse my calls is off");
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
  // All fine: no rows to fix, only the last recording (production 132).
  for (const fix of ["Phone settings", "Choose folder", "Upload settings"])
    expect(host.textContent).not.toContain(fix);
});

it("without a phone answering, says once where to check", async () => {
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
  expect(host.textContent).toContain("Open Sales X-Ray on your phone");
  expect(host.textContent).not.toContain("Phone settings");
  expect(host.textContent).not.toContain("Choose folder");
  // Uploads are a setting here too, so their row stays, saying where it goes.
  expect(host.querySelector("a")?.textContent).toBe("Apps & devices");
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
  // Minutes: who can add them, no Fix and no prices (Redmi QA, 10 Nov 2026).
  await render(<CaptureStateLabel state="held" hold="allowance" />);
  expect(host.textContent).toBe(
    "Waiting for analysis minutes · your owner or an admin can add them",
  );
  expect(host.querySelector("a, button")).toBeNull();
  await act(async () => root?.unmount());
  host.remove();
  await render(<CaptureStateLabel state="held" hold="profile" />);
  expect(host.querySelector("a")?.getAttribute("href")).toBe(
    "/settings/profile",
  );
  await act(async () => root?.unmount());
  host.remove();
  // A hold the phone can't explain says what to do, and never opens phone setup.
  await render(<CaptureStateLabel state="held" />);
  expect(host.textContent).toBe(
    "Upload paused · add its recording by hand on the lead",
  );
  expect(host.querySelector("a, button")).toBeNull();
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
    label: "Waiting for analysis minutes · your owner or an admin can add them",
  });
  expect(trackFor(held, null)?.fix).toBeUndefined();
  // The hold says why, even after the server's 30-minute deadline.
  expect(trackFor(held, serverCall({ state: "missing" }))?.label).toBe(
    "Waiting for analysis minutes · your owner or an admin can add them",
  );
  // A hold the phone can't explain never sends the seller to phone setup.
  expect(trackFor({ eventId: "event", state: "held" }, null)).toMatchObject({
    label: "Upload paused · add its recording by hand on the lead",
    stuck: true,
  });
  expect(
    trackFor({ eventId: "event", state: "held" }, null)?.fix,
  ).toBeUndefined();
  expect(
    trackFor({ eventId: "event", state: "held", hold: "profile" }, null)?.fix,
  ).toMatchObject({ label: "Open Profile", href: "/settings/profile" });
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
// Owner, 3 Nov 2026: on his OnePlus, Google's Phone app recorded both calls to the
// lead "testing" and kept them, and the rows said "Waiting for recording" for two hours.
it("says a private Phone app keeps the recording, with its one way to get it", () => {
  const share = { switchTo: null, share: true };
  for (const state of ["waiting", "missing"] as const)
    expect(trackFor(null, serverCall({ state }), false, share)).toMatchObject({
      label: PRIVATE_LABEL,
      stuck: false,
      fix: { label: "Share the recording to Sales X-Ray" },
    });
  expect(
    trackFor(null, serverCall({ state: "waiting" }), false, share)?.recording,
  ).toBeUndefined();
  // Another Phone app here saves files Sales X-Ray reads: switch to it.
  expect(
    trackFor(null, serverCall({ state: "waiting" }), false, {
      switchTo: "OnePlus Phone",
      share: true,
    })?.fix?.label,
  ).toBe("Switch to OnePlus Phone");
  // An app build that can't take a share says to update it.
  expect(
    trackFor(null, serverCall({ state: "missing" }), false, {
      switchTo: null,
      share: false,
    })?.fix,
  ).toMatchObject({ label: "Update Sales X-Ray to share recordings" });
  // A recording that did reach the app (shared, or recorded in it) goes on as usual.
  expect(
    trackFor(
      { eventId: "event", state: "uploading" },
      serverCall({ state: "waiting" }),
      false,
      share,
    )?.label,
  ).toBe("Uploading");
  expect(
    trackFor(null, serverCall({ state: "report_ready" }), false, share)?.label,
  ).toBe("Report ready");
  // Another Phone app's recordings: nothing changes.
  expect(trackFor(null, serverCall({ state: "waiting" }))?.recording).toBe(
    "waiting",
  );
});
it("reads the Phone app on the phone and opens its screen from the row", async () => {
  vi.mocked(setupStatus).mockResolvedValueOnce(
    parseSetup({
      checks: {},
      recorderProfile: {
        kind: "private",
        recording: "private",
        folders: [],
        shareTarget: true,
        otherDialers: [
          {
            package: "com.oplus.dialer",
            label: "OnePlus Phone",
            savesToFolder: true,
          },
        ],
      },
    }),
  );
  vi.mocked(autoCaptureStates).mockResolvedValue([]);
  vi.mocked(readCaptureGuard).mockResolvedValue({
    generated_at: "2026-11-03",
    rates: [],
    calls: [serverCall({ state: "waiting" })],
  });
  await render(<AutoCaptureState eventId="event" />);
  await act(async () => {});
  expect(host.textContent).toContain(PRIVATE_LABEL);
  expect(host.textContent).not.toContain("Recording: waiting");
  const fix = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Switch to OnePlus Phone",
  );
  await act(async () => fix?.click());
  expect(recorderOpen).toHaveBeenCalledWith("defaultDialer");
  expect(openDialer).not.toHaveBeenCalled();
});
it("parses whether the app takes a shared recording", () => {
  const base = { kind: "private", recording: "private", folders: [] };
  expect(parseRecorder({ ...base, shareTarget: true })?.shareTarget).toBe(true);
  expect(parseRecorder(base)?.shareTarget).toBeUndefined();
});
// Orchestrator, 3 Nov 2026: the owner's OnePlus has only OnePlus's own Phone app, which saves to a
// folder, and its calls said "Waiting for recording" with no reason. 3 minutes on, say the fix.
it("names the fix 3 minutes after a folder phone's call with no recording", () => {
  const now = Date.parse("2026-11-03T09:00:00Z");
  const ago = (minutes: number) =>
    new Date(now - minutes * 60_000).toISOString();
  const autoRecord = trackFor(
    null,
    serverCall({ state: "waiting", at: ago(4) }),
    false,
    null,
    { pick: false },
    now,
  );
  expect(autoRecord).toMatchObject({
    label: "No recording yet",
    stuck: false,
    fix: { label: "Turn on Auto record in your Phone app" },
  });
  expect(
    trackFor(
      null,
      serverCall({ state: "missing", at: ago(40) }),
      false,
      null,
      { pick: true },
      now,
    )?.fix?.label,
  ).toBe("Pick your recordings folder");
  // Before 3 minutes it still waits, and a recording on the phone goes on as usual.
  expect(
    trackFor(
      null,
      serverCall({ state: "waiting", at: ago(2) }),
      false,
      null,
      { pick: false },
      now,
    )?.recording,
  ).toBe("waiting");
  expect(
    trackFor(
      { eventId: "event", state: "waiting" },
      serverCall({ state: "waiting", at: ago(10) }),
      false,
      null,
      { pick: false },
      now,
    )?.label,
  ).toBe("Waiting to upload");
});
it("picks the folder only when none of the known folders is on the phone", () => {
  const setup = (states: string[], folderPicked = false) =>
    parseSetup({
      checks: {},
      folderPicked,
      recorderProfile: {
        kind: "folder",
        recording: "unknown",
        folders: states.map((state, i) => ({ path: `Folder${i}`, state })),
      },
    });
  expect(folderRecorder(setup(["missing", "missing"]))).toEqual({ pick: true });
  expect(folderRecorder(setup(["missing", "empty"]))).toEqual({ pick: false });
  expect(folderRecorder(setup(["missing"], true))).toEqual({ pick: false });
  expect(
    folderRecorder(
      parseSetup({
        checks: {},
        recorderProfile: { kind: "private", folders: [] },
      }),
    ),
  ).toBeNull();
  expect(folderRecorder(null)).toBeNull();
});
it("opens the Phone app's call recording setting from a waiting row", async () => {
  vi.mocked(setupStatus).mockResolvedValueOnce(
    parseSetup({
      checks: {},
      folderPicked: true,
      recorderProfile: {
        kind: "folder",
        recording: "off",
        folders: [{ path: "Music/Recordings/Call Recordings", state: "empty" }],
      },
    }),
  );
  vi.mocked(autoCaptureStates).mockResolvedValue([]);
  vi.mocked(readCaptureGuard).mockResolvedValue({
    generated_at: "2026-11-03",
    rates: [],
    calls: [
      serverCall({
        state: "waiting",
        at: new Date(Date.now() - 10 * 60_000).toISOString(),
      }),
    ],
  });
  await render(<AutoCaptureState eventId="event" />);
  await act(async () => {});
  expect(host.textContent).toContain("No recording yet");
  const fix = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Turn on Auto record in your Phone app",
  );
  await act(async () => fix?.click());
  expect(recorderOpen).toHaveBeenCalledWith("settings");
  expect(pickRecordingsFolder).not.toHaveBeenCalled();
});

it("lets a check's action go under its words rather than squeeze them", () => {
  // The owner's bug 115, re-checked at 130% text (10 Nov 2026).
  const css = readFileSync(
    join(process.cwd(), "app/capture-guard/capture-guard.module.css"),
    "utf8",
  );
  expect(css).toMatch(/\n\.check \{[^}]*flex-wrap: wrap;/);
  expect(css).toMatch(/\n\.check > span:first-child \{\s*flex: 1 1 10rem;/);
});
