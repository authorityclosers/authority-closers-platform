import { z } from "zod";

const counter = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const identifier = z.uuid();
const instant = z.iso.datetime({ offset: true });
const chargeChange = z.union([z.literal(0), z.literal(1)]);
const runSchema = z
  .strictObject({
    id: identifier,
    attempt_id: identifier,
    set_id: z.string().regex(/^[a-z0-9-]{1,120}$/),
    state: z.enum(["active", "ended", "completed"]),
    started_at: instant,
    finished_at: instant.nullable(),
    exit_cost: chargeChange,
    completion_restore: chargeChange,
  })
  .refine(
    (run) =>
      run.state === "active"
        ? run.finished_at === null &&
          run.exit_cost === 0 &&
          run.completion_restore === 0
        : run.finished_at !== null &&
          (run.state === "ended"
            ? run.completion_restore === 0
            : run.exit_cost === 0),
    { message: "Focus run lifecycle fields disagree" },
  );
const summarySchema = z
  .strictObject({
    policy_version: z.string().min(1).max(200),
    charges: counter.max(3),
    capacity: z.literal(3),
    revision: counter,
    local_day: z.iso.date().nullable(),
    timezone: z.string().min(1).max(64).nullable(),
    active_run: runSchema.nullable(),
  })
  .refine(
    (summary) =>
      (summary.local_day === null) === (summary.timezone === null) &&
      (summary.active_run === null ||
        (summary.active_run.state === "active" && summary.timezone !== null)),
    { message: "Focus summary context is inconsistent" },
  );
const resultSchema = z
  .strictObject({ summary: summarySchema, run: runSchema })
  .refine(
    ({ summary, run }) =>
      run.state === "active"
        ? JSON.stringify(summary.active_run) === JSON.stringify(run)
        : summary.active_run?.id !== run.id,
    { message: "Focus result and current active run disagree" },
  );
const revisionInput = z.strictObject({
  expected_revision: counter,
  expected_attempt_revision: counter,
});
const commandKey = z.string().regex(/^[\x21-\x7e]{1,128}$/);
const conflictReason = z.enum([
  "attempt_started",
  "not_eligible",
  "active_run_conflict",
  "focus_empty",
  "revision_conflict",
]);
const conflictBody = z.strictObject({
  detail: z.strictObject({ reason: conflictReason, message: z.string() }),
});
export type FocusRun = z.infer<typeof runSchema>;
export type FocusSummary = z.infer<typeof summarySchema>;
export type FocusResult = z.infer<typeof resultSchema>;
export type FocusRevision = z.infer<typeof revisionInput>;
export type FocusConflictReason = z.infer<typeof conflictReason>;
type FailureReason =
  | FocusConflictReason
  | "http"
  | "network"
  | "timeout"
  | "invalid_response"
  | "invalid_request";

export class PracticeFocusRequestError extends Error {
  constructor(
    public readonly status: number,
    public readonly reason: FailureReason = "http",
  ) {
    super(
      reason === "invalid_response"
        ? "Focus returned an unexpected response. Refresh before continuing."
        : reason === "invalid_request"
          ? "Check the Focus request before trying again."
          : status === 401
            ? "Sign in to continue Focus."
            : status === 403
              ? "This academy cannot open that Focus run."
              : status === 409
                ? "Focus changed or is unavailable. Refresh before continuing."
                : "Focus couldn’t connect. Try again.",
    );
    this.name = "PracticeFocusRequestError";
  }
}

type FocusFetch = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;
const TIMEOUT_MS = 12_000;
const RESPONSE_LIMIT = 64 * 1024;
const CONFLICT_LIMIT = 8 * 1024;
const isJson = (response: Response) =>
  /^application\/json(?:\s*;|$)/i.test(
    response.headers.get("content-type") ?? "",
  );
const discard = (response: Response) => {
  void response.body?.cancel().catch(() => undefined);
};

async function boundedJson(
  response: Response,
  limit: number,
  signal: AbortSignal,
): Promise<unknown> {
  if (!isJson(response)) {
    discard(response);
    throw new PracticeFocusRequestError(0, "invalid_response");
  }
  const declared = response.headers.get("content-length");
  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > limit) {
    discard(response);
    throw new PracticeFocusRequestError(0, "invalid_response");
  }
  const reader = response.body?.getReader();
  if (!reader) throw new PracticeFocusRequestError(0, "invalid_response");
  const stop = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal.addEventListener("abort", stop, { once: true });
  if (signal.aborted) stop();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (!signal.aborted) {
      const part = await reader.read();
      if (part.done) break;
      length += part.value.byteLength;
      if (length > limit) {
        stop();
        throw new PracticeFocusRequestError(0, "invalid_response");
      }
      chunks.push(part.value);
    }
    if (signal.aborted)
      throw new DOMException("Focus request cancelled.", "AbortError");
  } finally {
    signal.removeEventListener("abort", stop);
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new PracticeFocusRequestError(0, "invalid_response");
  }
}

/** Focus is independent of earned balances. The caller supplies stable logical
 * command keys; this client never retries, awards, spends or infers a timezone. */
export function createPracticeFocusApi(
  fetcher: FocusFetch = (input, init) => globalThis.fetch(input, init),
) {
  const parse = <T>(schema: z.ZodType<T>, value: unknown) => {
    const result = schema.safeParse(value);
    if (!result.success)
      throw new PracticeFocusRequestError(0, "invalid_request");
    return result.data;
  };
  async function request<T>(
    path: string,
    schema: z.ZodType<T>,
    signal: AbortSignal,
    mutation?: { key: string; body: FocusRevision },
  ): Promise<T> {
    // Snapshot before awaiting so a caller cannot alter this in-flight payload.
    const body = mutation
      ? JSON.stringify(parse(revisionInput, mutation.body))
      : undefined;
    if (mutation) parse(commandKey, mutation.key);
    const controller = new AbortController();
    let timedOut = false;
    let cancel: (() => void) | undefined;
    const cancellation = new Promise<never>((_resolve, reject) => {
      cancel = () =>
        reject(
          timedOut
            ? new PracticeFocusRequestError(0, "timeout")
            : new DOMException("Focus request cancelled.", "AbortError"),
        );
    });
    const abort = () => {
      controller.abort();
      cancel?.();
    };
    const timer = setTimeout(() => {
      timedOut = true;
      abort();
    }, TIMEOUT_MS);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
    const execute = async () => {
      if (controller.signal.aborted)
        throw new DOMException("Focus request cancelled.", "AbortError");
      const response = await fetcher(`/v1/practice/${path}`, {
        method: mutation ? "POST" : "GET",
        mode: "same-origin",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal: controller.signal,
        headers: {
          accept: "application/json",
          ...(mutation
            ? {
                "content-type": "application/json",
                "Idempotency-Key": mutation.key,
              }
            : {}),
        },
        body,
      });
      if (controller.signal.aborted) {
        discard(response);
        throw new DOMException("Focus request cancelled.", "AbortError");
      }
      if (!response.ok) {
        let reason: FocusConflictReason | undefined;
        if (response.status === 409) {
          try {
            const problem = conflictBody.safeParse(
              await boundedJson(response, CONFLICT_LIMIT, controller.signal),
            );
            if (problem.success) reason = problem.data.detail.reason;
          } catch (error) {
            if (controller.signal.aborted) throw error;
            // Preserve HTTP status while refusing unrecognized or oversized diagnostics.
          }
        } else discard(response);
        throw new PracticeFocusRequestError(response.status, reason);
      }
      const result = schema.safeParse(
        await boundedJson(response, RESPONSE_LIMIT, controller.signal),
      );
      if (!result.success)
        throw new PracticeFocusRequestError(0, "invalid_response");
      return result.data;
    };
    try {
      return await Promise.race([execute(), cancellation]);
    } catch (error) {
      if (
        error instanceof PracticeFocusRequestError ||
        (error instanceof DOMException && error.name === "AbortError")
      )
        throw error;
      throw new PracticeFocusRequestError(0, "network");
    } finally {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
    }
  }
  return {
    summary: (signal: AbortSignal) => request("focus", summarySchema, signal),
    start: (
      attemptId: string,
      body: FocusRevision,
      key: string,
      signal: AbortSignal,
    ) => {
      const id = parse(identifier, attemptId);
      return request(
        `attempts/${id}/focus`,
        resultSchema.refine((value) => value.run.attempt_id === id),
        signal,
        { key, body },
      );
    },
    end: (
      runId: string,
      body: FocusRevision,
      key: string,
      signal: AbortSignal,
    ) => {
      const id = parse(identifier, runId);
      return request(
        `focus/runs/${id}/end`,
        resultSchema.refine(
          (value) => value.run.id === id && value.run.state !== "active",
        ),
        signal,
        { key, body },
      );
    },
  };
}
export const practiceFocusApi = createPracticeFocusApi();
export type PracticeFocusApi = typeof practiceFocusApi;
