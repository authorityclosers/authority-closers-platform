import { requestedSkill, requestedSkillLabel } from "./focus-request";
import { requestedCall } from "./call-request";

// Fixed call-map objection kinds (call_signals_v1); server labels are discarded.
const OBJECTIONS: Record<string, string> = {
  price_concern: "Price",
  affordability_gap: "Affordability",
  time_constraint: "Timing",
  stall: "Stalling",
  competitor_or_status_quo: "Competitor or status quo",
  decision_maker_absent: "Decision maker not there",
  trust_concern: "Trust",
  other: "Other objections",
};

/** How often the team hears one kind of buyer objection, and how it was met. */
export type TeamObjection = {
  kind: string;
  label: string;
  calls: number;
  heard: number;
  /** Answered or met with a question back; the rest were deflected or ignored. */
  handled: number;
};

/** A fictional AC Sandbox rep with their newest call's focus. */
export type TeamRep = {
  person_id: string;
  name: string;
  skill_id: string | null;
  focus_label: string | null;
  calls: number;
  latest_call_at: string | null;
  /** When a real rep shared their coaching; absent for fictional reps. */
  shared_at: string | null;
};

export type TeamCoaching = {
  schema: "ac.sales-xray.team-coaching/1";
  person_id: string;
  tenant_id: string;
  session_id?: string | null;
  /** "sandbox": fictional AC Sandbox reps, named, for the person who imported them. */
  scope: "anonymous" | "sandbox";
  named_rep_details: boolean;
  sandbox: boolean;
  reps: TeamRep[];
  /** Why reps are named: fictional sandbox reps, or real reps who shared. */
  reps_basis: "none" | "fictional" | "shared";
  analysed_calls: number;
  /** How many people the calls belong to; never who. Optional: older APIs. */
  rep_count: number;
  pending_calls: number;
  unavailable_calls: number;
  history_limited: boolean;
  /** Newest counted call's date; never whose call it was. */
  latest_call_at: string | null;
  suggestions: { skill_id: string; label: string; suggestion_calls: number }[];
  /** From v7 report call maps; `objection_calls` is how many calls had one. */
  objections: TeamObjection[];
  objection_calls: number;
  limitations: string[];
};

export function parseTeamCoaching(raw: unknown): TeamCoaching | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const data = raw as Record<string, unknown>;
  // Names only for fictional AC Sandbox reps or real reps who shared. Any
  // other rep detail rejects the whole view; it is never shown.
  const sandbox = data.sandbox === true && data.scope === "sandbox";
  const named = Array.isArray(data.reps) && data.reps.length > 0;
  const basis =
    named && sandbox && data.reps_basis === "fictional"
      ? "fictional"
      : named &&
          !sandbox &&
          data.scope === "anonymous" &&
          data.reps_basis === "shared"
        ? "shared"
        : "none";
  if (
    data.schema !== "ac.sales-xray.team-coaching/1" ||
    (data.scope !== "anonymous" && data.scope !== "sandbox") ||
    (data.sandbox === true) !== (data.scope === "sandbox") ||
    (named && (basis === "none" || data.named_rep_details !== true)) ||
    (!named && data.named_rep_details === true) ||
    (data.reps != null && !Array.isArray(data.reps)) ||
    data.entitlement !== "coaching" ||
    data.entitlement_policy !== "AUT-1678-open-access" ||
    !requestedCall(data.person_id) ||
    !requestedCall(data.tenant_id) ||
    (data.session_id != null && !requestedCall(data.session_id)) ||
    ["people", "evidence", "missions", "focus", "root_cause", "calls"].some(
      (key) => data[key] != null,
    )
  )
    return null;
  const count = (value: unknown): number | null =>
    value == null
      ? 0
      : typeof value === "number" && Number.isSafeInteger(value) && value >= 0
        ? value
        : null;
  const analysed = count(data.analysed_calls),
    pending = count(data.pending_calls),
    unavailable = count(data.unavailable_calls);
  if (analysed === null || pending === null || unavailable === null)
    return null;
  const suggestions: TeamCoaching["suggestions"] = [];
  const seen = new Set<string>();
  for (const raw of Array.isArray(data.suggestions) ? data.suggestions : []) {
    if (!raw || typeof raw !== "object") return null;
    const row = raw as Record<string, unknown>,
      skill = requestedSkill(row.skill_id);
    if (!skill && row.skill_id !== "report_next_step") return null;
    const id = skill ?? "report_next_step",
      calls = count(row.suggestion_calls);
    if (calls === null || calls < 1 || calls > analysed || seen.has(id))
      return null;
    seen.add(id);
    // Server labels are discarded: only the approved taxonomy reaches the UI.
    suggestions.push({
      skill_id: id,
      label: skill
        ? requestedSkillLabel(skill)
        : "Other call report suggestions",
      suggestion_calls: calls,
    });
  }
  return {
    schema: "ac.sales-xray.team-coaching/1",
    person_id: data.person_id as string,
    tenant_id: data.tenant_id as string,
    session_id: data.session_id as string | null | undefined,
    scope: sandbox ? "sandbox" : "anonymous",
    named_rep_details: basis !== "none",
    sandbox,
    reps_basis: basis,
    reps: basis === "none" ? [] : parseReps(data.reps, basis === "shared"),
    objections: parseObjections(data.objections, analysed),
    objection_calls: Math.min(count(data.objection_calls) ?? 0, analysed),
    analysed_calls: analysed,
    rep_count:
      Number.isSafeInteger(data.rep_count) && (data.rep_count as number) > 0
        ? (data.rep_count as number)
        : 0,
    pending_calls: pending,
    unavailable_calls: unavailable,
    history_limited: data.history_limited === true,
    latest_call_at:
      typeof data.latest_call_at === "string" &&
      Number.isFinite(Date.parse(data.latest_call_at))
        ? data.latest_call_at
        : null,
    suggestions,
    limitations: Array.isArray(data.limitations)
      ? data.limitations.filter((s): s is string => typeof s === "string")
      : [],
  };
}

/** Malformed rows are dropped; the rest of the team view still shows. */
function parseReps(value: unknown, shared: boolean): TeamRep[] {
  const reps: TeamRep[] = [];
  const seen = new Set<string>();
  for (const raw of Array.isArray(value) ? value.slice(0, 500) : []) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const id = requestedCall(row.person_id);
    const name = typeof row.name === "string" ? row.name.trim() : "";
    const sharedAt =
      typeof row.shared_at === "string" &&
      Number.isFinite(Date.parse(row.shared_at))
        ? row.shared_at
        : null;
    // A real rep appears only with the date they shared.
    if (!id || !name || seen.has(id) || (shared && !sharedAt)) continue;
    seen.add(id);
    reps.push({
      person_id: id,
      name: name.slice(0, 120),
      skill_id: requestedSkill(row.skill_id) ?? null,
      focus_label:
        typeof row.focus_label === "string" && row.focus_label.trim()
          ? row.focus_label.slice(0, 240)
          : null,
      calls:
        Number.isSafeInteger(row.calls) && (row.calls as number) > 0
          ? (row.calls as number)
          : 0,
      latest_call_at:
        typeof row.latest_call_at === "string" &&
        Number.isFinite(Date.parse(row.latest_call_at))
          ? row.latest_call_at
          : null,
      shared_at: shared ? sharedAt : null,
    });
  }
  return reps;
}

/** Unknown kinds or impossible counts drop that row, never the team view. */
function parseObjections(value: unknown, analysed: number): TeamObjection[] {
  const rows: TeamObjection[] = [];
  const seen = new Set<string>();
  for (const raw of Array.isArray(value) ? value.slice(0, 8) : []) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const kind = typeof row.kind === "string" ? row.kind : "";
    const whole = (n: unknown) =>
      Number.isSafeInteger(n) && (n as number) >= 0 ? (n as number) : -1;
    const calls = whole(row.calls),
      heard = whole(row.heard),
      handled = whole(row.handled);
    if (
      !Object.hasOwn(OBJECTIONS, kind) ||
      seen.has(kind) ||
      calls < 1 ||
      calls > analysed ||
      heard < calls ||
      handled < 0 ||
      handled > heard
    )
      continue;
    seen.add(kind);
    rows.push({ kind, label: OBJECTIONS[kind], calls, heard, handled });
  }
  return rows;
}
