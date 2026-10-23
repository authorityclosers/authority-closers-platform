"use client";

/**
 * The real New analysis studio with a stand-in for the Sales Xray API, for tutorial
 * recordings. A generated recording (12 minutes of soft tone bursts) is picked the way
 * a person picks one; the account, workspace, allowance and analysis are fictional and
 * nothing is sent anywhere. No price or cost is answered or shown.
 */

import dynamic from "next/dynamic";
import { useEffect } from "react";

import { CALL_LIMIT_SECONDS } from "../../call-limit";
import { UploadSessionProvider } from "../../hooks/upload-session";
import { WorkspaceAccessProvider } from "../../workspace-access";

export type UploadStep = "start" | "picked" | "details" | "analysing";

const ACQUISITION = "/v1/conversation/acquisition";
const TENANT = "00000000-0000-4000-8000-0000000000a1";
const SAVED_CALL = "00000000-0000-4000-8000-0000000000c1";
const RECORDING = "00000000-0000-4000-8000-0000000000d1";
const PLAN = "00000000-0000-4000-8000-0000000000e1";
const FILE_NAME = "Call with Amit Sharma.wav";
const SECONDS = 12 * 60;

const ACCESS = {
  status: "ready" as const,
  authenticated: true,
  context: {
    personId: "fixture-person",
    sessionId: "fixture-session",
    tenantId: TENANT,
  },
  retry: () => {},
};

const ALLOWANCE = {
  allowance_seconds: 6_000,
  committed_seconds: 1_080,
  available_seconds: 4_920,
};

const ENTRY = {
  enabled: true,
  auth_mode: "account",
  site_key: null,
  challenge_action: null,
  policy_revision: "sales-xray-upload-v1",
  allowance_seconds: 6_000,
  report_languages: ["en", "hi-Deva+en", "mr-Deva+en"],
  report_language_default: "en",
};

const POLICY = {
  schema: "ac.sales-xray.private-upload-consent/1",
  policy_sha256: "c".repeat(64),
  title: "Upload your call and get your report",
  description:
    "Upload only a call you have permission to analyse. AC checks its length, " +
    "transcribes it and prepares your report. The call's length comes off your " +
    "minutes only when its report is ready; a call that fails uses none. Your " +
    "recording and report stay private for up to 30 days. Review the privacy " +
    "details before starting your analysis.",
  privacy_details:
    "Approved service providers receive the recording or its transcript only to " +
    "transcribe the call and prepare your report. AC keeps your recording, " +
    "transcript and report privately for up to 30 days, then deletes them. You " +
    "can request deletion from Privacy & support.",
  maximum_file_bytes: 100_000_000,
  maximum_call_seconds: CALL_LIMIT_SECONDS,
  retention_days: 30,
  max_cost_paise: 0,
};

const STAGES = ["C2", "C4", "C5"].map((stage) => ({
  stage,
  provider: "approved-provider",
  model: "fixture-model",
  max_requests: 1,
  privacy_revision: "sales-xray-processing-plan-v1",
  privacy_notice:
    "An approved provider transcribes the call and prepares its report.",
}));

function plan(accepted: boolean) {
  return {
    id: PLAN,
    recording_id: RECORDING,
    plan_fingerprint: "a".repeat(64),
    privacy_revision: "sales-xray-processing-plan-v1",
    accepted,
    state: accepted ? "active" : "quoted",
    cost_label: "Included in your minutes",
    max_cost_paise: 0,
    max_entitlement_seconds: 0,
    expires_at_epoch: 4_102_444_800,
    stages: STAGES,
    current_stage: accepted ? "C2" : null,
    report_ready: false,
    report_run_id: null,
    automatic_progression: true,
    failure_code: null,
  };
}

function progress(id: string, analysing: boolean, sha = "0".repeat(64)) {
  return {
    submission_id: id,
    recording_id: RECORDING,
    source_sha256: sha,
    state: analysing ? "active" : "ready",
    local_state: "completed",
    has_report: false,
    automatic_progression: analysing,
    duration_ms: SECONDS * 1_000,
    allowance: ALLOWANCE,
    stages: analysing
      ? [
          { stage: "C2", state: "completed" },
          { stage: "C4", state: "running" },
        ]
      : [],
  };
}

function json(body: unknown, status = 200) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Answers the API reads the studio and shell make, as a signed-in person with a
 * personal workspace would get them. Unknown API paths get a 404, so no real
 * account data can appear in a recording.
 */
function installApi(step: UploadStep) {
  const marked = window as Window & { __uploadFixture?: boolean };
  if (marked.__uploadFixture) return;
  marked.__uploadFixture = true;
  // A call the studio remembers from an earlier visit would open instead.
  try {
    localStorage.removeItem("ac.xray.submission.v1");
    localStorage.removeItem("ac.xray.pending-upload.v1");
  } catch {
    /* storage blocked: nothing remembered either */
  }
  const sent = new Set<string>(step === "analysing" ? [SAVED_CALL] : []);
  const accepted = new Set<string>(step === "analysing" ? [SAVED_CALL] : []);
  // The studio checks the server bound exactly the file it sent.
  const shas = new Map<string, string>();
  const real = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const raw =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const url = new URL(raw, window.location.href);
    if (
      url.origin !== window.location.origin ||
      !url.pathname.startsWith("/v1/")
    )
      return real(input, init);
    // Answer after a short wait, as a network does: an instant answer would let
    // the studio's status polling run without ever yielding to the page.
    await new Promise((resolve) => window.setTimeout(resolve, 120));
    const method = (
      init.method ?? (input instanceof Request ? input.method : "GET")
    ).toUpperCase();
    const path = url.pathname;
    if (path === "/v1/me/workspaces")
      return json({
        person_id: "fixture-person",
        session_id: "fixture-session",
        selected_tenant_id: TENANT,
        workspaces: [{ tenant_id: TENANT, name: "Personal" }],
      });
    if (path === "/v1/me/sales-xray-workspaces")
      return json({
        selected_tenant_id: TENANT,
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "personal",
            name: "Personal",
            role: null,
            sales_xray_enabled: true,
          },
        ],
      });
    if (path === "/v1/me/sales-xray-profile/write-eligibility")
      return json(null, 204);
    if (path === `${ACQUISITION}/entry`) return json(ENTRY);
    if (path === `${ACQUISITION}/upload-policy`) return json(POLICY);
    if (path === `${ACQUISITION}/session`)
      return json({ state: "claimed", allowance: ALLOWANCE });
    if (path === `${ACQUISITION}/availability`) return json({ paused: false });
    if (path === `${ACQUISITION}/submissions` && method === "GET")
      return json({ submissions: [], next_cursor: null });
    const call = new RegExp(
      `^${ACQUISITION}/submissions/([0-9a-f-]{36})(/.*)?$`,
    ).exec(path);
    if (call) {
      const [, id, rest = ""] = call;
      if (rest === "/source" && method === "PUT") {
        sent.add(id);
        const sha = new Headers(init.headers).get("X-Source-SHA256");
        if (sha) shas.set(id, sha);
        return json(progress(id, false, shas.get(id)), 202);
      }
      if (rest === "/plan/quote" && method === "POST")
        return json(plan(false), 201);
      if (rest === "/plan" && method === "POST") {
        accepted.add(id);
        return json(plan(true), 202);
      }
      if (rest === "/plan")
        return accepted.has(id) ? json(plan(true)) : json({}, 404);
      if (rest === "" && method === "GET")
        return sent.has(id)
          ? json(progress(id, accepted.has(id), shas.get(id)))
          : json({}, 404);
    }
    return json({ detail: "Not part of this preview." }, 404);
  };
}

/** A real, playable recording: 12 minutes of soft tone bursts with pauses. */
function recording(): File {
  const rate = 8_000;
  const samples = rate * SECONDS;
  const buffer = new ArrayBuffer(44 + samples * 2);
  const view = new DataView(buffer);
  const text = (at: number, value: string) => {
    for (let i = 0; i < value.length; i += 1)
      view.setUint8(at + i, value.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples * 2, true);
  let seed = 7;
  for (let i = 0; i < samples; i += 1) {
    const t = i / rate;
    const phrase = Math.max(0, Math.sin(t * 0.9) * Math.sin(t * 2.3 + 1));
    seed = (seed * 1_103_515_245 + 12_345) % 2_147_483_648;
    const noise = (seed / 2_147_483_648) * 2 - 1;
    const value =
      phrase * (0.5 * Math.sin(2 * Math.PI * 180 * t) + 0.3 * noise) * 9_000;
    view.setInt16(44 + i * 2, Math.round(value), true);
  }
  return new File([buffer], FILE_NAME, { type: "audio/wav" });
}

const Studio = dynamic(
  async () => {
    const params = new URLSearchParams(window.location.search);
    const step = params.get("step");
    installApi(
      step === "picked" || step === "details" || step === "analysing"
        ? step
        : "start",
    );
    return (await import("../../acquisition-studio")).AcquisitionStudio;
  },
  { ssr: false },
);

export function UploadPreview({ step }: { step: UploadStep }) {
  // Pick the recording (and tick the terms) as the person would, once the
  // studio's upload page is ready.
  useEffect(() => {
    if (step !== "picked" && step !== "details") return;
    let seen = 0;
    let picked = false;
    const timer = window.setInterval(() => {
      const input =
        document.querySelector<HTMLInputElement>('input[type="file"]');
      if (!input || input.disabled) return;
      seen += 1;
      if (!picked) {
        if (seen < 4) return;
        const files = new DataTransfer();
        files.items.add(recording());
        input.files = files.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        picked = true;
        if (step === "picked") window.clearInterval(timer);
        return;
      }
      const box = document.querySelector<HTMLInputElement>(
        '.studio-consent input[type="checkbox"]',
      );
      if (!box) return;
      if (!box.checked) box.click();
      box.closest(".studio-consent")?.scrollIntoView({ block: "center" });
      window.clearInterval(timer);
    }, 250);
    return () => window.clearInterval(timer);
  }, [step]);
  return (
    <UploadSessionProvider>
      <WorkspaceAccessProvider value={ACCESS}>
        <Studio requestedCallId={step === "analysing" ? SAVED_CALL : null} />
      </WorkspaceAccessProvider>
    </UploadSessionProvider>
  );
}
