/**
 * Calls on a lead that become Sales Xray calls (the same consent, file
 * checks, plan and analysis as any upload):
 *
 * - a real call's recording, picked by the seller after the call, uploaded
 *   as their own call as the studio does, and put on the lead;
 * - in a test workspace, a simulated call through the recording import: the
 *   API picks a fictional recording that matches the lead, saved as the lead
 *   owner's call. Nobody is dialled.
 */

import {
  AcquisitionError,
  acquisition,
  parsePolicy,
  parseSubmission,
  record,
  submissionPath,
  type Submission,
  type UploadPolicy,
} from "../acquisition-client";
import { startAnalysis } from "../analysis-start";
import { captureHeader } from "../capture-source";
import { previewImportFolder } from "../bulk-import-client";
import { inventoryImportFiles } from "../bulk-import-files";
import { readCallLabel, renameCall } from "../call-label-client";
import {
  advanceImport,
  confirmImport,
  refreshImport,
  type ImportBatch,
} from "../bulk-import-runner";
import { commandId, LeadsError, type LeadDetail } from "./leads-client";

export type SimulationPick = {
  sample_id: string;
  duration_seconds: number;
  language_mix: string;
  business_name: string;
  owner_person_id: string;
  owner_name: string;
};

export type SimulationStep =
  | "recording"
  | "saving"
  | "checking"
  | "starting"
  | "linking";

export const STEP_LABELS: Record<SimulationStep, string> = {
  recording: "Getting the test recording",
  saving: "Saving the recording as the seller's call",
  checking: "Checking the file",
  starting: "Starting the analysis",
  linking: "Adding the call to the lead",
};

const API = "/v1/lead-desk";
const STEP_MS = 3_000;
const MAX_STEPS = 80; // about four minutes of file checks at most

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    ...init,
    headers: { accept: "application/json", ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no body */
    }
    throw new LeadsError(
      detail ?? "That didn't work. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

export function pickSimulation(leadId: string) {
  return json<SimulationPick>(
    `${API}/leads/${encodeURIComponent(leadId)}/simulation`,
    { method: "POST" },
  );
}

export async function readUploadPolicy(
  signal?: AbortSignal,
): Promise<UploadPolicy> {
  return parsePolicy(await acquisition("/upload-policy", { signal }));
}

const wait = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });

/** Runs the whole simulated call; returns the lead as recorded afterwards. */
export async function runSimulatedCall({
  lead,
  pick,
  policy,
  onStep,
  signal,
  attempt = crypto.randomUUID(),
}: {
  lead: LeadDetail;
  pick: SimulationPick;
  policy: UploadPolicy;
  onStep: (step: SimulationStep) => void;
  signal: AbortSignal;
  attempt?: string;
}): Promise<LeadDetail> {
  onStep("recording");
  const audio = await fetch(
    `${API}/simulation/${encodeURIComponent(pick.sample_id)}/audio`,
    { credentials: "same-origin", cache: "no-store", signal },
  );
  if (!audio.ok)
    throw new LeadsError(
      "The test recording didn't load. Try again.",
      audio.status,
    );
  const file = new File([await audio.blob()], `${pick.sample_id}.mp3`, {
    type: "audio/mpeg",
  });

  onStep("saving");
  const selection = await inventoryImportFiles([file], { signal });
  if (selection.error !== null) throw new LeadsError(selection.error, 0);
  const preview = await previewImportFolder(selection.data.manifest, signal);
  if (preview.error !== null) throw new LeadsError(preview.error, 0);
  if (
    !preview.data.members.some(
      (member) => member.personId === pick.owner_person_id,
    )
  )
    throw new LeadsError(
      `${pick.owner_name} can't receive calls in this workspace.`,
      0,
    );
  const confirmed = await confirmImport({
    selection: selection.data,
    preview: preview.data,
    folders: Object.fromEntries(
      preview.data.folders.map((folder) => [
        folder.folder,
        pick.owner_person_id,
      ]),
    ),
    policySha: policy.policy_sha256,
    // One key per attempt: a lost response reuses it; a new attempt starts fresh.
    key: `lead-call:${lead.lead.lead_id}:${attempt}`,
    signal,
  });
  if (confirmed.error !== null) throw new LeadsError(confirmed.error, 0);

  return drive({
    batch: confirmed.data,
    selection: selection.data,
    link: async (submissionId, linkSignal) => {
      const next = await linkCall(lead, pick, submissionId, linkSignal);
      await nameCall(
        submissionId,
        `${lead.lead.name} · simulated call`,
        linkSignal,
      );
      return next;
    },
    onStep,
    signal,
  });
}

const hex = (bytes: ArrayBuffer | Uint8Array) =>
  Array.from(new Uint8Array(bytes), (n) =>
    n.toString(16).padStart(2, "0"),
  ).join("");

/** A call id fixed by its key: the key's SHA-256, shaped as a version 4 UUID. */
export async function attemptId(key: string): Promise<string> {
  const bytes = new Uint8Array(
    await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key)),
  ).slice(0, 16);
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const id = hex(bytes);
  return `${id.slice(0, 8)}-${id.slice(8, 12)}-${id.slice(12, 16)}-${id.slice(16, 20)}-${id.slice(20)}`;
}

/**
 * The seller's own upload of a recording, with the consent they ticked for
 * this call: a try that was already saved is found first, never sent again.
 * Unlike the studio's upload, it leaves the studio's open call alone.
 */
async function sendOwnSource({
  id,
  file,
  sha,
  policySha,
  signal,
}: {
  id: string;
  file: File;
  sha: string;
  policySha: string;
  signal: AbortSignal;
}): Promise<Submission> {
  const mismatch = () =>
    new LeadsError(
      "The saved call doesn't match this recording. Pick the recording again.",
      0,
    );
  try {
    const saved = parseSubmission(
      record(await acquisition(submissionPath(id), { signal })),
    );
    if (saved.id !== id || saved.sha !== sha) throw mismatch();
    return saved;
  } catch (error) {
    if (!(error instanceof AcquisitionError && error.status === 404))
      throw error;
  }
  const bound = parseSubmission(
    record(
      await acquisition(`${submissionPath(id)}/source`, {
        method: "PUT",
        signal,
        headers: {
          "Content-Type": "application/octet-stream",
          "X-Source-SHA256": sha,
          "X-Upload-Policy": policySha,
          "X-Upload-Consent": "accepted",
          ...captureHeader(file),
        },
        body: file,
      }),
    ),
  );
  if (bound.id !== id || bound.sha !== sha) throw mismatch();
  return bound;
}

/**
 * Saves a real call's recording as the seller's own call, puts it on the lead
 * and starts its analysis, as the studio does: the seller's own upload, on
 * the terms they ticked for this call. It went through the recording import
 * before, which only owners and admins may use, so a seller's tap failed
 * there (26 Oct 2026). With `callEventId` (a call already on the lead, such
 * as one the phone logged from its dialer) the recording joins that call's
 * row.
 */
export async function runRecordingUpload({
  lead,
  file,
  policy,
  onStep,
  signal,
  attempt = crypto.randomUUID(),
  callEventId = null,
}: {
  lead: LeadDetail;
  file: File;
  policy: UploadPolicy;
  onStep: (step: SimulationStep) => void;
  signal: AbortSignal;
  attempt?: string;
  callEventId?: string | null;
}): Promise<LeadDetail> {
  onStep("saving");
  // One call per attempt: trying again finds the call the first try saved
  // (the upload reads before it sends) instead of saving it twice.
  const id = await attemptId(`lead-recording:${lead.lead.lead_id}:${attempt}`);
  const sha = hex(
    await crypto.subtle.digest("SHA-256", await file.arrayBuffer()),
  );
  let bound: Submission;
  try {
    bound = await sendOwnSource({
      id,
      file,
      sha,
      policySha: policy.policy_sha256,
      signal,
    });
  } catch (error) {
    if (signal.aborted || error instanceof LeadsError) throw error;
    throw error instanceof AcquisitionError
      ? new LeadsError(error.message, error.status)
      : new LeadsError(
          "The recording didn't upload. Check your connection and try again.",
          0,
        );
  }
  // Put the call on the lead first, so closing the page never loses it.
  onStep("linking");
  // One command per attempt too: trying again never puts the call on the lead
  // twice.
  const linked = await attachRecording(
    lead,
    bound.id,
    signal,
    callEventId,
    await attemptId(`lead-recording-attach:${lead.lead.lead_id}:${attempt}`),
  );
  await nameCall(bound.id, `${lead.lead.name} · call`, signal);
  const started = await startAnalysis(
    {
      bound,
      sourceSha256: sha,
      policySha256: policy.policy_sha256,
      // An English report, as the recording import started it.
      reportLanguage: "en",
      supportsLanguage: true,
      paused: false,
    },
    signal,
    onStep,
  );
  if (started.kind === "needs_action") throw new LeadsError(started.message, 0);
  onStep("starting");
  return linked;
}

/** Runs the import until the call is on the lead and its analysis has started. */
async function drive({
  batch: first,
  selection,
  link,
  onStep,
  signal,
}: {
  batch: ImportBatch;
  selection: Parameters<typeof advanceImport>[1];
  link: (submissionId: string, signal: AbortSignal) => Promise<LeadDetail>;
  onStep: (step: SimulationStep) => void;
  signal: AbortSignal;
}): Promise<LeadDetail> {
  let batch = first;
  let linked: LeadDetail | null = null;
  for (let step = 0; step < MAX_STEPS; step++) {
    const item = batch.items[0];
    if (!item) break;
    if (
      ["failed", "expired", "unavailable", "needs_member"].includes(item.state)
    )
      throw new LeadsError(
        "The recording was saved but its analysis needs attention. Open Calls to review it.",
        0,
      );
    if (item.submissionId) {
      if (!linked) {
        // Put the call on the lead first, so closing the page never loses it.
        onStep("linking");
        linked = await link(item.submissionId, signal);
      }
      if (
        item.state === "done" ||
        (await analysisStarted(item.submissionId, signal))
      ) {
        onStep("starting");
        return linked;
      }
      onStep("checking");
    }
    const advanced = await advanceImport(batch, selection, signal);
    if (advanced.error !== null)
      throw new LeadsError(
        linked
          ? `The call is on the lead, but its analysis didn't start: ${advanced.error}`
          : advanced.error,
        0,
      );
    await wait(STEP_MS, signal);
    const refreshed = await refreshImport(batch, signal);
    if (refreshed.error !== null) throw new LeadsError(refreshed.error, 0);
    batch = refreshed.data;
  }
  throw new LeadsError(
    linked
      ? "The call is on the lead, but its file checks are slow today. Open the call later to start its analysis."
      : "The recording is still being checked. It will appear under Calls; try the lead again shortly.",
    0,
  );
}

/** True once the analysis plan is accepted (or the call already has a report). */
async function analysisStarted(
  submissionId: string,
  signal: AbortSignal,
): Promise<boolean> {
  try {
    const progress = (await acquisition(`/submissions/${submissionId}`, {
      signal,
      headers: { accept: "application/json" },
    })) as { has_report?: unknown; automatic_progression?: unknown };
    if (progress.has_report === true || progress.automatic_progression === true)
      return true;
    const plan = (await acquisition(`/submissions/${submissionId}/plan`, {
      signal,
      headers: { accept: "application/json" },
    })) as { accepted?: unknown };
    return plan.accepted === true;
  } catch (error) {
    if (signal.aborted) throw error;
    return false;
  }
}

function attachRecording(
  lead: LeadDetail,
  submissionId: string,
  signal: AbortSignal,
  callEventId: string | null,
  command: string = commandId(),
) {
  return json<LeadDetail>(
    `${API}/leads/${encodeURIComponent(lead.lead.lead_id)}/recordings`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        command_id: command,
        submission_id: submissionId,
        ...(callEventId ? { call_event_id: callEventId } : {}),
      }),
      signal,
    },
  );
}

function linkCall(
  lead: LeadDetail,
  pick: SimulationPick,
  submissionId: string,
  signal: AbortSignal,
) {
  return json<LeadDetail>(
    `${API}/leads/${encodeURIComponent(lead.lead.lead_id)}/calls`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        command_id: commandId(),
        submission_id: submissionId,
        simulated: true,
        duration_seconds: pick.duration_seconds,
        sample: pick.sample_id,
      }),
      signal,
    },
  );
}

/** Best effort: the call's Report is titled after the lead instead of "Untitled call". */
async function nameCall(
  submissionId: string,
  title: string,
  signal: AbortSignal,
): Promise<void> {
  try {
    const label = await readCallLabel(submissionId, signal);
    if (label && !label.displayName)
      await renameCall(
        submissionId,
        title.slice(0, 80),
        label.revision,
        signal,
      );
  } catch (error) {
    if (signal.aborted) throw error;
    // Only the seller may rename their call; otherwise it keeps its default name.
  }
}
