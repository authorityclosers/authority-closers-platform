"use client";

/**
 * Call capture setup with fictional data, for phone-width screenshots (wb-ci
 * --visual, the Redmi). The screens' API calls and the phone app's answers are
 * made up here; nothing leaves the browser and no permission is asked.
 *
 * `?step=profile|consent|recordings|recorder|private|background|autostart|uploads|done`
 * opens that step in the phone app (an organisation's seller); `&agreed=1` shows
 * the consent step for someone who agreed before; `?step=done-private` is the
 * last screen on a phone whose Phone app is Google's (recordings not working:
 * Set up recording or Not now, never finished). `?step=web` is the web's
 * last step, `?step=update` an app too old, `?step=personal` a personal
 * workspace's first screen, and `?view=team` Team's Call capture list.
 * `?view=walk&step=welcome|alerts|calls|recordings|battery|analyse|test_call|all_set`
 * is phone setup's one-ask walk after sign-in (owner, 20 Nov 2026, style C);
 * `&family=xiaomi|samsung|oppo|pixel` picks the phone, `&stuck=1` the screen
 * after Android stopped asking, `&phase=autostart` the battery's second page,
 * `&test=waiting|missing` the test call's later states. `?view=missing` is
 * the line on Calls and Reports for calls with no recording (`&day=2026-10-29`:
 * as the bell's reminder opens it, its calls listed).
 */

import { useState, useSyncExternalStore } from "react";

import type { CaptureSetup } from "../../capture-setup/capture-setup-client";
import { CaptureSetupFlow } from "../../capture-setup/capture-setup-flow";
import type { CaptureStep } from "../../capture-setup/capture-setup-rules";
import { SetupWalk } from "../../capture-setup/setup-walk";
import walkStyles from "../../capture-setup/setup-walk.module.css";
import type { WalkStep } from "../../capture-setup/setup-walk-steps";
import { parseSetup, type SetupStatus } from "../../leads/native-phone";
import { MissingLine } from "../../capture-setup/recording-check";
import { CaptureSetupPanel } from "../../organisation/capture-setup-panel";
import onboarding from "../../leads/phone-onboarding.module.css";

const SHA = "a".repeat(64);
const DAY = 86_400_000;
// A fixed clock for the shots: 30 Oct 2026, 10:00 India time.
const NOW = Date.UTC(2026, 9, 30, 4, 30);

const TEAM = [
  ["301", "Asha Fictional", "not_started", null, null],
  ["302", "Ravi Fictional", "declined", NOW - DAY / 2, null],
  ["303", "Meera Fictional", "phone_pending", NOW - 2 * DAY, null],
  ["304", "Karan Fictional", "set_up", NOW - DAY, "Redmi 13"],
  ["305", "Neha Fictional", "set_up", NOW - 3 * DAY, "Galaxy A15"],
  // Two phones, the newer one with call recording off (ph1-46): never Ready.
  ["306", "Rohan Fictional", "recording_off", NOW - DAY, "Redmi 13"],
] as const;

function answer(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function read(name: string) {
  return new URLSearchParams(window.location.search).get(name);
}

/** What the fictional phone says, for the step asked for. */
function phone(step: string) {
  const recorderOff = step === "recorder";
  const google = step === "private" || step === "done-private";
  const folder = !["recordings", "private"].includes(step);
  const battery = !["background", "recordings", "recorder", "private"].includes(
    step,
  );
  return {
    setup: {
      checks: {
        calls: true,
        notifications: step !== "uploads",
        recordings: folder,
        recorder: !recorderOff,
        battery,
        autostart: step !== "autostart" && battery,
      },
      family: "xiaomi",
      model: "Redmi 13",
      autostartNeeded: true,
      version: "1.0.50-fictional",
      device: "install-fictional-1",
      recorderProfile: {
        kind: google ? "private" : "folder",
        maker: "xiaomi",
        dialerLabel: google ? "Phone by Google" : "Phone (Xiaomi)",
        recording: recorderOff ? "off" : "on",
        folders: [],
        otherDialers: [],
        newestMs: Date.now() - 12 * 60_000,
      },
      needsAllFiles: !folder,
      allFilesSupported: false,
      folderPickSupported: true,
      folderPicked: folder,
      truecaller: false,
      callLogSupported: false,
      store: "play",
      blocked: {},
    },
    capture: {
      supported: true,
      on: step === "done" || step === "done-private",
      wifiOnly: false,
      health: "off",
    },
  };
}

function install() {
  if (typeof window === "undefined") return true;
  const step = read("step") ?? "profile";
  const where = step === "web" ? "web" : "app";
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    if (url.includes("/capture-setup/team"))
      return answer({
        schema: "sales-xray-capture-setup-team/1",
        people: TEAM.map(([id, name, state, at, model]) => ({
          person_id: `00000000-0000-4000-8000-000000000${id}`,
          name,
          role: "member",
          state,
          at: at ? new Date(at).toISOString() : null,
          phone: model,
          ...(state === "recording_off"
            ? {
                phones: ["Redmi 13", "Nord CE 2 5G"],
                recording: {
                  state: "off",
                  last_at: null,
                  fix: "recorder",
                  phone: "Nord CE 2 5G",
                },
                // Each phone with its own line (ph1-55).
                devices: [
                  {
                    device: "install-fictional-2",
                    name: "Nord CE 2 5G",
                    recording: { state: "off", last_at: null, fix: "recorder" },
                    call_log_off: false,
                  },
                  {
                    device: "install-fictional-1",
                    name: "Redmi 13",
                    recording: {
                      state: "ok",
                      last_at: new Date(NOW - 12 * 60_000).toISOString(),
                      fix: null,
                    },
                    call_log_off: false,
                  },
                ],
              }
            : {}),
        })),
      });
    if (url.includes("/capture-setup"))
      return answer({ ...setupFor(step), consent: "on" });
    if (url.includes("/auto-analysis"))
      return answer({
        schema: "sales-xray-auto-analysis/1",
        state: read("agreed") ? "on" : "ask",
        since: read("agreed") ? new Date(NOW - 5 * DAY).toISOString() : null,
        can_start: Boolean(read("agreed")),
        notice: {
          version: "auto-analysis-2026-10-26",
          language: "en",
          title: "Analyse my calls automatically",
          text: "When I record a sales call with Sales X-Ray in Fictional Homes, the customer knows the call is recorded. Sales X-Ray may analyse each call I record here as soon as it arrives, at my organisation's AI setting. I can turn this off in Settings, Privacy, at any time.",
          policy_sha256: SHA,
        },
      });
    if (url.includes("/upload-policy"))
      return answer({
        schema: "ac.sales-xray.private-upload-consent/1",
        max_cost_paise: 0,
        policy_sha256: SHA,
        title: "Private call upload",
        description: "Fictional upload terms for review.",
        privacy_details:
          "Recordings and reports stay in your workspace. Fictional terms for review only.",
        maximum_file_bytes: 100_000_000,
        maximum_call_seconds: 7200,
        retention_days: 365,
      });
    if (url.includes("/v1/me/sales-xray-profile"))
      return answer({
        name: step === "profile" ? null : "Asha Fictional",
        email: "asha@example.test",
        phone_number_e164: null,
        phone_verified: false,
        profile_complete: step !== "profile",
        revision: 1,
      });
    return real(input, init);
  };
  if (where === "web") return true;
  const answers = phone(step === "update" ? "profile" : step);
  const listeners = new Set<(event: { data: string }) => void>();
  Object.assign(window, {
    SXPhone: {
      addEventListener: (
        _type: string,
        listener: (event: { data: string }) => void,
      ) => listeners.add(listener),
      postMessage: (data: string) => {
        const request = JSON.parse(data) as { id: string; method: string };
        const result =
          request.method === "autoCaptureStatus"
            ? step === "update"
              ? null
              : answers.capture
            : request.method === "setupOpen" ||
                request.method === "recorderOpen"
              ? { opened: false }
              : answers.setup;
        setTimeout(() => {
          for (const listener of listeners)
            listener({
              data: JSON.stringify({
                id: request.id,
                ok: result !== null,
                result,
                error: "phone_error",
              }),
            });
        }, 0);
      },
    },
  });
  return true;
}

function setupFor(step: string): CaptureSetup {
  return {
    schema: "sales-xray-capture-setup/1",
    workspace: step === "personal" ? "personal" : "organisation",
    required: step !== "personal",
    profile_complete: step !== "profile",
    consent: step === "personal" ? "unavailable" : "ask",
    declined_at: null,
    ask_again_at: null,
    phones: [],
  };
}

const STARTS: Record<string, CaptureStep> = {
  profile: "profile",
  consent: "consent",
  personal: "consent",
  recordings: "recordings",
  recorder: "recordings",
  private: "recordings",
  background: "background",
  autostart: "background",
  uploads: "uploads",
  done: "done",
  "done-private": "done",
  web: "phone",
  update: "phone",
};

// Phone setup's walk on a fictional phone (owner, 20 Nov 2026, style C).
const WALK: WalkStep[] = [
  "welcome",
  "alerts",
  "calls",
  "recordings",
  "battery",
  "analyse",
  "test_call",
  "all_set",
];

const PHONES: Record<string, { model: string; folder: string }> = {
  xiaomi: {
    model: "Redmi 13",
    folder: "/storage/emulated/0/MIUI/sound_recorder/call_rec",
  },
  samsung: {
    model: "Galaxy A15",
    folder: "/storage/emulated/0/Recordings/Call",
  },
  oppo: {
    model: "Oppo A78",
    folder: "/storage/emulated/0/Music/Recordings/Call Recordings",
  },
  pixel: { model: "Pixel 8", folder: "" },
};

function walkPhone(family: string): SetupStatus {
  const phone = PHONES[family] ?? PHONES.xiaomi!;
  return parseSetup({
    checks: { calls: false, notifications: false },
    family: family === "pixel" ? "other" : family,
    model: phone.model,
    version: "1.0.60",
    device: "install-fictional-walk",
    autostartNeeded: family === "xiaomi" || family === "oppo",
    folderPickSupported: true,
    callLogSupported: true,
    recorderProfile: {
      kind: family === "pixel" ? "private" : "folder",
      dialerLabel: family === "pixel" ? "Google's Phone app" : "Phone",
      recording: "on",
      folders: phone.folder
        ? [{ path: phone.folder, state: "found", recordings: 12 }]
        : [],
    },
  }) as SetupStatus;
}

/** One screen of the walk, its buttons inert. */
function WalkFixture() {
  const step = (read("step") ?? "welcome") as WalkStep;
  const status = walkPhone(read("family") ?? "xiaomi");
  const stuck = read("stuck") === "1";
  const test = read("test");
  return (
    <div
      className={`${onboarding.page} ${walkStyles.walk}`}
      style={{ position: "static", minHeight: "100dvh" }}
    >
      <SetupWalk
        start={WALK.includes(step) ? step : "welcome"}
        steps={WALK}
        // At the end: all done, or (&almost=1) something put off.
        stillOpen={() => step !== "all_set" || read("almost") === "1"}
        status={status}
        settingsFor={() => stuck}
        questions={[
          "Allow Sales X-Ray to make and manage phone calls?",
          "Allow Sales X-Ray to access your phone call logs?",
        ]}
        batteryPhase={read("phase") === "autostart" ? "autostart" : "battery"}
        test={test === "waiting" || test === "missing" ? test : "ready"}
        consent={{
          // Fictional organisation in the fixture; the real words come sealed from the server.
          words:
            "When I record a sales call with Sales X-Ray in Fictional Homes, the customer knows the call is recorded. Sales X-Ray may analyse each call I record here as soon as it arrives, at my organisation's AI setting. I can turn this off in Settings, Privacy, at any time.",
          terms:
            "Recordings and reports stay in your workspace. Fictional terms for review only.",
        }}
        busy={false}
        laterLabel={(each) => `Not now: ${each}`}
        onAsk={() => undefined}
        onLater={() => undefined}
        onNoCalls={() => undefined}
        onShown={() => undefined}
        onEnd={() => undefined}
      />
    </div>
  );
}

const unchanging = () => () => undefined;

export function CaptureSetupPreview() {
  useState(install);
  const query = useSyncExternalStore(
    unchanging,
    () => window.location.search,
    () => null,
  );
  if (query === null) return null;
  const params = new URLSearchParams(query);
  if (params.get("view") === "walk" || params.get("view") === "permissions")
    return (
      <main data-capture-setup-fixture="" style={{ minHeight: "100dvh" }}>
        <WalkFixture />
      </main>
    );
  if (params.get("view") === "missing")
    return (
      <main data-capture-setup-fixture="" style={{ minHeight: "100dvh" }}>
        <MissingFixture day={params.get("day")} />
      </main>
    );
  if (params.get("view") === "team")
    return (
      <main style={{ padding: 16, maxWidth: 720, margin: "0 auto" }}>
        <CaptureSetupPanel />
      </main>
    );
  const step = params.get("step") ?? "profile";
  const setup = setupFor(step === "update" ? "consent" : step);
  // The flow is a full-screen dialog; the page under it fills the screen too.
  return (
    <main data-capture-setup-fixture="" style={{ minHeight: "100dvh" }}>
      <CaptureSetupFlow
        setup={
          step === "consent" || step === "personal" || step === "profile"
            ? setup
            : { ...setup, consent: params.get("agreed") ? "on" : setup.consent }
        }
        phone={step === "web" ? null : { status: null }}
        inApp={step !== "web"}
        required={step !== "personal"}
        organisation={step === "personal" ? null : "Fictional Homes"}
        startAt={STARTS[step] ?? "profile"}
        onFinish={() => undefined}
        onDeclined={() => undefined}
        onClose={() => undefined}
      />
    </main>
  );
}

/** The no-recording line on Calls and Reports (fictional calls). */
function MissingFixture({ day }: { day: string | null }) {
  return (
    <div style={{ padding: 16 }}>
      <MissingLine
        day={day}
        onFix={() => undefined}
        missing={{
          calls: 2,
          tried: 9,
          latest_at: new Date(NOW - 40 * 60_000).toISOString(),
          items: [
            {
              event_id: "00000000-0000-4000-8000-000000000501",
              lead_id: "00000000-0000-4000-8000-000000000401",
              lead_name: "Rohan Fictional",
              at: new Date(NOW - 40 * 60_000).toISOString(),
              seconds: 95,
            },
            {
              event_id: "00000000-0000-4000-8000-000000000502",
              lead_id: "00000000-0000-4000-8000-000000000402",
              lead_name: "Priya Fictional",
              at: new Date(NOW - 3 * 3_600_000).toISOString(),
              seconds: 42,
            },
          ],
        }}
      />
    </div>
  );
}
