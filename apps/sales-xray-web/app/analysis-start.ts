import {
  AcquisitionError,
  acquisition,
  parseProgress,
  submissionPath,
  type Submission,
} from "./acquisition-client";
import { parseProcessingPlan, type ProcessingPlan } from "./call-studio";
import {
  STATUS_READ_TIMEOUT_MS,
  readProcessingPlan,
} from "./observe-submission";

// A saved source is not yet ready for analysis: native file checks finish
// asynchronously. Bound the owner reads that wait for them.
export const NATIVE_CHECK_READS = 40;
export const NATIVE_CHECK_INTERVAL_MS = 3_000;
export const NATIVE_CHECK_DEADLINE_MS = 120_000;

/** Fixed when the owner clicks Analyse; never re-read from later view state. */
export type AnalysisStartRequest = Readonly<{
  bound: Submission;
  /** The digest hashed locally from the selected File. */
  sourceSha256: string;
  /** The upload policy the consent was given for. */
  policySha256: string;
  reportLanguage: string;
  supportsLanguage: boolean;
  paused: boolean;
}>;

export type AnalysisStartPhase = "checking" | "starting";

export type AnalysisStartReason =
  | "checks_pending"
  | "needs_attention"
  | "language_mismatch"
  | "source_mismatch"
  | "plan_expired"
  | "paused"
  | "start_failed";

export type AnalysisStartOutcome =
  | Readonly<{
      kind: "accepted";
      /** Null when the server was already progressing or had a report. */
      plan: ProcessingPlan | null;
    }>
  | Readonly<{
      kind: "needs_action";
      reason: AnalysisStartReason;
      message: string;
    }>;

const COPY: Record<Exclude<AnalysisStartReason, "start_failed">, string> = {
  checks_pending:
    "Your recording is saved. Its file checks are still running, so analysis has not started. Open the call to check again.",
  needs_attention:
    "Your recording is saved, but it needs attention before analysis can start. Open the call to review it.",
  language_mismatch:
    "Your recording is saved. The analysis plan did not confirm your chosen report language, so it was not started. Open the call to review it.",
  source_mismatch:
    "Your recording is saved, but it did not match the file you chose, so analysis was not started. Open the call to review it.",
  plan_expired:
    "Your recording is saved. Its analysis plan expired before it started. Open the call to review a fresh plan.",
  paused:
    "Your recording is saved. Analysis is paused right now; open the call to start it when it resumes.",
};

function needsAction(
  reason: AnalysisStartReason,
  error?: unknown,
): AnalysisStartOutcome {
  return {
    kind: "needs_action",
    reason,
    message:
      reason !== "start_failed"
        ? COPY[reason]
        : error instanceof AcquisitionError
          ? error.message
          : "Your recording is saved, but analysis could not be started. Open the call to try again.",
  };
}

/** The same continuation key the studio uses for this call and language. */
export function reportPlanKey(
  bound: Submission,
  language: string,
  supportsLanguage: boolean,
) {
  // Continuation keys permit letters, numbers, underscores, dots, colons and
  // hyphens. Keep each language distinct without sending its `+`.
  return `report-plan:${bound.id}${supportsLanguage ? `:${language.replaceAll("+", "_")}` : ""}`;
}

async function boundedRequest(
  path: string,
  parent: AbortSignal,
  init: RequestInit = {},
  timeoutMs = STATUS_READ_TIMEOUT_MS,
) {
  const request = new AbortController();
  let timedOut = false;
  const cancel = () => request.abort(parent.reason);
  parent.addEventListener("abort", cancel, { once: true });
  if (parent.aborted) cancel();
  const timeout = setTimeout(() => {
    timedOut = true;
    request.abort(new DOMException("Request timed out", "TimeoutError"));
  }, timeoutMs);
  try {
    if (parent.aborted) throw new DOMException("Aborted", "AbortError");
    return await acquisition(path, { ...init, signal: request.signal });
  } catch (error) {
    if (timedOut && !parent.aborted)
      throw new DOMException("Request timed out", "TimeoutError");
    throw error;
  } finally {
    clearTimeout(timeout);
    parent.removeEventListener("abort", cancel);
  }
}

function wait(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const stop = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", stop);
      resolve();
    }, ms);
    signal.addEventListener("abort", stop, { once: true });
    if (signal.aborted) stop();
  });
}

/**
 * Starts analysis once for a source saved from one intentional Analyse click.
 * It waits on canonical GET progress, adopts work the server already owns, and
 * otherwise quotes and accepts the same plan once. Anything uncertain settles
 * to a visible action; it never retries paid work or restarts a provider.
 */
export async function startAnalysis(
  request: AnalysisStartRequest,
  signal: AbortSignal,
  onPhase: (phase: AnalysisStartPhase) => void,
  timing: Readonly<{ reads: number; intervalMs: number }> = {
    reads: NATIVE_CHECK_READS,
    intervalMs: NATIVE_CHECK_INTERVAL_MS,
  },
): Promise<AnalysisStartOutcome> {
  const { bound } = request;
  if (!request.policySha256 || bound.sha !== request.sourceSha256)
    return needsAction("source_mismatch");
  if (request.paused) return needsAction("paused");

  onPhase("checking");
  let ready = false;
  const checksDeadline = Date.now() + NATIVE_CHECK_DEADLINE_MS;
  for (let read = 0; read < timing.reads && !ready; read++) {
    if (read)
      await wait(
        Math.min(timing.intervalMs, Math.max(0, checksDeadline - Date.now())),
        signal,
      );
    const remaining = checksDeadline - Date.now();
    if (remaining <= 0) break;
    let progress;
    try {
      progress = parseProgress(
        await boundedRequest(
          submissionPath(bound.id),
          signal,
          {},
          Math.min(remaining, STATUS_READ_TIMEOUT_MS),
        ),
        bound,
      );
    } catch (error) {
      if (signal.aborted) throw error;
      if (
        error instanceof AcquisitionError &&
        [401, 403, 404].includes(error.status)
      )
        return needsAction("start_failed", error);
      continue;
    }
    if (progress.has_report || progress.automatic_progression)
      return { kind: "accepted", plan: null };
    if (
      progress.local_state === "failed" ||
      progress.local_state === "cancelled" ||
      ["held", "cancelled", "completed"].includes(progress.state)
    )
      return needsAction("needs_attention");
    ready = progress.local_state === "completed";
  }
  if (!ready) return needsAction("checks_pending");

  onPhase("starting");
  let shown: ProcessingPlan;
  try {
    shown = parseProcessingPlan(
      await boundedRequest(`${submissionPath(bound.id)}/plan/quote`, signal, {
        method: "POST",
        signal,
        headers: {
          "Idempotency-Key": reportPlanKey(
            bound,
            request.reportLanguage,
            request.supportsLanguage,
          ),
          ...(request.supportsLanguage
            ? { "Content-Type": "application/json" }
            : {}),
        },
        ...(request.supportsLanguage
          ? {
              body: JSON.stringify({ report_language: request.reportLanguage }),
            }
          : {}),
      }),
      bound.recordingId,
    );
  } catch (error) {
    if (signal.aborted) throw error;
    return needsAction("start_failed", error);
  }
  if (
    request.supportsLanguage &&
    shown.report_language !== request.reportLanguage
  )
    return needsAction("language_mismatch");
  if (shown.accepted) return { kind: "accepted", plan: shown };
  if (shown.expires_at_epoch * 1000 <= Date.now())
    return needsAction("plan_expired");

  let accepted: ProcessingPlan;
  try {
    accepted = parseProcessingPlan(
      await boundedRequest(`${submissionPath(bound.id)}/plan`, signal, {
        method: "POST",
        signal,
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `accept-plan:${shown.id}`,
        },
        body: JSON.stringify({
          plan_id: shown.id,
          plan_fingerprint: shown.plan_fingerprint,
          privacy_revision: shown.privacy_revision,
          accepted: true,
        }),
      }),
      bound.recordingId,
    );
  } catch (error) {
    if (signal.aborted) throw error;
    // A failed response can arrive after the server accepted this exact plan.
    // Reconcile with one owner read; never send the acceptance again.
    const mayHaveAccepted =
      error instanceof TypeError ||
      (error instanceof DOMException && error.name === "TimeoutError") ||
      (error instanceof AcquisitionError &&
        error.status >= 500 &&
        error.reason !== "execution_paused");
    if (!mayHaveAccepted) return needsAction("start_failed", error);
    try {
      accepted = await readProcessingPlan(bound, signal);
    } catch {
      if (signal.aborted) throw error;
      return needsAction("start_failed", error);
    }
    if (!accepted.accepted) return needsAction("start_failed", error);
  }
  if (
    accepted.id !== shown.id ||
    accepted.plan_fingerprint !== shown.plan_fingerprint
  )
    return needsAction("start_failed");
  return {
    kind: "accepted",
    plan: {
      ...accepted,
      ...(shown.report_language
        ? {
            report_language: shown.report_language,
            coaching_prompt_revision: shown.coaching_prompt_revision,
          }
        : {}),
    },
  };
}
