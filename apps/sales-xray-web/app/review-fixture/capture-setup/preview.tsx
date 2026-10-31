"use client";

/**
 * Call capture setup with fictional data, for phone-width screenshots (wb-ci
 * --visual, the Redmi). The screens' API calls and the phone app's answers are
 * made up here; nothing leaves the browser and no permission is asked.
 *
 * `?step=profile|consent|recordings|recorder|private|background|autostart|uploads|done`
 * opens that step in the phone app (an organisation's seller); `&agreed=1` shows
 * the consent step for someone who agreed before. `?step=web` is the web's
 * last step, `?step=update` an app too old, `?step=personal` a personal
 * workspace's first screen, and `?view=team` Team's Call capture list.
 * `?view=permissions` is the permissions checklist after sign-in (two still to
 * allow, one blocked, contacts waiting for an app update) and `?view=missing`
 * the card for a call with no recording.
 */

import { useEffect, useState, useSyncExternalStore } from "react";

import type { CaptureSetup } from "../../capture-setup/capture-setup-client";
import { CaptureSetupFlow } from "../../capture-setup/capture-setup-flow";
import type { CaptureStep } from "../../capture-setup/capture-setup-rules";
import { PermissionsChecklist } from "../../capture-setup/permissions-gate";
import type {
  PermissionItem,
  PermissionKey,
} from "../../capture-setup/permissions-rules";
import { recordingNotice } from "../../capture-setup/recording-check";
import { NoticeCenter, notify } from "../../notice-center";
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
        kind: step === "private" ? "private" : "folder",
        maker: "xiaomi",
        dialerLabel: step === "private" ? "Phone by Google" : "Phone (Xiaomi)",
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
      on: step === "done",
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
  web: "phone",
  update: "phone",
};

const PERMISSIONS: PermissionItem[] = [
  {
    key: "callLog",
    label: "Call log",
    why: "Logs your calls with leads on the lead. Other numbers stay on your phone.",
    state: "granted",
  },
  {
    key: "phone",
    label: "Phone",
    why: "Knows when a call starts and ends, so it is timed and its recording found.",
    state: "needed",
  },
  {
    key: "contacts",
    label: "Contacts",
    why: "Shows the right name on calls and leads by matching callers to your saved contacts. Read for nothing else.",
    state: "update",
  },
  {
    key: "notifications",
    label: "Notifications",
    why: "New leads, calls that are due, and Undo before a call uploads.",
    state: "blocked",
  },
  {
    key: "recordings",
    label: "Recordings folder",
    why: "Finds each call's recording in your Phone app's folder.",
    state: "needed",
  },
];

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
  if (params.get("view") === "permissions")
    return (
      <main data-capture-setup-fixture="" style={{ minHeight: "100dvh" }}>
        <div className={onboarding.page} style={{ position: "static" }}>
          <div className={onboarding.body}>
            <PermissionsChecklist
              items={PERMISSIONS}
              busy={null}
              tried={new Set<PermissionKey>(["phone"])}
              onAllow={() => undefined}
              onSettings={() => undefined}
            />
          </div>
        </div>
      </main>
    );
  if (params.get("view") === "missing")
    return (
      <main data-capture-setup-fixture="" style={{ minHeight: "100dvh" }}>
        <MissingCard />
        <NoticeCenter />
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

/** The no-recording corner card, as the app posts it (fictional count). */
function MissingCard() {
  useEffect(() => notify(recordingNotice(2, null, () => undefined)), []);
  return null;
}
