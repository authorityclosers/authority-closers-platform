"use client";

/**
 * Lead calls the phone recorded from its own dialer (owner, 22 Oct 2026), and
 * Phone setup on a Xiaomi that hides its recordings, for screenshots on
 * GitHub (wb-ci --visual). A stand-in for the phone app's channel answers
 * here with fictional calls; nothing leaves the browser.
 *
 * `?view=card` (default): the Recorded lead calls card on Leads.
 * `?view=sheet`: then its sheet, with one silent recording flagged.
 * `?view=hidden`: the card when the phone hides its recordings folder.
 * `?view=setup`: Phone setup on the Xiaomi: All files access and Truecaller.
 */

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { AcquisitionShell } from "../../acquisition-shell";
import { RecordedCallsCard } from "../../leads/recorded-calls";
import { PhoneSetupSheet } from "../../leads/phone-setup";
import { parseSetup } from "../../leads/native-phone";
import { PageHeader } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";
import { CALL_LIMIT_SECONDS } from "../../call-limit";

const SELLER = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const LEADS: Record<string, string> = {
  "00000000-0000-4000-8000-0000000000a1": "meera joshi",
  "00000000-0000-4000-8000-0000000000a2": "RAHUL VERMA",
};

const now = Date.now();
const recording = (name: string, verdict: string) => ({
  source: `file:/storage/emulated/0/MIUI/sound_recorder/call_rec/${name}`,
  name,
  size: 2_150_000,
  durationMs: 0,
  ext: "mp3",
  mime: "audio/mpeg",
  supported: true,
  captured: "dialer",
  check: { verdict, speechSeconds: 52, measuredSeconds: 134 },
});

const CALLS = [
  {
    eventId: "00000000-0000-4000-8000-0000000000e1",
    leadId: "00000000-0000-4000-8000-0000000000a1",
    startedMs: now - 42 * 60_000,
    seconds: 134,
    direction: "outgoing",
    recording: recording("(00919000000001)_20261022101530.mp3", "ok"),
    looking: false,
  },
  {
    eventId: "00000000-0000-4000-8000-0000000000e2",
    leadId: "00000000-0000-4000-8000-0000000000a2",
    startedMs: now - 18 * 60_000,
    seconds: 61,
    direction: "incoming",
    recording: recording("(00919000000002)_20261022103412.mp3", "silent"),
    looking: false,
  },
];

const SETUP = {
  checks: {
    calls: true,
    recordings: false,
    notifications: true,
    recorder: true,
    folder: false,
    battery: false,
    autostart: true,
    testCall: false,
    callLog: true,
  },
  family: "xiaomi",
  model: "Fictional 5G",
  autostartNeeded: true,
  version: "0.3.80",
  device: "00000000-0000-4000-8000-0000000000d1",
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

function install(view: string) {
  if (typeof window === "undefined") return true;
  const hidden = view === "hidden";
  const pending = {
    items: hidden ? [{ ...CALLS[0], recording: null, looking: true }] : CALLS,
    needsAllFiles: hidden,
    allFilesSupported: true,
  };
  const listeners: ((event: { data: unknown }) => void)[] = [];
  (window as unknown as { SXPhone: unknown }).SXPhone = {
    addEventListener: (
      _: string,
      listener: (event: { data: unknown }) => void,
    ) => listeners.push(listener),
    postMessage: (data: string) => {
      const message = JSON.parse(data) as { id: string; method: string };
      const result =
        message.method === "setupStatus"
          ? SETUP
          : message.method === "pendingRecordings" ||
              message.method === "recordingHandled"
            ? pending
            : {};
      window.setTimeout(() =>
        listeners.forEach((listener) =>
          listener({
            data: JSON.stringify({ id: message.id, ok: true, result }),
          }),
        ),
      );
    },
  };
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const lead = path.match(/^\/v1\/lead-desk\/leads\/([0-9a-f-]+)$/)?.[1];
    if (lead && LEADS[lead])
      return new Response(
        JSON.stringify({
          lead: { lead_id: lead, name: LEADS[lead] },
          events: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    if (path === "/v1/conversation/acquisition/upload-policy")
      return new Response(
        JSON.stringify({
          schema: "ac.sales-xray.private-upload-consent/1",
          max_cost_paise: 0,
          policy_sha256: "0".repeat(64),
          title: "Recording terms (sample)",
          description: "Sample terms for screenshots.",
          maximum_file_bytes: 100_000_000,
          maximum_call_seconds: CALL_LIMIT_SECONDS,
          retention_days: 30,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    if (path.startsWith("/v1/"))
      return new Response(JSON.stringify({ detail: "Sample data only." }), {
        status: 404,
      });
    return real(input, init);
  };
  return true;
}

const pause = (ms: number) =>
  new Promise((resolve) => window.setTimeout(resolve, ms));

function Preview() {
  const view = useSearchParams().get("view") ?? "card";
  useState(() => install(view));
  const [setupOpen, setSetupOpen] = useState(view === "setup");
  useEffect(() => {
    if (view !== "sheet") return;
    let stopped = false;
    void (async () => {
      await pause(600);
      if (stopped) return;
      Array.from(document.querySelectorAll<HTMLButtonElement>("button"))
        .find((button) => button.textContent === "Analyse")
        ?.click();
    })();
    return () => {
      stopped = true;
    };
  }, [view]);
  const status = parseSetup(SETUP);
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: { personId: SELLER, sessionId: SESSION, tenantId: TENANT },
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "organisation",
            name: "Fictional Homes",
            role: "member",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <AcquisitionShell authenticated active="leads">
        <PageHeader title="Leads" titleInBar />
        <RecordedCallsCard
          me={{
            person_id: SELLER,
            name: "Asha Fictional",
            role: "member",
            can_manage: false,
          }}
        />
        {status ? (
          <PhoneSetupSheet
            open={setupOpen}
            status={status}
            onStatus={() => {}}
            onClose={() => setSetupOpen(false)}
          />
        ) : null}
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}

export function RecordedCallsPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
