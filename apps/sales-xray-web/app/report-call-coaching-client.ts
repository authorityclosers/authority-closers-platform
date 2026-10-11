import {
  parseEvidence,
  type Evidence,
  type Mission,
  type TextLesson,
} from "./coaching/coaching-client";
import type { Transcript } from "./report-contract";
import { REPORT_SKILLS } from "./report-pillars";
import { parseClips, type CoachingClip } from "./coaching/media-contract";

export type CallCoachingBinding = {
  callId: string;
  personId: string;
  tenantId: string;
  sessionId?: string;
  sourceSha256: string;
  transcriptRevision: string;
  recordingId?: string;
  reportRevision?: string;
  transcript?: Transcript;
};
export type CallCoaching = {
  schema: "ac.sales-xray.call-coaching/1";
  person_id: string;
  tenant_id: string;
  session_id?: string | null;
  submission_id: string;
  recording_id: string;
  source_sha256: string;
  transcript_revision: string;
  report_revision: string;
  state: "ready" | "unavailable";
  basis:
    | "skill_evidence"
    | "report_suggestion"
    | "general_practice"
    | "unavailable";
  focus: null | {
    skill_id: string;
    label: string;
    explanation: string;
    why_it_matters: string;
    selected_reason: string;
    selected_at: string;
    status: "active" | "provisional";
    verdict: string;
  };
  evidence: Evidence[];
  lesson: (Omit<TextLesson, "own_call"> & { own_call: Evidence | null }) | null;
  practice: { exercise: string; success_condition: string } | null;
  mission: Mission | null;
  media_clips?: CoachingClip[];
  limitations: string[];
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SHA = /^[0-9a-f]{64}$/;
const MAX_BODY_BYTES = 128_000;
export class CallCoachingReadError extends Error {
  constructor(readonly status?: number) {
    super("This call’s coaching is unavailable. Try again.");
  }
}
function invalid(): never {
  throw new CallCoachingReadError();
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return invalid();
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value.trim() || value.length > 10000)
    return invalid();
  return value;
}
function texts(value: unknown): string[] {
  if (!Array.isArray(value) || value.length > 24) return invalid();
  return value.map(text);
}
function fields(value: unknown, keys: string[]) {
  const row = object(value);
  keys.forEach((key) => text(row[key]));
  return row;
}
function date(value: unknown) {
  if (!Number.isFinite(Date.parse(text(value)))) invalid();
}
function skill(value: unknown) {
  if (
    value !== "report_next_step" &&
    !REPORT_SKILLS.some(([id]) => id === value)
  )
    invalid();
}
export function parseCallCoaching(
  value: unknown,
  binding: CallCoachingBinding,
): CallCoaching {
  const row = object(value);
  if (
    row.schema !== "ac.sales-xray.call-coaching/1" ||
    row.authority !== "provisional" ||
    row.entitlement !== "coaching" ||
    row.entitlement_policy !== "AUT-1678-open-access" ||
    row.person_id !== binding.personId ||
    row.tenant_id !== binding.tenantId ||
    (binding.sessionId !== undefined && row.session_id !== binding.sessionId) ||
    row.submission_id !== binding.callId ||
    row.source_sha256 !== binding.sourceSha256 ||
    row.transcript_revision !== binding.transcriptRevision ||
    !UUID.test(text(row.recording_id)) ||
    !SHA.test(text(row.source_sha256)) ||
    !SHA.test(text(row.report_revision)) ||
    (binding.recordingId !== undefined &&
      row.recording_id !== binding.recordingId) ||
    (binding.reportRevision !== undefined &&
      row.report_revision !== binding.reportRevision) ||
    ![binding.callId, binding.personId, binding.tenantId].every((id) =>
      UUID.test(id),
    ) ||
    (binding.sessionId !== undefined && !UUID.test(binding.sessionId)) ||
    row.recommended_media !== null ||
    !["ready", "unavailable"].includes(text(row.state)) ||
    ![
      "skill_evidence",
      "report_suggestion",
      "general_practice",
      "unavailable",
    ].includes(text(row.basis))
  )
    invalid();
  const evidence = (value: unknown) => {
    const source = parseEvidence(value);
    if (
      source.submission_id !== binding.callId ||
      source.recording_id !== row.recording_id ||
      source.source_sha256 !== binding.sourceSha256 ||
      source.transcript_revision !== binding.transcriptRevision
    )
      invalid();
    const transcript = binding.transcript;
    if (transcript) {
      const segment = transcript.segments.find(
        (item) => item.id === source.segment_id,
      );
      if (
        transcript.source_sha256 !== binding.sourceSha256 ||
        transcript.revision !== binding.transcriptRevision ||
        !segment ||
        !segment.text.includes(source.quote) ||
        source.start_ms < segment.start_ms ||
        source.end_ms > segment.end_ms
      )
        invalid();
    }
    return source;
  };
  if (!Array.isArray(row.evidence) || row.evidence.length > 4) invalid();
  row.evidence.forEach(evidence);
  texts(row.limitations);
  if (row.state === "unavailable") {
    if (
      row.basis !== "unavailable" ||
      row.evidence.length ||
      row.focus !== null ||
      row.lesson !== null ||
      row.practice !== null ||
      row.mission !== null
    )
      invalid();
  } else {
    if (row.basis === "unavailable") invalid();
    const focus = fields(row.focus, [
      "skill_id",
      "label",
      "explanation",
      "why_it_matters",
      "selected_reason",
      "verdict",
    ]);
    skill(focus.skill_id);
    date(focus.selected_at);
    if (!["active", "provisional"].includes(text(focus.status))) invalid();
    const mission = fields(row.mission, [
      "skill_id",
      "behavior",
      "context",
      "done_when",
      "cue",
    ]);
    date(mission.active_since);
    if (
      mission.origin_submission_id !== binding.callId ||
      mission.skill_id !== focus.skill_id ||
      mission.status !== "active"
    )
      invalid();
    fields(row.practice, ["exercise", "success_condition"]);
    const lesson = fields(row.lesson, [
      "title",
      "quick_idea",
      "why_it_matters",
      "good_looks_like",
      "better_direction",
      "when_to_use",
      "when_not",
      "source",
      "next_call_connection",
    ]);
    for (const key of ["framework", "example_wording", "checklist"])
      texts(lesson[key]);
    if (lesson.own_call !== null) evidence(lesson.own_call);
    if (lesson.next_call_connection !== mission.behavior) invalid();
    if (row.basis === "skill_evidence" && !row.evidence.length) invalid();
  }
  return {
    ...row,
    media_clips: row.state === "ready" ? parseClips(row.media_clips) : [],
  } as CallCoaching;
}

/** Bound the body before decoding; scope loss also closes a stalled stream. */
async function readBody(response: Response, signal: AbortSignal) {
  if (
    signal.aborted ||
    Number(response.headers.get("content-length")) > MAX_BODY_BYTES ||
    !response.body
  ) {
    void response.body?.cancel().catch(() => {});
    return invalid();
  }
  const reader = response.body.getReader();
  let cancelled = false;
  const cancel = () => {
    if (cancelled) return;
    cancelled = true;
    // A defective stream's cancellation promise must not delay recovery.
    void reader.cancel().catch(() => {});
  };
  signal.addEventListener("abort", cancel, { once: true });
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (signal.aborted) return invalid();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > MAX_BODY_BYTES) return invalid();
      chunks.push(part.value);
    }
    const body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      body.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
  } finally {
    signal.removeEventListener("abort", cancel);
    cancel();
    reader.releaseLock();
  }
}

/** One own-call GET. It cannot load another person's coaching or start a job. */
export async function readCallCoaching(
  binding: CallCoachingBinding,
  signal: AbortSignal,
) {
  if (!UUID.test(binding.callId)) return invalid();
  if (signal.aborted) return invalid();
  let cancel: () => void = () => {};
  const aborted = new Promise<never>((_, reject) => {
    cancel = () =>
      reject(new Error("This call’s coaching is unavailable. Try again."));
    signal.addEventListener("abort", cancel, { once: true });
  });
  const operation = async () => {
    const response = await fetch(`/v1/me/coaching/calls/${binding.callId}`, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal,
    });
    if (!response.ok) throw new CallCoachingReadError(response.status);
    if (response.redirected) return invalid();
    try {
      return parseCallCoaching(await readBody(response, signal), binding);
    } catch {
      return invalid();
    }
  };
  try {
    return await Promise.race([operation(), aborted]);
  } finally {
    signal.removeEventListener("abort", cancel);
  }
}
