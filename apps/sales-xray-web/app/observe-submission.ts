import {
  acquisition,
  parseProgress,
  submissionPath,
  type Submission,
} from "./acquisition-client";
import { parseProcessingPlan } from "./call-studio";
import { parseAcquisitionReport, parseTranscript } from "./report-contract";

// Bound a status read, not provider execution. A timeout leaves the last saved
// stage intact and allows the user to check again without starting work.
export const STATUS_READ_TIMEOUT_MS = 30_000;
async function read(path: string, parent: AbortSignal) {
  const request = new AbortController();
  const cancel = () => request.abort(parent.reason);
  parent.addEventListener("abort", cancel, { once: true });
  if (parent.aborted) cancel();
  const timeout = setTimeout(
    () =>
      request.abort(new DOMException("Status read timed out", "TimeoutError")),
    STATUS_READ_TIMEOUT_MS,
  );
  try {
    return await acquisition(path, { signal: request.signal });
  } finally {
    clearTimeout(timeout);
    parent.removeEventListener("abort", cancel);
  }
}

export async function readProcessingPlan(
  bound: Submission,
  signal: AbortSignal,
) {
  return parseProcessingPlan(
    await read(`${submissionPath(bound.id)}/plan`, signal),
    bound.recordingId,
  );
}

// Status observation is deliberately GET-only. Approval and recovery commands
// belong to explicit, separately authorized flows in the studio.
export async function observeSubmission(
  bound: Submission,
  signal: AbortSignal,
) {
  const progress = parseProgress(
    await read(submissionPath(bound.id), signal),
    bound,
  );
  if (!progress.has_report) return { progress, result: null };
  const transcript = parseTranscript(
    await read(`${submissionPath(bound.id)}/transcript`, signal),
    bound.sha,
  );
  const verified = parseAcquisitionReport(
    await read(`${submissionPath(bound.id)}/report`, signal),
    { submissionId: bound.id, recordingId: bound.recordingId },
    transcript,
  );
  return { progress, result: { ...verified, transcript } };
}
