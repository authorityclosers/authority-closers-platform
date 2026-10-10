import {
  ACQUISITION,
  UUID,
  parseProgress,
  parseSubmission,
  submissionPath,
  type Progress,
  type Submission,
} from "./acquisition-client";
import { parseAcquisitionReport, parseTranscript } from "./report-contract";

/** A request-scoped, authorised GET supplied by the server route owner. */
export type SavedReportRead = (
  path: string,
  signal: AbortSignal,
) => Promise<unknown>;

type ReadyResult = ReturnType<typeof parseAcquisitionReport> & {
  transcript: ReturnType<typeof parseTranscript>;
  callRecord: null;
};
export type SavedReportPreload =
  | {
      state: "ready";
      submission: Submission;
      progress: Progress;
      result: ReadyResult;
    }
  | {
      state: "processing";
      submission: Submission;
      progress: Progress;
      result: null;
    }
  | { state: "unavailable"; message: string; result: null };

const UNAVAILABLE: SavedReportPreload = {
  state: "unavailable",
  message: "This saved call is unavailable. Try again.",
  result: null,
};
export const SAVED_REPORT_READ_TIMEOUT_MS = 15_000;

/**
 * One canonical submission read, followed by parallel retained C2/C5 reads.
 * No approval, execution, detection or cache. The route must bind its GET port
 * to the current session/workspace and keep credentials out of returned props.
 * A missing route/field or stale source returns a small unavailable state.
 */
export async function preloadSavedReport(
  callId: string,
  read: SavedReportRead,
  parent?: AbortSignal,
): Promise<SavedReportPreload> {
  if (!UUID.test(callId)) return UNAVAILABLE;
  const timeout = new AbortController();
  const signal = parent
    ? AbortSignal.any([parent, timeout.signal])
    : timeout.signal;
  const timer = setTimeout(() => timeout.abort(), SAVED_REPORT_READ_TIMEOUT_MS);
  async function get(path: string) {
    if (signal.aborted) throw new Error("saved_report_read_cancelled");
    let cancel: () => void = () => {};
    const aborted = new Promise<never>((_, reject) => {
      cancel = () => reject(new Error("saved_report_read_cancelled"));
      signal.addEventListener("abort", cancel, { once: true });
    });
    try {
      // Bound even if a defective adapter fails to honour AbortSignal.
      return await Promise.race([read(ACQUISITION + path, signal), aborted]);
    } finally {
      signal.removeEventListener("abort", cancel);
    }
  }
  try {
    const path = submissionPath(callId);
    const payload = await get(path);
    const submission = parseSubmission(payload);
    if (submission.id !== callId) return UNAVAILABLE;
    const progress = parseProgress(payload, submission);
    if (!progress.has_report)
      return { state: "processing", submission, progress, result: null };
    const [transcriptPayload, reportPayload] = await Promise.all([
      get(`${path}/transcript`),
      get(`${path}/report`),
    ]);
    const transcript = parseTranscript(transcriptPayload, submission.sha);
    const report = parseAcquisitionReport(
      reportPayload,
      { submissionId: submission.id, recordingId: submission.recordingId },
      transcript,
    );
    return {
      state: "ready",
      submission,
      progress,
      result: { ...report, transcript, callRecord: null },
    };
  } catch {
    return UNAVAILABLE;
  } finally {
    clearTimeout(timer);
    timeout.abort();
  }
}
