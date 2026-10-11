import {
  parseHumanCallOutcome,
  type HumanCallOutcome,
} from "./report-call-outcome-contract";
import { UUID_RE } from "./prospects-client";

export const CALL_OUTCOME_SCHEMA = "ac.sales-xray.call-outcome/1";
export type CallOutcomeBinding = {
  callId: string;
  personId: string;
  tenantId: string;
  sessionId: string;
};
export type CallOutcomeRecord = {
  schema: typeof CALL_OUTCOME_SCHEMA;
  submission_id: string;
  person_id: string;
  tenant_id: string;
  session_id: string;
  revision: number;
  value: HumanCallOutcome | null;
  basis: "person" | null;
  locked: boolean;
  set_by_person_id: string | null;
  set_at: string | null;
  prospect_binding: {
    prospect_id: string;
    membership_id: string;
    stage_revision: number;
  } | null;
  can_edit: boolean;
};
export type CallOutcomeRead =
  | { status: "ready"; binding: CallOutcomeBinding; data: CallOutcomeRecord }
  /** Not this person's call to record (403 not_call_owner): nothing to show. */
  | { status: "not_owner" }
  | { status: "unavailable"; message: string };
export type CallOutcomeSave =
  | { status: "saved"; binding: CallOutcomeBinding; data: CallOutcomeRecord }
  | {
      status: "invalid" | "forbidden" | "conflict" | "unconfirmed";
      message: string;
    };
type Options = { signal?: AbortSignal; deadlineMs?: number };
const MAX_BODY_BYTES = 16384;

function invalid(): never {
  throw new Error("call_outcome_unavailable");
}
function record(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) invalid();
  return raw as Record<string, unknown>;
}
function uuid(raw: unknown): string {
  if (typeof raw !== "string" || !UUID_RE.test(raw)) invalid();
  return raw;
}
function revision(raw: unknown): number {
  if (!Number.isSafeInteger(raw) || (raw as number) < 0) invalid();
  return raw as number;
}
function checkBinding(binding: CallOutcomeBinding) {
  for (const id of [
    binding.callId,
    binding.personId,
    binding.tenantId,
    binding.sessionId,
  ])
    uuid(id);
}
function auditTime(raw: unknown): string {
  if (
    typeof raw !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(
      raw,
    ) ||
    !Number.isFinite(Date.parse(raw))
  )
    invalid();
  // Date.parse normalizes impossible calendar dates; the human date codec does not.
  parseHumanCallOutcome({
    outcome: "follow_up",
    follow_up_on: raw.slice(0, 10),
  });
  return raw;
}

/** Prepared human-fact read contract. AI labels, roles and browser scope grant nothing. */
export function parseCallOutcomeRecord(
  raw: unknown,
  binding: CallOutcomeBinding,
): CallOutcomeRecord {
  checkBinding(binding);
  const row = record(raw);
  if (
    row.schema !== CALL_OUTCOME_SCHEMA ||
    row.submission_id !== binding.callId ||
    row.person_id !== binding.personId ||
    row.tenant_id !== binding.tenantId ||
    row.session_id !== binding.sessionId ||
    (row.can_edit !== undefined && typeof row.can_edit !== "boolean")
  )
    invalid();
  const currentRevision = revision(row.revision);
  const value = row.value === null ? null : parseHumanCallOutcome(row.value);
  let setBy: string | null = null,
    setAt: string | null = null;
  if (value === null) {
    if (
      currentRevision !== 0 ||
      row.basis !== null ||
      row.locked !== false ||
      row.set_by_person_id !== null ||
      row.set_at !== null
    )
      invalid();
  } else {
    if (currentRevision < 1 || row.basis !== "person" || row.locked !== true)
      invalid();
    setBy = uuid(row.set_by_person_id);
    setAt = auditTime(row.set_at);
  }
  let prospect: CallOutcomeRecord["prospect_binding"] = null;
  if (row.prospect_binding !== null) {
    const link = record(row.prospect_binding);
    prospect = {
      prospect_id: uuid(link.prospect_id),
      membership_id: uuid(link.membership_id),
      stage_revision: revision(link.stage_revision),
    };
  }
  return {
    schema: CALL_OUTCOME_SCHEMA,
    submission_id: binding.callId,
    person_id: binding.personId,
    tenant_id: binding.tenantId,
    session_id: binding.sessionId,
    revision: currentRevision,
    value,
    basis: value === null ? null : "person",
    locked: value !== null,
    set_by_person_id: setBy,
    set_at: setAt,
    prospect_binding: prospect,
    can_edit: row.can_edit === true,
  };
}

async function responseBody(
  response: Response,
  signal: AbortSignal,
): Promise<unknown> {
  if (
    signal.aborted ||
    response.redirected ||
    response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !==
      "application/json" ||
    Number(response.headers.get("content-length")) > MAX_BODY_BYTES ||
    !response.body
  )
    invalid();
  const stream = response.body.getReader();
  const cancel = () => {
    void stream.cancel().catch(() => {});
  };
  signal.addEventListener("abort", cancel, { once: true });
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const part = await stream.read();
      if (signal.aborted) invalid();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > MAX_BODY_BYTES) invalid();
      chunks.push(part.value);
    }
  } finally {
    signal.removeEventListener("abort", cancel);
    await stream.cancel();
    stream.releaseLock();
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
}

/** The deadline includes response-body reading; an ignored abort still cannot hold the page. */
async function bounded<T>(
  options: Options,
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const signal = options.signal;
  const deadline = options.deadlineMs ?? 2500;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    if (
      !Number.isFinite(deadline) ||
      deadline < 1 ||
      deadline > 15000 ||
      signal?.aborted
    )
      invalid();
    signal?.addEventListener("abort", abort, { once: true });
    const cancelled = new Promise<never>((_, reject) => {
      controller.signal.addEventListener(
        "abort",
        () => reject(invalidError()),
        {
          once: true,
        },
      );
      timer = setTimeout(abort, deadline);
    });
    const result = await Promise.race([
      Promise.resolve().then(() => {
        if (controller.signal.aborted) invalid();
        return operation(controller.signal);
      }),
      cancelled,
    ]);
    if (controller.signal.aborted) invalid();
    return result;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
    controller.abort();
  }
}
function invalidError() {
  return new Error("call_outcome_unavailable");
}
function path(binding: CallOutcomeBinding) {
  return `/v1/conversation/prospects/calls/${binding.callId}/outcome`;
}
const requestOptions = {
  credentials: "same-origin",
  redirect: "error",
  cache: "no-store",
} as const;

/** Explicit read/preload only. A missing API is unavailable, never an unrecorded fact. */
export async function readCallOutcome(
  binding: CallOutcomeBinding,
  options: Options = {},
): Promise<CallOutcomeRead> {
  const scope = { ...binding };
  let notOwner = false;
  try {
    checkBinding(scope);
    const data = await bounded(options, async (signal) => {
      const response = await fetch(path(scope), {
        ...requestOptions,
        method: "GET",
        signal,
        headers: { accept: "application/json" },
      });
      if (response.status === 403) {
        // Only the call's owner records it; the server says so with a stable code.
        const detail = await response
          .json()
          .then((data: unknown) =>
            data && typeof data === "object" && "detail" in data
              ? (data as { detail: unknown }).detail
              : null,
          )
          .catch(() => null);
        notOwner = detail === "not_call_owner";
      }
      if (response.status !== 200) invalid();
      return parseCallOutcomeRecord(
        await responseBody(response, signal),
        scope,
      );
    });
    return { status: "ready", binding: scope, data };
  } catch {
    if (notOwner) return { status: "not_owner" };
    return {
      status: "unavailable",
      message: "Call outcome is unavailable. Try again.",
    };
  }
}

/** Prepared command only; no mount, stage inference, optimistic success or automatic retry. */
export async function saveCallOutcome(
  binding: CallOutcomeBinding,
  previous: CallOutcomeRecord,
  requested: unknown,
  options: Options = {},
): Promise<CallOutcomeSave> {
  const scope = { ...binding };
  let before: CallOutcomeRecord, value: HumanCallOutcome, body: string;
  try {
    before = parseCallOutcomeRecord(previous, scope);
    value = parseHumanCallOutcome(requested);
    if (before.revision === Number.MAX_SAFE_INTEGER) invalid();
    body = JSON.stringify({
      value,
      expected_revision: before.revision,
      expected_membership_id: before.prospect_binding?.membership_id ?? null,
      expected_prospect_stage_revision:
        before.prospect_binding?.stage_revision ?? null,
    });
  } catch {
    return {
      status: "invalid",
      message: "Reload the call and check the outcome values.",
    };
  }
  if (!before.can_edit)
    return { status: "forbidden", message: "This call outcome is read-only." };
  let conflict = false;
  try {
    const data = await bounded(options, async (signal) => {
      const response = await fetch(path(scope), {
        ...requestOptions,
        method: "PUT",
        signal,
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body,
      });
      if (response.status === 409) conflict = true;
      if (response.status !== 200) invalid();
      return parseCallOutcomeRecord(
        await responseBody(response, signal),
        scope,
      );
    });
    const oldLink = before.prospect_binding,
      newLink = data.prospect_binding;
    if (
      JSON.stringify(data.value) !== JSON.stringify(value) ||
      (oldLink === null
        ? newLink !== null
        : newLink === null ||
          oldLink.prospect_id !== newLink.prospect_id ||
          oldLink.membership_id !== newLink.membership_id ||
          newLink.stage_revision < oldLink.stage_revision ||
          newLink.stage_revision > oldLink.stage_revision + 1)
    )
      invalid();
    if (data.revision === before.revision) {
      // An unchanged fact retains its original actor/time and stage provenance.
      if (
        JSON.stringify(before.value) !== JSON.stringify(value) ||
        before.set_by_person_id !== data.set_by_person_id ||
        before.set_at !== data.set_at ||
        oldLink?.stage_revision !== newLink?.stage_revision
      )
        invalid();
    } else if (
      data.revision !== before.revision + 1 ||
      data.set_by_person_id !== scope.personId ||
      JSON.stringify(before.value) === JSON.stringify(value) ||
      (before.set_at !== null &&
        Date.parse(data.set_at!) < Date.parse(before.set_at))
    )
      invalid();
    return { status: "saved", binding: scope, data };
  } catch {
    return conflict
      ? {
          status: "conflict",
          message:
            "Call or prospect information changed. Reload before saving again.",
        }
      : {
          status: "unconfirmed",
          message:
            "This save could not be confirmed. Reload before saving again.",
        };
  }
}
