import {
  AcquisitionError,
  acquisition,
  parseSubmission,
  record,
  rememberPendingUpload,
  rememberSubmission,
  submissionPath,
  type Submission,
} from "../acquisition-client";

export type SourceUploadOutcome = Readonly<{
  submissionId: string;
  bound: Submission;
  raw: Record<string, unknown>;
  /** True when an earlier attempt had already been accepted by the server. */
  recovered: boolean;
}>;

export type SourceReconciliation =
  | Readonly<{ kind: "missing" }>
  | Readonly<{
      kind: "saved";
      submissionId: string;
      bound: Submission;
      raw: Record<string, unknown>;
    }>;

export type CurrentUploadConsent = Readonly<{
  accepted: boolean;
  /** The exact policy whose upload-consent control the user accepted. */
  policySha256: string;
}>;

/** A safe GET only. It never needs consent and never retries the upload. */
export async function reconcileSource({
  id,
  sha,
  signal,
}: {
  id: string;
  sha: string;
  signal: AbortSignal;
}): Promise<SourceReconciliation> {
  let raw: Record<string, unknown>;
  try {
    raw = record(await acquisition(submissionPath(id), { signal }));
    signal.throwIfAborted();
  } catch (error) {
    if (error instanceof AcquisitionError && error.status === 404) {
      signal.throwIfAborted();
      return { kind: "missing" };
    }
    throw error;
  }
  const bound = parseSubmission(raw);
  if (bound.id !== id || bound.sha !== sha)
    throw new Error("uploaded_source_mismatch");
  signal.throwIfAborted();
  rememberSubmission(bound.id);
  rememberPendingUpload(null);
  return { kind: "saved", submissionId: bound.id, bound, raw };
}

/**
 * Sends one consented recording through the shared acquisition fetch, so the
 * request keeps `credentials: "same-origin"` and `redirect: "error"`.
 *
 * Every attempt reads the same opaque submission first. A repeat PUT is
 * allowed only after that read returns 404 and the current upload consent is
 * explicitly accepted for the exact current policy. Denied, malformed or
 * unavailable reads never authorize another PUT.
 *
 * Only opaque selectors are stored: the id is "pending" until the server binds
 * the exact source, and becomes the saved-call selector only after that.
 */
export async function sendSource({
  id,
  file,
  sha,
  policySha,
  uploadConsent,
  signal,
  onPut,
}: {
  id: string;
  file: Blob;
  sha: string;
  policySha: string;
  uploadConsent: CurrentUploadConsent;
  signal: AbortSignal;
  onPut?: () => void;
}): Promise<SourceUploadOutcome> {
  const reconciled = await reconcileSource({ id, sha, signal });
  signal.throwIfAborted();
  if (reconciled.kind === "saved") {
    return {
      submissionId: reconciled.submissionId,
      bound: reconciled.bound,
      raw: reconciled.raw,
      recovered: true,
    };
  }

  // Read-only recovery does not require fresh consent. A new source PUT does.
  if (
    !uploadConsent ||
    uploadConsent.accepted !== true ||
    uploadConsent.policySha256 !== policySha
  )
    throw new Error("current_upload_consent_required");

  signal.throwIfAborted();
  rememberPendingUpload(id);
  onPut?.();
  const raw = record(
    await acquisition(`${submissionPath(id)}/source`, {
      method: "PUT",
      signal,
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Source-SHA256": sha,
        "X-Upload-Policy": policySha,
        "X-Upload-Consent": "accepted",
      },
      body: file,
    }),
  );
  signal.throwIfAborted();
  const bound = parseSubmission(raw);
  if (bound.id !== id || bound.sha !== sha)
    throw new Error("uploaded_source_mismatch");
  signal.throwIfAborted();
  rememberSubmission(bound.id);
  rememberPendingUpload(null);
  return { submissionId: bound.id, bound, raw, recovered: false };
}
