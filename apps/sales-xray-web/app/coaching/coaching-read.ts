import { parseClips, type CoachingClip } from "./media-contract";
import {
  parseCoaching,
  parseEvidence,
  type Coaching,
  type Evidence,
  type TextLesson,
} from "./coaching-client";
import { parseTeamCoaching, type TeamCoaching } from "./team-contract";
import { requestedCall } from "./call-request";
export { requestedCall } from "./call-request";

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
  call_label: string;
  state: "ready" | "unavailable";
  basis:
    | "skill_evidence"
    | "report_suggestion"
    | "general_practice"
    | "unavailable";
  focus: Coaching["focus"];
  evidence: Evidence[];
  root_cause: Coaching["root_cause"];
  lesson: (Omit<TextLesson, "own_call"> & { own_call: Evidence | null }) | null;
  practice: Coaching["practice"];
  mission: Coaching["mission"];
  media_clips?: CoachingClip[];
  /** A quoted "What worked" finding from this call's report (spec 3.6). */
  strength?: CallStrength | null;
  limitations: string[];
};
export type CallStrength = {
  title: string;
  explanation: string;
  evidence: Evidence[];
};
export type CoachingResult =
  | { data: Coaching | CallCoaching | TeamCoaching; error: null }
  | { data: null; error: string };

export function coachingPath(callId: string | null): string {
  if (callId === "team") return "/v1/me/coaching/team";
  return callId ? `/v1/me/coaching/calls/${callId}` : "/v1/me/coaching";
}
export function isCallCoaching(
  data: Coaching | CallCoaching | TeamCoaching,
): data is CallCoaching {
  return data.schema === "ac.sales-xray.call-coaching/1";
}
export function isTeamCoaching(
  data: Coaching | CallCoaching | TeamCoaching,
): data is TeamCoaching {
  return data.schema === "ac.sales-xray.team-coaching/1";
}
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const text = (value: unknown, fallback = "") =>
  typeof value === "string" && value.trim() ? value : fallback;
const texts = (value: unknown) =>
  Array.isArray(value)
    ? value.filter((s): s is string => typeof s === "string" && !!s.trim())
    : [];

/** Identity/source boundaries are strict. Missing optional display fields default. */
export function parseCallCoaching(
  value: unknown,
  callId: string,
): CallCoaching | null {
  const item = object(value);
  if (
    item.schema !== "ac.sales-xray.call-coaching/1" ||
    item.authority !== "provisional" ||
    item.entitlement !== "coaching" ||
    item.entitlement_policy !== "AUT-1678-open-access" ||
    requestedCall(item.submission_id) !== callId ||
    !requestedCall(item.person_id) ||
    !requestedCall(item.tenant_id) ||
    (item.session_id != null && !requestedCall(item.session_id)) ||
    !requestedCall(item.recording_id) ||
    !/^[0-9a-f]{64}$/.test(text(item.source_sha256)) ||
    !/^[0-9a-f]{64}$/.test(text(item.report_revision)) ||
    !text(item.transcript_revision) ||
    !["ready", "unavailable"].includes(text(item.state)) ||
    ![
      "skill_evidence",
      "report_suggestion",
      "general_practice",
      "unavailable",
    ].includes(text(item.basis)) ||
    item.recommended_media != null
  )
    return null;
  const ownEvidence = (raw: unknown): Evidence | null => {
    try {
      const moment = parseEvidence(raw);
      return moment.submission_id === item.submission_id &&
        moment.recording_id === item.recording_id &&
        moment.source_sha256 === item.source_sha256 &&
        moment.transcript_revision === item.transcript_revision
        ? moment
        : null;
    } catch {
      return null;
    }
  };
  const evidence: Evidence[] = [];
  for (const raw of Array.isArray(item.evidence) ? item.evidence : []) {
    const moment = ownEvidence(raw);
    if (!moment) return null;
    if (evidence.length < 4) evidence.push(moment);
  }
  const focus = object(item.focus),
    mission = object(item.mission),
    lesson = object(item.lesson);
  const practice = object(item.practice),
    cause = object(item.root_cause);
  if (
    item.state === "ready" &&
    (!text(focus.skill_id) ||
      !text(focus.label) ||
      !text(mission.behavior) ||
      mission.skill_id !== focus.skill_id ||
      mission.origin_submission_id !== callId ||
      mission.status !== "active" ||
      !Number.isFinite(Date.parse(text(mission.active_since))) ||
      !Number.isFinite(Date.parse(text(focus.selected_at))) ||
      !text(lesson.title) ||
      lesson.next_call_connection !== mission.behavior)
  )
    return null;
  if (
    item.state === "unavailable" &&
    (item.focus ||
      evidence.length ||
      item.mission ||
      item.lesson ||
      item.practice)
  )
    return null;
  const ownCall = lesson.own_call == null ? null : ownEvidence(lesson.own_call);
  if (lesson.own_call != null && !ownCall) return null;
  // Optional: a malformed or foreign strength is dropped, never the coaching.
  const strengthItem = object(item.strength);
  const strengthEvidence = (
    Array.isArray(strengthItem.evidence) ? strengthItem.evidence : []
  ).map(ownEvidence);
  const strength =
    item.state === "ready" &&
    text(strengthItem.title) &&
    text(strengthItem.explanation) &&
    strengthEvidence.length &&
    strengthEvidence.every(Boolean)
      ? {
          title: text(strengthItem.title),
          explanation: text(strengthItem.explanation),
          evidence: (strengthEvidence as Evidence[]).slice(0, 2),
        }
      : null;
  return {
    schema: "ac.sales-xray.call-coaching/1",
    person_id: item.person_id as string,
    tenant_id: item.tenant_id as string,
    session_id: item.session_id as string | null | undefined,
    submission_id: callId,
    recording_id: item.recording_id as string,
    source_sha256: item.source_sha256 as string,
    transcript_revision: item.transcript_revision as string,
    report_revision: item.report_revision as string,
    call_label: text(item.call_label, "Sales call"),
    state: item.state as CallCoaching["state"],
    basis: item.basis as CallCoaching["basis"],
    evidence,
    media_clips: item.state === "ready" ? parseClips(item.media_clips) : [],
    strength,
    root_cause: {
      hypothesis: text(
        cause.hypothesis,
        "This call does not establish the reason for a recurring gap.",
      ),
      gap_type: text(cause.gap_type, "uncertain"),
      confidence: text(cause.confidence, "uncertain"),
    },
    focus:
      item.state === "ready"
        ? {
            skill_id: text(focus.skill_id),
            label: text(focus.label),
            explanation: text(focus.explanation),
            why_it_matters: text(focus.why_it_matters),
            selected_reason: text(
              focus.selected_reason,
              "Selected from this call's report.",
            ),
            selected_at: text(focus.selected_at),
            status: "provisional",
            verdict: text(focus.verdict, text(mission.behavior)),
          }
        : null,
    mission:
      item.state === "ready"
        ? {
            skill_id: text(mission.skill_id),
            behavior: text(mission.behavior),
            context: text(
              mission.context,
              "When a comparable situation gives you an opportunity.",
            ),
            done_when: text(
              mission.done_when,
              "Keep one attempted moment for review.",
            ),
            cue: text(mission.cue, "One useful change. Keep your own words."),
            active_since: text(mission.active_since),
            origin_submission_id: callId,
            status: "active",
          }
        : null,
    practice:
      item.state === "ready"
        ? {
            exercise: text(
              practice.exercise,
              "Review this call and rehearse one response in your own words.",
            ),
            success_condition: text(
              practice.success_condition,
              text(mission.done_when),
            ),
            gap_type: text(practice.gap_type, "uncertain"),
            estimated_minutes: null,
          }
        : null,
    lesson:
      item.state === "ready"
        ? {
            title: text(lesson.title),
            quick_idea: text(lesson.quick_idea),
            framework: texts(lesson.framework),
            why_it_matters: text(lesson.why_it_matters),
            good_looks_like: text(lesson.good_looks_like),
            better_direction: text(
              lesson.better_direction,
              text(mission.behavior),
            ),
            example_wording: texts(lesson.example_wording),
            when_to_use: text(lesson.when_to_use, text(mission.context)),
            when_not: text(
              lesson.when_not,
              "Use the change only when it fits the situation and respects the prospect's boundary.",
            ),
            checklist: texts(lesson.checklist),
            source: text(lesson.source, "Owner's approved Coaching guidance"),
            own_call: ownCall,
            next_call_connection: text(mission.behavior),
          }
        : null,
    limitations: texts(item.limitations),
  };
}

/** All reads return a result; private diagnostics never reach the page. */
export async function readCoaching(
  callId: string | null,
  init: RequestInit = {},
  origin = "",
): Promise<CoachingResult> {
  if (callId !== null && callId !== "team" && requestedCall(callId) !== callId)
    return {
      data: null,
      error: "This call link is invalid. Open the call's report again.",
    };
  try {
    const readHeaders = new Headers(init.headers);
    readHeaders.set("Accept", "application/json");
    const response = await fetch(`${origin}${coachingPath(callId)}`, {
      ...init,
      cache: "no-store",
      credentials: "same-origin",
      redirect: "error",
      signal: init.signal
        ? AbortSignal.any([init.signal, AbortSignal.timeout(10000)])
        : AbortSignal.timeout(10000),
      headers: readHeaders,
    });
    if (!response.ok)
      return {
        data: null,
        error:
          response.status === 401
            ? "Sign in to see your Coaching."
            : response.status === 403
              ? "Coaching is unavailable in this workspace."
              : response.status === 404 || response.status === 409
                ? "This call's coaching is unavailable. Open the call to check its analysis."
                : "Coaching could not be loaded. Try again.",
      };
    if (!response.headers.get("content-type")?.includes("application/json"))
      return { data: null, error: "Coaching could not be read. Try again." };
    const raw: unknown = await response.json();
    const data =
      callId === "team"
        ? parseTeamCoaching(raw)
        : callId
          ? parseCallCoaching(raw, callId)
          : parseCoaching(raw);
    return data
      ? { data, error: null }
      : { data: null, error: "Coaching could not be read. Try again." };
  } catch {
    return { data: null, error: "Coaching could not be loaded. Try again." };
  }
}
