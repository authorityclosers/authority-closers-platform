import { requestedSkill, requestedSkillLabel } from "./focus-request";
import { requestedCall } from "./call-request";

export type TeamCoaching = {
  schema: "ac.sales-xray.team-coaching/1";
  person_id: string;
  tenant_id: string;
  session_id?: string | null;
  scope: "anonymous";
  named_rep_details: false;
  analysed_calls: number;
  pending_calls: number;
  unavailable_calls: number;
  history_limited: boolean;
  suggestions: { skill_id: string; label: string; suggestion_calls: number }[];
  limitations: string[];
};

export function parseTeamCoaching(raw: unknown): TeamCoaching | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const data = raw as Record<string, unknown>;
  if (
    data.schema !== "ac.sales-xray.team-coaching/1" ||
    data.scope !== "anonymous" ||
    data.named_rep_details !== false ||
    data.entitlement !== "coaching" ||
    data.entitlement_policy !== "AUT-1678-open-access" ||
    !requestedCall(data.person_id) ||
    !requestedCall(data.tenant_id) ||
    (data.session_id != null && !requestedCall(data.session_id)) ||
    [
      "reps",
      "people",
      "evidence",
      "missions",
      "focus",
      "root_cause",
      "calls",
    ].some((key) => data[key] != null)
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
    scope: "anonymous",
    named_rep_details: false,
    analysed_calls: analysed,
    pending_calls: pending,
    unavailable_calls: unavailable,
    history_limited: data.history_limited === true,
    suggestions,
    limitations: Array.isArray(data.limitations)
      ? data.limitations.filter((s): s is string => typeof s === "string")
      : [],
  };
}
