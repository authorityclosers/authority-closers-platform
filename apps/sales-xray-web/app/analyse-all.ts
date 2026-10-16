import { ACQUISITION, UUID } from "./acquisition-client";
import {
  parseProcessingPlan,
  type ProcessingPlan,
} from "./processing-plan-contract";

/**
 * "Analyse all not-analysed calls" (16 Oct, dev): the signed-in owner starts
 * analysis for their own saved calls that never started, one call at a time,
 * through the same quote -> accept path as a single Start analysis. The
 * server's admission and budget checks run for every call; nothing here
 * accepts a plan the server did not quote for that call, and each plan is
 * accepted at most once (`accept-plan:<plan id>`, the studio's own key).
 */

/** Dev only until the owner ships it (16 Oct): the dev site and local runs. */
const HOSTS = new Set([
  "salesxray-dev.authorityclosers.com",
  "localhost",
  "127.0.0.1",
]);
export const analyseAllHost = () => HOSTS.has(window.location.hostname);
export const noHostChanges = () => () => {};

/** Exact server refusal when the analysis budget can't cover a call's plan. */
const BUDGET_REFUSAL = "The provider budget cannot cover this complete plan.";
const LIST_PATH = "/submissions?include_owners=true&order=reports_first";
const MAX_PAGES = 50;

export type SkipReason = "started" | "checks" | "attention";

export type PlannedCall = Readonly<{
  id: string;
  recordingId: string;
  plan: ProcessingPlan;
}>;

export type Preparation = Readonly<{
  planned: PlannedCall[];
  skipped: ReadonlyArray<Readonly<{ id: string; reason: SkipReason }>>;
  /** Sum of each planned call's maximum (the quote), in paise. */
  maxCostPaise: number;
  /** The budget refused a quote: the calls after it were not prepared. */
  budgetStopped: boolean;
}>;

export type CallRun =
  | "waiting"
  | "starting"
  | "analysing"
  | "done"
  | "failed"
  | "not_started";

export type RunResult = Readonly<{
  started: number;
  done: number;
  failed: number;
  stoppedBy: "budget" | "cancelled" | null;
}>;

type Answer = Readonly<{ status: number; body: unknown }>;

const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

/** The known refusal text only; server bodies are never shown to people. */
function refusedForBudget(answer: Answer) {
  return (
    answer.status === 409 && object(answer.body)?.detail === BUDGET_REFUSAL
  );
}

async function call(
  path: string,
  signal: AbortSignal,
  init: RequestInit = {},
): Promise<Answer> {
  const response = await fetch(ACQUISITION + path, {
    ...init,
    signal,
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    headers: { accept: "application/json", ...init.headers },
  });
  return {
    status: response.status,
    body: await response.json().catch(() => null),
  };
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
 * Every saved call of the signed-in person that never started analysis,
 * across all list pages (newest first). Calls of other people (an
 * organisation owner reading members' calls) are not theirs to start.
 */
export async function notAnalysedCalls(
  viewerId: string | null,
  signal: AbortSignal,
  /** An organisation owner/admin may start members' calls too (16 Oct). */
  everyone = false,
): Promise<string[]> {
  const ids: string[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < MAX_PAGES; page++) {
    const answer = await call(
      cursor ? `${LIST_PATH}&before=${encodeURIComponent(cursor)}` : LIST_PATH,
      signal,
    );
    const body = object(answer.body);
    if (answer.status !== 200 || !body || !Array.isArray(body.submissions))
      throw new Error("library_unavailable");
    for (const value of body.submissions) {
      const row = object(value);
      if (!row || typeof row.submission_id !== "string") continue;
      if (!UUID.test(row.submission_id)) continue;
      // A row carries an owner only where the viewer reads others' calls.
      const mine =
        everyone ||
        typeof row.owner_person_id !== "string" ||
        (viewerId !== null && row.owner_person_id === viewerId);
      if (
        mine &&
        row.has_report !== true &&
        (row.state === "ready" || row.state === "awaiting_upload")
      )
        ids.push(row.submission_id);
    }
    const next = body.next_cursor;
    if (typeof next !== "string" || next === cursor) return ids;
    cursor = next;
  }
  return ids;
}

/** Quote each call's plan (no spend) so the owner sees the total first. */
export async function prepareAnalyseAll(
  ids: readonly string[],
  signal: AbortSignal,
  onProgress: (checked: number) => void = () => {},
): Promise<Preparation> {
  const planned: PlannedCall[] = [];
  const skipped: Array<{ id: string; reason: SkipReason }> = [];
  let maxCostPaise = 0;
  for (const [index, id] of ids.entries()) {
    const path = `/submissions/${id}`;
    const progress = await call(path, signal);
    const state = object(progress.body);
    const recordingId = state?.recording_id;
    if (progress.status !== 200 || !state || typeof recordingId !== "string") {
      skipped.push({ id, reason: "attention" });
    } else if (
      state.has_report === true ||
      state.automatic_progression === true
    ) {
      skipped.push({ id, reason: "started" });
    } else if (state.local_state !== "completed") {
      skipped.push({ id, reason: "checks" });
    } else {
      const saved = await call(`${path}/plan`, signal);
      const quoted =
        saved.status === 404
          ? await call(`${path}/plan/quote`, signal, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Idempotency-Key": `analyse-all-plan:${id}`,
              },
              body: JSON.stringify({ report_language: "en" }),
            })
          : saved;
      if (refusedForBudget(quoted)) {
        onProgress(index + 1);
        return { planned, skipped, maxCostPaise, budgetStopped: true };
      }
      let plan: ProcessingPlan | null = null;
      try {
        if (quoted.status === 200 || quoted.status === 201)
          plan = parseProcessingPlan(quoted.body, recordingId);
      } catch {
        plan = null;
      }
      if (plan?.accepted) skipped.push({ id, reason: "started" });
      else if (
        !plan ||
        plan.state !== "quoted" ||
        plan.expires_at_epoch * 1000 <= Date.now()
      )
        skipped.push({ id, reason: "attention" });
      else {
        planned.push({ id, recordingId, plan });
        maxCostPaise += plan.max_cost_paise;
      }
    }
    onProgress(index + 1);
  }
  return { planned, skipped, maxCostPaise, budgetStopped: false };
}

async function freshPlan(
  item: PlannedCall,
  signal: AbortSignal,
): Promise<ProcessingPlan | "budget" | null> {
  if (item.plan.expires_at_epoch * 1000 > Date.now() + 5_000) return item.plan;
  // The quote expired while earlier calls ran: ask for a new one, once.
  const answer = await call(`/submissions/${item.id}/plan/quote`, signal, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": `analyse-all-plan:${item.id}:${item.plan.id}`,
    },
    body: JSON.stringify({ report_language: "en" }),
  });
  if (refusedForBudget(answer)) return "budget";
  try {
    const plan = parseProcessingPlan(answer.body, item.recordingId);
    return plan.state === "quoted" || plan.accepted ? plan : null;
  } catch {
    return null;
  }
}

/** Waits for one call's report, so only one analysis runs at a time. */
async function settle(
  item: PlannedCall,
  signal: AbortSignal,
  pollMs: number,
  maxWaitMs: number,
): Promise<"done" | "failed" | "analysing"> {
  const until = Date.now() + maxWaitMs;
  while (Date.now() < until) {
    await wait(pollMs, signal);
    const answer = await call(`/submissions/${item.id}`, signal).catch(
      () => null,
    );
    const state = object(answer?.body);
    if (!state) continue;
    if (state.has_report === true) return "done";
    if (
      state.local_state === "failed" ||
      state.run_state === "failed" ||
      state.state === "held" ||
      state.state === "cancelled"
    )
      return "failed";
  }
  // Still running on the server; the next call may start.
  return "analysing";
}

export async function runAnalyseAll(
  planned: readonly PlannedCall[],
  signal: AbortSignal,
  onCall: (id: string, run: CallRun) => void,
  pacing: Readonly<{ pollMs: number; maxWaitMs: number }> = {
    pollMs: 10_000,
    maxWaitMs: 15 * 60_000,
  },
): Promise<RunResult> {
  let started = 0;
  let done = 0;
  let failed = 0;
  const stopAll = (from: number, stoppedBy: "budget" | "cancelled") => {
    for (const item of planned.slice(from)) onCall(item.id, "not_started");
    return { started, done, failed, stoppedBy };
  };
  for (const [index, item] of planned.entries()) {
    if (signal.aborted) return stopAll(index, "cancelled");
    onCall(item.id, "starting");
    let outcome: "started" | "failed" | "budget";
    try {
      const plan = await freshPlan(item, signal);
      if (plan === "budget") outcome = "budget";
      else if (!plan) outcome = "failed";
      else if (plan.accepted) outcome = "started";
      else {
        const body = JSON.stringify({
          plan_id: plan.id,
          plan_fingerprint: plan.plan_fingerprint,
          privacy_revision: plan.privacy_revision,
          accepted: true,
        });
        let answer: Answer | null = null;
        try {
          answer = await call(`/submissions/${item.id}/plan`, signal, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Idempotency-Key": `accept-plan:${plan.id}`,
            },
            body,
          });
        } catch (error) {
          if (signal.aborted) throw error;
        }
        if (answer && refusedForBudget(answer)) outcome = "budget";
        else if (answer && answer.status >= 200 && answer.status < 300) {
          const accepted = parseProcessingPlan(answer.body, item.recordingId);
          outcome =
            accepted.accepted &&
            accepted.id === plan.id &&
            accepted.plan_fingerprint === plan.plan_fingerprint
              ? "started"
              : "failed";
        } else if (!answer || answer.status >= 500) {
          // The server may have accepted it: one read, never a second accept.
          const read = await call(`/submissions/${item.id}/plan`, signal);
          const now =
            read.status === 200
              ? parseProcessingPlan(read.body, item.recordingId)
              : null;
          outcome = now?.accepted && now.id === plan.id ? "started" : "failed";
        } else outcome = "failed";
      }
    } catch {
      if (signal.aborted) return stopAll(index, "cancelled");
      outcome = "failed";
    }
    if (outcome === "budget") return stopAll(index, "budget");
    if (outcome === "failed") {
      failed += 1;
      onCall(item.id, "failed");
      continue;
    }
    started += 1;
    onCall(item.id, "analysing");
    try {
      const result = await settle(
        item,
        signal,
        pacing.pollMs,
        pacing.maxWaitMs,
      );
      if (result === "done") done += 1;
      if (result === "failed") failed += 1;
      onCall(item.id, result);
    } catch {
      if (signal.aborted) return stopAll(index + 1, "cancelled");
    }
  }
  return { started, done, failed, stoppedBy: null };
}

/** "₹1,234" from paise, rounded up to the rupee (a maximum, never less). */
export function rupees(paise: number) {
  return `₹${Math.ceil(paise / 100).toLocaleString("en-IN")}`;
}
