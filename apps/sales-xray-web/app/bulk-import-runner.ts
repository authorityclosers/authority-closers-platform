import {
  ACQUISITION,
  MAX_ACQUISITION_FILE_BYTES,
  UUID,
} from "./acquisition-client";
import type { ImportPreview } from "./bulk-import-client";
import type { ImportResult, ImportSelection } from "./bulk-import-files";
import { parseProcessingPlan } from "./processing-plan-contract";

export type ImportItem = {
  index: number;
  sha: string;
  bytes: number;
  personId: string | null;
  uploadId: string;
  submissionId: string | null;
  state: string;
  stage: string | null;
  minuteState: string | null;
  retryAvailable: boolean;
  runState: string | null;
};
export type ImportBatch = {
  id: string;
  tenantId: string;
  manifestSha: string;
  policySha: string;
  expiresAt: string;
  terminalState: "done" | "failed" | null;
  items: ImportItem[];
};
const SHA = /^[a-f0-9]{64}$/;
const STATES = new Set([
  "awaiting_upload",
  "needs_member",
  "expired",
  "already_imported",
  "queued",
  "working",
  "retrying",
  "failed",
  "done",
  "unavailable",
]);
const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
const uuid = (value: unknown): value is string =>
  typeof value === "string" && UUID.test(value);
const sha = (value: unknown): value is string =>
  typeof value === "string" && SHA.test(value);

export function readImportBatch(value: unknown): ImportBatch | null {
  const row = object(value);
  if (
    !row ||
    !uuid(row.batch_id) ||
    !uuid(row.tenant_id) ||
    !sha(row.manifest_sha256) ||
    !sha(row.policy_sha256) ||
    typeof row.expires_at !== "string" ||
    !Number.isFinite(Date.parse(row.expires_at)) ||
    ![null, "done", "failed"].includes(row.terminal_state as string | null) ||
    !Array.isArray(row.files) ||
    row.files.length < 1 ||
    row.files.length > 256 ||
    row.total_files !== row.files.length
  )
    return null;
  const items: ImportItem[] = [];
  for (const [index, raw] of row.files.entries()) {
    const file = object(raw);
    if (
      !file ||
      file.item_index !== index ||
      !sha(file.source_sha256) ||
      !Number.isSafeInteger(file.source_bytes) ||
      (file.source_bytes as number) < 1 ||
      (file.source_bytes as number) > MAX_ACQUISITION_FILE_BYTES ||
      !uuid(file.upload_submission_id) ||
      (file.person_id !== null && !uuid(file.person_id)) ||
      (file.submission_id !== null && !uuid(file.submission_id)) ||
      typeof file.state !== "string" ||
      !STATES.has(file.state) ||
      (file.current_stage !== null &&
        !/^C[0-6]$/.test(String(file.current_stage))) ||
      ![null, "reserved", "released", "delivered"].includes(
        file.minute_state as string | null,
      ) ||
      typeof file.retry_available !== "boolean"
    )
      return null;
    items.push({
      index,
      sha: file.source_sha256,
      bytes: file.source_bytes as number,
      personId: file.person_id as string | null,
      uploadId: file.upload_submission_id,
      submissionId: file.submission_id as string | null,
      state: file.state,
      stage: file.current_stage as string | null,
      minuteState: file.minute_state as string | null,
      retryAvailable: file.retry_available,
      runState:
        typeof file.run_state === "string" &&
        ["queued", "working", "retrying", "failed", "done"].includes(
          file.run_state,
        )
          ? file.run_state
          : null,
    });
  }
  if (
    items.reduce((sum, item) => sum + item.bytes, 0) !== row.total_bytes ||
    (row.total_bytes as number) > 1024 ** 3
  )
    return null;
  return {
    id: row.batch_id,
    tenantId: row.tenant_id,
    manifestSha: row.manifest_sha256,
    policySha: row.policy_sha256,
    expiresAt: row.expires_at,
    terminalState: row.terminal_state as ImportBatch["terminalState"],
    items,
  };
}

type ResponseResult = ImportResult<unknown> & { status: number };
async function request(
  path: string,
  init: RequestInit = {},
): Promise<ResponseResult> {
  const abort = new AbortController();
  const cancel = () => abort.abort();
  init.signal?.addEventListener("abort", cancel, { once: true });
  if (init.signal?.aborted) cancel();
  const timer = setTimeout(cancel, init.method === "PUT" ? 180_000 : 15_000);
  try {
    const response = await fetch(`${ACQUISITION}${path}`, {
      ...init,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: abort.signal,
    });
    const data: unknown = await response.json();
    if (!response.ok) {
      const detail = object(data)?.detail;
      return {
        data: null,
        status: response.status,
        error:
          typeof detail === "string" && detail.length <= 300
            ? detail
            : "Import is unavailable. Try again shortly.",
      };
    }
    return { data, error: null, status: response.status };
  } catch {
    return {
      data: null,
      status: 0,
      error: init.signal?.aborted
        ? "Import paused. Saved recordings are safe; resume to continue."
        : "Import did not finish. Check your connection and resume.",
    };
  } finally {
    clearTimeout(timer);
    init.signal?.removeEventListener("abort", cancel);
  }
}
const headers = (batch: ImportBatch, item: ImportItem) => ({
  "X-Recording-Import": batch.id,
  "X-Recording-Import-Item": String(item.index),
});
const unavailable = (): ImportResult<never> => ({
  data: null,
  error: "Import progress is unavailable. Try again shortly.",
});

export async function confirmImport({
  selection,
  preview,
  folders,
  policySha,
  key,
  signal,
}: {
  selection: ImportSelection;
  preview: ImportPreview;
  folders: Record<string, string | null>;
  policySha: string;
  key: string;
  signal: AbortSignal;
}): Promise<ImportResult<ImportBatch>> {
  if (
    !SHA.test(policySha) ||
    preview.folders.some(
      (folder) =>
        !(folder.folder in folders) ||
        (folders[folder.folder] !== null &&
          !preview.members.some(
            (member) => member.personId === folders[folder.folder],
          )),
    )
  )
    return unavailable();
  const result = await request("/imports", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify({
      manifest: selection.manifest,
      manifest_sha256: preview.manifestSha,
      policy_sha256: policySha,
      rights_confirmed: true,
      folders: preview.folders.map((folder) => ({
        folder: folder.folder,
        person_id: folders[folder.folder],
      })),
    }),
  });
  if (result.error !== null) return { data: null, error: result.error };
  const batch = readImportBatch(result.data);
  return batch &&
    batch.tenantId === preview.tenantId &&
    batch.manifestSha === preview.manifestSha &&
    batch.policySha === policySha
    ? { data: batch, error: null }
    : unavailable();
}

export async function refreshImport(
  batch: ImportBatch,
  signal: AbortSignal,
): Promise<ImportResult<ImportBatch>> {
  const result = await request(`/imports/${batch.id}`, { signal });
  if (result.error !== null) return { data: null, error: result.error };
  const next = readImportBatch(result.data);
  return next &&
    next.id === batch.id &&
    next.tenantId === batch.tenantId &&
    next.manifestSha === batch.manifestSha &&
    next.policySha === batch.policySha
    ? { data: next, error: null }
    : unavailable();
}

/** One bounded step under consent held by the mounted import view. No failed-call auto retry. */
export async function advanceImport(
  batch: ImportBatch,
  selection: ImportSelection,
  signal: AbortSignal,
): Promise<ImportResult<null>> {
  const active = batch.items.find((item) =>
    ["queued", "working", "retrying"].includes(item.state),
  );
  if (active && active.submissionId) {
    const path = `/submissions/${active.submissionId}`;
    const response = await request(path, {
      signal,
      headers: headers(batch, active),
    });
    if (response.error !== null) return { data: null, error: response.error };
    const progress = object(response.data);
    if (
      !progress ||
      progress.source_sha256 !== active.sha ||
      !uuid(progress.recording_id)
    )
      return unavailable();
    if (
      progress.local_state !== "completed" ||
      progress.automatic_progression ||
      progress.has_report ||
      progress.run_state === "failed"
    )
      return { data: null, error: null };
    const saved = await request(`${path}/plan`, {
      signal,
      headers: headers(batch, active),
    });
    if (saved.error !== null && saved.status !== 404)
      return { data: null, error: saved.error };
    const quoted =
      saved.status === 404
        ? await request(`${path}/plan/quote`, {
            method: "POST",
            signal,
            headers: {
              ...headers(batch, active),
              "Content-Type": "application/json",
              "Idempotency-Key": `import-plan:${batch.id}:${active.index}`,
            },
            body: JSON.stringify({ report_language: "en" }),
          })
        : saved;
    if (quoted.error !== null) return { data: null, error: quoted.error };
    try {
      const plan = parseProcessingPlan(quoted.data, progress.recording_id);
      if (plan.accepted) return { data: null, error: null };
      if (
        plan.state !== "quoted" ||
        plan.expires_at_epoch * 1000 <= Date.now() ||
        plan.report_language !== "en"
      )
        return {
          data: null,
          error: "This plan needs attention. Open the call to review it.",
        };
      const accepted = await request(`${path}/plan`, {
        method: "POST",
        signal,
        headers: {
          ...headers(batch, active),
          "Content-Type": "application/json",
          "Idempotency-Key": `accept-plan:${plan.id}`,
        },
        body: JSON.stringify({
          plan_id: plan.id,
          plan_fingerprint: plan.plan_fingerprint,
          privacy_revision: plan.privacy_revision,
          accepted: true,
        }),
      });
      if (accepted.error !== null) return { data: null, error: accepted.error };
      const actual = parseProcessingPlan(accepted.data, progress.recording_id);
      return actual.id === plan.id &&
        actual.plan_fingerprint === plan.plan_fingerprint &&
        actual.accepted
        ? { data: null, error: null }
        : unavailable();
    } catch {
      return unavailable();
    }
  }
  if (active) return unavailable();
  const pending = batch.items.find((item) => item.state === "awaiting_upload");
  if (!pending) return { data: null, error: null };
  const source = selection.manifest.files[pending.index];
  const file = source && selection.files.get(source.relative_path);
  if (
    !file ||
    source.source_sha256 !== pending.sha ||
    source.source_bytes !== pending.bytes ||
    file.size !== pending.bytes
  )
    return {
      data: null,
      error: "Reselect the same folder to resume this import.",
    };
  const result = await request(`/submissions/${pending.uploadId}/source`, {
    method: "PUT",
    signal,
    headers: {
      ...headers(batch, pending),
      "Content-Type": "application/octet-stream",
      "X-Source-SHA256": pending.sha,
      "X-Upload-Policy": batch.policySha,
      "X-Upload-Consent": "accepted",
    },
    body: file,
  });
  if (result.error !== null) return { data: null, error: result.error };
  const uploaded = object(result.data);
  return uploaded &&
    uploaded.source_sha256 === pending.sha &&
    uuid(uploaded.submission_id)
    ? { data: null, error: null }
    : unavailable();
}

export async function retryImportItem(
  batch: ImportBatch,
  item: ImportItem,
  key: string,
  signal: AbortSignal,
): Promise<ImportResult<null>> {
  if (!item.retryAvailable || item.state !== "failed" || !item.submissionId)
    return unavailable();
  const result = await request(`/submissions/${item.submissionId}/retry`, {
    method: "POST",
    signal,
    headers: { ...headers(batch, item), "Idempotency-Key": key },
  });
  if (result.error !== null) return { data: null, error: result.error };
  const receipt = object(result.data);
  if (!receipt || !uuid(receipt.recording_id)) return unavailable();
  if (receipt.retry_kind === "local")
    return uuid(receipt.run_id) ? { data: null, error: null } : unavailable();
  try {
    const plan = parseProcessingPlan(receipt, receipt.recording_id);
    return plan.state === "quoted" && !plan.accepted
      ? { data: null, error: null }
      : unavailable();
  } catch {
    return unavailable();
  }
}
