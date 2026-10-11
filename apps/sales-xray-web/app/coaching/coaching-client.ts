import { parseClips, type CoachingClip } from "./media-contract";

export const COACHING_API = "/v1/me/coaching";
export class CoachingReadError extends Error {}
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export const MASTERY_STATES = [
  "not_enough_evidence",
  "emerging",
  "developing",
  "consistent",
  "strong",
  "mastered",
  "regression_detected",
  "re_stabilizing",
] as const;
export type MasteryState = (typeof MASTERY_STATES)[number];
export type Evidence = {
  submission_id: string;
  recording_id: string;
  source_sha256: string;
  transcript_revision: string;
  created_at: string;
  call_label: string;
  segment_id: string;
  quote: string;
  start_ms: number;
  end_ms: number;
  observation: string;
  playable: boolean;
};
export type Mission = {
  skill_id: string;
  behavior: string;
  context: string;
  done_when: string;
  cue: string;
  active_since: string;
  origin_submission_id: string;
  status: "active";
};
export type TextLesson = {
  title: string;
  quick_idea: string;
  framework: string[];
  why_it_matters: string;
  good_looks_like: string;
  better_direction: string;
  example_wording: string[];
  when_to_use: string;
  when_not: string;
  checklist: string[];
  source: string;
  own_call: Evidence;
  next_call_connection: string;
};
/** One of the learner's own calls, linking to that call's coaching. */
export type CallSummary = {
  submission_id: string;
  call_label: string;
  created_at: string;
  state: "ready" | "pending" | "unavailable";
  focus_label: string | null;
};
/** What one comparable call's report said about the focus skill. */
export type ProgressPoint = {
  submission_id: string;
  created_at: string;
  state: "suggested" | "no_suggestion" | "not_covered";
  after_mission: boolean;
};
export type Coaching = {
  schema: "ac.sales-xray.coaching/1";
  person_id: string;
  tenant_id: string;
  session_id?: string | null;
  authority: "provisional";
  entitlement: "coaching";
  state: "not_enough_evidence" | "ready";
  analysed_calls: number;
  pending_calls: number;
  unavailable_calls: number;
  history_limited: boolean;
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
  pattern: {
    relevant_call_count: number;
    attention_call_count: number;
    summary: string;
  };
  root_cause: { hypothesis: string; gap_type: string; confidence: string };
  evidence: Evidence[];
  practice: null | {
    exercise: string;
    success_condition: string;
    gap_type: string;
    estimated_minutes: number | null;
  };
  mission: Mission | null;
  mastery: {
    state: MasteryState;
    trend: string;
    relevant_count: number | null;
    correct_count: number | null;
    baseline: string | null;
    confidence: string;
    historical_achievement: MasteryState | null;
    explanation: string;
  };
  regression: { state: string; action: string };
  lesson: TextLesson | null;
  media_clips?: CoachingClip[];
  /** The newest own call's quoted "What worked" finding (spec 3.6). */
  strength?: Strength | null;
  calls?: CallSummary[];
  progress?: ProgressPoint[];
  development_path: {
    current: string | null;
    likely_next: string | null;
    maintain: string | null;
    later: string | null;
    explanation: string;
  };
  reflection_question: string | null;
  feedback_available: false;
  /** Fictional AC Sandbox data, read only by the person who imported it. */
  sandbox?: boolean;
  /** Whose coaching this is, when it is not the viewer's own. */
  person_name?: string | null;
  limitations: string[];
};

/** A quoted "What worked" finding from one of the learner's own calls. */
export type Strength = {
  title: string;
  explanation: string;
  evidence: Evidence[];
};

function invalid(): never {
  throw new CoachingReadError("Coaching could not be read. Try again.");
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return invalid();
  return value as Record<string, unknown>;
}
function string(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return invalid();
  return value;
}
function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    return invalid();
  return value;
}
function uuid(value: unknown): string {
  const result = string(value);
  if (!UUID_RE.test(result)) return invalid();
  return result;
}
function date(value: unknown): string {
  const result = string(value);
  if (!Number.isFinite(Date.parse(result))) return invalid();
  return result;
}
function strings(value: unknown): string[] {
  if (!Array.isArray(value)) return invalid();
  return value.map(string);
}
function fields(value: unknown, keys: string[]) {
  const item = record(value);
  for (const key of keys) string(item[key]);
  return item;
}
export function parseEvidence(value: unknown): Evidence {
  const item = fields(value, [
    "transcript_revision",
    "call_label",
    "segment_id",
    "quote",
    "observation",
  ]);
  uuid(item.submission_id);
  uuid(item.recording_id);
  date(item.created_at);
  if (!/^[0-9a-f]{64}$/.test(string(item.source_sha256))) return invalid();
  const start = count(item.start_ms),
    end = count(item.end_ms);
  if (end <= start || typeof item.playable !== "boolean") return invalid();
  return item as Evidence;
}
export function parseCoaching(value: unknown): Coaching {
  const item = record(value);
  if (
    item.schema !== "ac.sales-xray.coaching/1" ||
    item.authority !== "provisional" ||
    item.entitlement !== "coaching" ||
    item.entitlement_policy !== "AUT-1678-open-access" ||
    !["ready", "not_enough_evidence"].includes(string(item.state)) ||
    item.feedback_available !== false ||
    typeof item.history_limited !== "boolean"
  )
    return invalid();
  uuid(item.person_id);
  uuid(item.tenant_id);
  if (item.session_id != null) uuid(item.session_id);
  count(item.analysed_calls);
  count(item.pending_calls);
  count(item.unavailable_calls);
  if (!Array.isArray(item.evidence) || item.evidence.length > 4)
    return invalid();
  item.evidence.forEach(parseEvidence);
  strings(item.limitations);
  const pattern = fields(item.pattern, ["summary"]);
  if (count(pattern.attention_call_count) > count(pattern.relevant_call_count))
    return invalid();
  fields(item.root_cause, ["hypothesis", "gap_type", "confidence"]);
  fields(item.regression, ["state", "action"]);
  const mastery = fields(item.mastery, ["trend", "confidence", "explanation"]);
  if (!MASTERY_STATES.includes(mastery.state as MasteryState)) return invalid();
  for (const key of ["relevant_count", "correct_count"])
    if (mastery[key] !== null) count(mastery[key]);
  if (
    (mastery.correct_count === null) !== (mastery.relevant_count === null) ||
    (typeof mastery.correct_count === "number" &&
      typeof mastery.relevant_count === "number" &&
      mastery.correct_count > mastery.relevant_count)
  )
    return invalid();
  if (mastery.baseline !== null) string(mastery.baseline);
  if (
    mastery.historical_achievement !== null &&
    !MASTERY_STATES.includes(mastery.historical_achievement as MasteryState)
  )
    return invalid();
  const path = fields(item.development_path, ["explanation"]);
  for (const key of ["current", "likely_next", "maintain", "later"])
    if (path[key] !== null) string(path[key]);
  if (item.reflection_question !== null) string(item.reflection_question);
  if (item.focus === null) {
    if (
      item.state !== "not_enough_evidence" ||
      item.mission !== null ||
      item.practice !== null ||
      item.lesson !== null
    )
      return invalid();
  } else {
    const focus = fields(item.focus, [
      "skill_id",
      "label",
      "explanation",
      "why_it_matters",
      "selected_reason",
      "verdict",
    ]);
    date(focus.selected_at);
    if (
      !["active", "provisional"].includes(string(focus.status)) ||
      item.state !== "ready" ||
      !item.evidence.length
    )
      return invalid();
    const mission = fields(item.mission, [
      "skill_id",
      "behavior",
      "context",
      "done_when",
      "cue",
    ]);
    date(mission.active_since);
    uuid(mission.origin_submission_id);
    if (mission.status !== "active" || mission.skill_id !== focus.skill_id)
      return invalid();
    const practice = fields(item.practice, [
      "exercise",
      "success_condition",
      "gap_type",
    ]);
    if (practice.estimated_minutes !== null) count(practice.estimated_minutes);
    const lesson = fields(item.lesson, [
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
    strings(lesson.framework);
    strings(lesson.example_wording);
    strings(lesson.checklist);
    parseEvidence(lesson.own_call);
    if (lesson.next_call_connection !== mission.behavior) return invalid();
  }
  // Catalogue access/review is pending. Never expose an unparsed media URL.
  if (item.recommended_media !== null || item.other_format !== null)
    return invalid();
  return {
    ...item,
    media_clips: parseClips(item.media_clips),
    strength: item.state === "ready" ? parseStrength(item.strength) : null,
    calls: parseCallSummaries(item.calls),
    progress: parseProgress(item.progress),
    sandbox: item.sandbox === true,
    person_name:
      typeof item.person_name === "string" && item.person_name.trim()
        ? item.person_name.slice(0, 120)
        : null,
  } as Coaching;
}

/** Optional: a malformed or foreign strength is dropped, never the page. */
export function parseStrength(
  value: unknown,
  own: (moment: Evidence) => boolean = () => true,
): Strength | null {
  try {
    const item = record(value);
    const title = string(item.title),
      explanation = string(item.explanation);
    if (!Array.isArray(item.evidence)) return null;
    const evidence = item.evidence.slice(0, 2).map(parseEvidence);
    return evidence.length && evidence.every(own)
      ? { title, explanation, evidence }
      : null;
  } catch {
    return null;
  }
}

/** Optional strip: a malformed point is dropped, never fatal to the page. */
export function parseProgress(value: unknown): ProgressPoint[] {
  if (!Array.isArray(value)) return [];
  const points: ProgressPoint[] = [];
  for (const raw of value.slice(-40)) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const row = raw as Record<string, unknown>;
    if (
      typeof row.submission_id !== "string" ||
      !UUID_RE.test(row.submission_id) ||
      typeof row.created_at !== "string" ||
      !Number.isFinite(Date.parse(row.created_at)) ||
      !["suggested", "no_suggestion", "not_covered"].includes(
        String(row.state),
      ) ||
      typeof row.after_mission !== "boolean"
    )
      continue;
    points.push({
      submission_id: row.submission_id,
      created_at: row.created_at,
      state: row.state as ProgressPoint["state"],
      after_mission: row.after_mission,
    });
  }
  return points;
}

/** Optional list: a malformed row is dropped, never fatal to the page. */
export function parseCallSummaries(value: unknown): CallSummary[] {
  if (!Array.isArray(value)) return [];
  const rows: CallSummary[] = [];
  const seen = new Set<string>();
  for (const raw of value.slice(0, 40)) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const row = raw as Record<string, unknown>;
    const id = typeof row.submission_id === "string" ? row.submission_id : "";
    if (
      !UUID_RE.test(id) ||
      seen.has(id) ||
      typeof row.call_label !== "string" ||
      !row.call_label.trim() ||
      typeof row.created_at !== "string" ||
      !Number.isFinite(Date.parse(row.created_at)) ||
      !["ready", "pending", "unavailable"].includes(String(row.state))
    )
      continue;
    seen.add(id);
    rows.push({
      submission_id: id,
      call_label: row.call_label,
      created_at: row.created_at,
      state: row.state as CallSummary["state"],
      focus_label:
        typeof row.focus_label === "string" && row.focus_label.trim()
          ? row.focus_label
          : null,
    });
  }
  return rows;
}

export async function fetchCoaching(signal: AbortSignal): Promise<Coaching> {
  const response = await fetch(COACHING_API, {
    credentials: "same-origin",
    cache: "no-store",
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new CoachingReadError(
      response.status === 401
        ? "Sign in to see your Coaching."
        : response.status === 403
          ? "Coaching is unavailable in this workspace."
          : "Coaching could not be loaded. Try again.",
    );
  }
  if (!response.headers.get("content-type")?.includes("application/json"))
    return invalid();
  return parseCoaching(await response.json());
}
