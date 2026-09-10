import { z } from "zod";
import { practiceNodeSchema, practiceSetSchema } from "./practice-api";

const counter = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const identifier = z.uuid();
const setId = z.string().regex(/^[a-z0-9-]{1,120}$/);
const itemId = z.string().min(1).max(200);
const instant = z.iso.datetime({ offset: true });
const state = z.enum(["in_progress", "completed"]);
const profileSchema = z
  .strictObject({
    timezone: z.string().min(1).max(128).nullable(),
    revision: counter,
    pending_timezone: z.string().min(1).max(128).nullable(),
    pending_effective_at: instant.nullable(),
  })
  .refine(
    (value) =>
      (value.pending_timezone === null) ===
      (value.pending_effective_at === null),
    { message: "Pending timezone fields must agree" },
  );
const receiptSchema = z.strictObject({
  id: identifier,
  kind: z.enum(["daily_set", "weekly_rhythm"]),
  credits: counter,
  xp: counter,
  local_day: z.iso.date(),
  week_start: z.iso.date(),
  created_at: instant,
});
const receiptsSchema = z
  .array(receiptSchema)
  .refine(
    (items) => new Set(items.map((item) => item.id)).size === items.length,
    { message: "Duplicate reward receipt" },
  );
const feedbackSchema = z.discriminatedUnion("kind", [
  z.strictObject({ kind: z.literal("continue"), node: practiceNodeSchema }),
  z.strictObject({
    kind: z.literal("feedback"),
    reference_match: z.boolean().nullable(),
    explanation: z.string(),
    course_progress_affected: z.literal(false),
    responses_stored: z.literal(true),
  }),
]);
const attemptSchema = z
  .strictObject({
    id: identifier,
    set_id: setId,
    set_version: counter,
    content_digest: z.string().min(1).max(128),
    state,
    revision: counter,
    issued_at: instant,
    completed_at: instant.nullable(),
    set: practiceSetSchema,
    acknowledged_item_ids: z.array(itemId),
    item_states: z.array(
      z.strictObject({
        item_id: itemId,
        response_id: identifier.nullable(),
        selections: z.array(counter).nullable(),
        feedback: feedbackSchema.nullable(),
        acknowledged: z.boolean(),
      }),
    ),
    reward_receipts: receiptsSchema,
    responses_stored: z.literal(true),
    course_progress_affected: z.literal(false),
  })
  .refine(
    (value) =>
      value.set.id === value.set_id && value.set.version === value.set_version,
    { message: "Pinned set identity mismatch" },
  )
  .refine(
    (value) => {
      const items = new Set(value.set.items.map((item) => item.id));
      const acknowledged = new Set(value.acknowledged_item_ids);
      const states = new Set(value.item_states.map((item) => item.item_id));
      const acknowledgedStates = new Set(
        value.item_states
          .filter((item) => item.acknowledged)
          .map((item) => item.item_id),
      );
      if (
        items.size !== value.set.items.length ||
        value.set.item_count !== items.size ||
        acknowledged.size !== value.acknowledged_item_ids.length ||
        states.size !== value.item_states.length ||
        [...acknowledged, ...states].some((id) => !items.has(id)) ||
        acknowledged.size !== acknowledgedStates.size ||
        [...acknowledged].some((id) => !acknowledgedStates.has(id))
      )
        return false;
      const complete = acknowledged.size === items.size;
      return value.state === "completed"
        ? complete && value.completed_at !== null
        : !complete && value.completed_at === null;
    },
    { message: "Attempt progress does not match pinned items" },
  );
const progressSchema = z.strictObject({
  profile: profileSchema,
  credits_balance: counter,
  xp_total: counter,
  actual_practice_days_this_week: counter.max(7),
  policy_version: z.string().min(1),
  recent_attempts: z.array(
    z
      .strictObject({
        id: identifier,
        set_id: setId,
        set_version: counter,
        title: z.string(),
        state,
        revision: counter,
        acknowledged_count: counter,
        item_count: counter,
        issued_at: instant,
        completed_at: instant.nullable(),
      })
      .refine((value) => value.acknowledged_count <= value.item_count, {
        message: "Acknowledged count exceeds items",
      }),
  ),
  recent_awards: receiptsSchema,
  purchases_enabled: z.literal(false),
  course_progress_affected: z.literal(false),
});
const profileInput = z.strictObject({
  timezone: z.string().min(1).max(128),
  expected_revision: counter,
});
const responseInput = z.strictObject({
  item_id: itemId,
  selections: z.array(counter),
  expected_revision: counter,
});
const acknowledgementInput = z.strictObject({ expected_revision: counter });
const commandKey = z.string().regex(/^[\x21-\x7e]{1,200}$/);
export type PracticeProfile = z.infer<typeof profileSchema>;
export type PracticeAttempt = z.infer<typeof attemptSchema>;
export type PracticeProgress = z.infer<typeof progressSchema>;
export type PracticeRewardReceipt = z.infer<typeof receiptSchema>;
export type PracticeEngineFeedback = z.infer<typeof feedbackSchema>;

export class PracticeEngineRequestError extends Error {
  constructor(
    public readonly status: number,
    public readonly reason:
      | "http"
      | "network"
      | "timeout"
      | "invalid_response"
      | "invalid_request" = "http",
  ) {
    super(
      reason === "invalid_response"
        ? "Practice returned an unexpected response. Refresh before continuing."
        : reason === "invalid_request"
          ? "Check the practice request before trying again."
          : status === 401
            ? "Sign in to continue practice."
            : status === 403
              ? "This academy cannot open that practice."
              : status === 409
                ? "This practice changed. Refresh it before continuing."
                : "Practice couldn’t connect. Try again.",
    );
    this.name = "PracticeEngineRequestError";
  }
}

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_REQUEST_BYTES = 64 * 1024;
const TIMEOUT_MS = 12_000;
type EngineFetch = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

/** Caller owns logical-command keys; no automatic retries, rewards or local attempt state. */
export function createPracticeEngineApi(
  fetcher: EngineFetch = (input, init) => globalThis.fetch(input, init),
) {
  async function request<T>(
    path: string,
    schema: z.ZodType<T>,
    signal: AbortSignal,
    mutation?: { method: "PUT" | "POST"; key: string; body: unknown },
  ): Promise<T> {
    let body: string | undefined;
    try {
      if (mutation) {
        commandKey.parse(mutation.key);
        // Serialize synchronously: later caller mutation cannot change an in-flight command.
        body = JSON.stringify(mutation.body);
        if (new TextEncoder().encode(body).byteLength > MAX_REQUEST_BYTES)
          throw new Error();
      }
    } catch {
      throw new PracticeEngineRequestError(0, "invalid_request");
    }
    const controller = new AbortController();
    let timedOut = false;
    let cancel: (() => void) | undefined;
    const cancellation = new Promise<never>((_resolve, reject) => {
      cancel = () =>
        reject(
          timedOut
            ? new PracticeEngineRequestError(0, "timeout")
            : new DOMException("Practice request cancelled.", "AbortError"),
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
    const execution = async () => {
      if (controller.signal.aborted)
        throw new DOMException("Practice request cancelled.", "AbortError");
      const response = await fetcher(`/v1/practice/${path}`, {
        method: mutation?.method ?? "GET",
        credentials: "same-origin",
        mode: "same-origin",
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
      const discard = () => {
        void response.body?.cancel().catch(() => undefined);
      };
      if (controller.signal.aborted) {
        discard();
        throw new DOMException("Practice request cancelled.", "AbortError");
      }
      if (!response.ok) {
        discard();
        throw new PracticeEngineRequestError(response.status);
      }
      if (
        !/^application\/json(?:\s*;|$)/i.test(
          response.headers.get("content-type") ?? "",
        )
      ) {
        discard();
        throw new PracticeEngineRequestError(0, "invalid_response");
      }
      const reader = response.body?.getReader();
      if (!reader) throw new PracticeEngineRequestError(0, "invalid_response");
      const stop = () => {
        void reader.cancel().catch(() => undefined);
      };
      controller.signal.addEventListener("abort", stop, { once: true });
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        while (!controller.signal.aborted) {
          const item = await reader.read();
          if (item.done) break;
          size += item.value.byteLength;
          if (size > MAX_RESPONSE_BYTES) {
            stop();
            throw new PracticeEngineRequestError(0, "invalid_response");
          }
          chunks.push(item.value);
        }
        if (controller.signal.aborted)
          throw new DOMException("Practice request cancelled.", "AbortError");
      } finally {
        controller.signal.removeEventListener("abort", stop);
        reader.releaseLock();
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.length;
      }
      try {
        return schema.parse(
          JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)),
        );
      } catch {
        throw new PracticeEngineRequestError(0, "invalid_response");
      }
    };
    try {
      return await Promise.race([execution(), cancellation]);
    } catch (error) {
      if (
        error instanceof PracticeEngineRequestError ||
        (error instanceof DOMException && error.name === "AbortError")
      )
        throw error;
      throw new PracticeEngineRequestError(0, "network");
    } finally {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
    }
  }
  const parse = <T>(schema: z.ZodType<T>, value: unknown) => {
    const parsed = schema.safeParse(value);
    if (!parsed.success)
      throw new PracticeEngineRequestError(0, "invalid_request");
    return parsed.data;
  };
  return {
    progress: (signal: AbortSignal) =>
      request("progress", progressSchema, signal),
    profile: (signal: AbortSignal) => request("profile", profileSchema, signal),
    updateProfile: (
      input: z.infer<typeof profileInput>,
      key: string,
      signal: AbortSignal,
    ) =>
      request("profile", profileSchema, signal, {
        method: "PUT",
        key,
        body: parse(profileInput, input),
      }),
    issue: (id: string, key: string, signal: AbortSignal) =>
      request(`sets/${parse(setId, id)}/attempts`, attemptSchema, signal, {
        method: "POST",
        key,
        body: {},
      }),
    attempt: (id: string, signal: AbortSignal) =>
      request(`attempts/${parse(identifier, id)}`, attemptSchema, signal),
    respond: (
      id: string,
      input: z.infer<typeof responseInput>,
      key: string,
      signal: AbortSignal,
    ) =>
      request(
        `attempts/${parse(identifier, id)}/responses`,
        attemptSchema,
        signal,
        { method: "POST", key, body: parse(responseInput, input) },
      ),
    acknowledge: (
      id: string,
      responseId: string,
      input: z.infer<typeof acknowledgementInput>,
      key: string,
      signal: AbortSignal,
    ) =>
      request(
        `attempts/${parse(identifier, id)}/feedback/${parse(identifier, responseId)}/acknowledge`,
        attemptSchema,
        signal,
        { method: "POST", key, body: parse(acknowledgementInput, input) },
      ),
  };
}
export const practiceEngineApi = createPracticeEngineApi();
export type PracticeEngineApi = typeof practiceEngineApi;
