/**
 * A simulated call from the desk (Sales Xray CRM slice d).
 *
 * The API picks a fictional sales-call recording that matches the lead; this
 * file then saves it as the lead owner's call through the existing recording
 * import (the same consent, file checks, plan and analysis as any upload) and
 * records the call on the lead. Nobody is dialled.
 */

import {
  acquisition,
  parsePolicy,
  type UploadPolicy,
} from "../acquisition-client";
import { previewImportFolder } from "../bulk-import-client";
import { inventoryImportFiles } from "../bulk-import-files";
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
  saving: "Saving it as the seller's call",
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
      detail ?? "The simulated call couldn't start. Try again.",
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

  let batch: ImportBatch = confirmed.data;
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
        linked = await linkCall(lead, pick, item.submissionId, signal);
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
    const advanced = await advanceImport(batch, selection.data, signal);
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
