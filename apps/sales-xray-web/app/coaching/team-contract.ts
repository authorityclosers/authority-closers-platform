import { requestedSkill, requestedSkillLabel } from "./focus-request";
import { requestedCall } from "./call-request";

/** A fictional AC Sandbox rep with their newest call's focus. */
export type TeamRep = {
  person_id: string;
  name: string;
  skill_id: string | null;
  focus_label: string | null;
  calls: number;
  latest_call_at: string | null;
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
  analysed_calls: number;
  /** How many people the calls belong to; never who. Optional: older APIs. */
  rep_count: number;
  pending_calls: number;
  unavailable_calls: number;
  history_limited: boolean;
  /** Newest counted call's date; never whose call it was. */
  latest_call_at: string | null;
  suggestions: { skill_id: string; label: string; suggestion_calls: number }[];
  limitations: string[];
};

export function parseTeamCoaching(raw: unknown): TeamCoaching | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const data = raw as Record<string, unknown>;
  // Names only for fictional AC Sandbox reps. A real team's totals that carry
  // any rep detail are rejected whole, never shown.
  const sandbox =
    data.sandbox === true &&
    data.scope === "sandbox" &&
    data.named_rep_details === true;
  if (
    data.schema !== "ac.sales-xray.team-coaching/1" ||
    (!sandbox &&
      (data.scope !== "anonymous" ||
        data.named_rep_details !== false ||
        data.sandbox === true ||
        (Array.isArray(data.reps)
          ? data.reps.length > 0
          : data.reps != null))) ||
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
    named_rep_details: sandbox,
    sandbox,
    reps: sandbox ? parseReps(data.reps) : [],
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
function parseReps(value: unknown): TeamRep[] {
  const reps: TeamRep[] = [];
  const seen = new Set<string>();
  for (const raw of Array.isArray(value) ? value.slice(0, 500) : []) {
    if (!raw || typeof raw !== "object") continue;
    const row = raw as Record<string, unknown>;
    const id = requestedCall(row.person_id);
    const name = typeof row.name === "string" ? row.name.trim() : "";
    if (!id || !name || seen.has(id)) continue;
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
    });
  }
  return reps;
}
