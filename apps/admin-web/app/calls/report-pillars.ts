/**
 * The six pillars of the 9 October specification and the eight skills, as the
 * rep's Report names them. Pillar ids key reviewers' verdicts and gold labels,
 * so they never change; the content of each pillar comes from report-story.ts.
 */
import type { Evidence, Report } from "./call-data";

export const REPORT_PILLARS = [
  { id: "overview", label: "The Big Picture" },
  { id: "coaching", label: "How the Call Played Out" },
  { id: "moments", label: "What Worked & What Didn't" },
  { id: "missed", label: "Moments That Mattered" },
  { id: "skills", label: "Your Skills on This Call" },
  { id: "facts", label: "Where the Deal Stands" },
] as const;
export type PillarId = (typeof REPORT_PILLARS)[number]["id"];

export const REPORT_SKILLS = [
  ["human_connection_trust", "Human Connection & Trust"],
  ["discovery_deep_understanding", "Discovery & Deep Understanding"],
  ["qualification", "Qualification"],
  ["problem_impact_desire", "Problem, Impact & Desire Clarity"],
  ["solution_relevance_presentation", "Solution Relevance & Presentation"],
  ["certainty_objection_intelligence", "Certainty & Objection Intelligence"],
  ["closing_decision_management", "Closing & Decision Management"],
  ["communication_tonality", "Communication & Tonality"],
] as const;

export const SKILL_STATE_LABEL: Record<string, string> = {
  strongly_demonstrated: "Strongly Demonstrated",
  observed: "Observed",
  needs_attention: "Needs Attention",
  insufficient_evidence: "Not Enough Evidence",
  not_applicable: "Not Applicable",
};

export type PillarEntry = {
  label: string;
  text: string;
  evidence: Evidence[];
  gap?: boolean;
  hypothesis?: boolean;
  /** A short line under the text (e.g. where an outcome came from). */
  note?: string;
  /** Moments the rep sees only after "View all". */
  secondary?: boolean;
};
export type ReportPillar = {
  id: PillarId;
  label: string;
  entries: PillarEntry[];
  timeline?: { label: string; startMs: number; endMs: number }[];
  metrics?: { label: string; value: string; note?: string }[];
};

/** The skill state the rep sees for one dimension, or null when none is established. */
export function skillState(
  dimension: Report["dimensions"][number],
): string | null {
  if (dimension.callState)
    return SKILL_STATE_LABEL[dimension.callState] ?? null;
  if (dimension.status === "observed" && dimension.evidence.length)
    return "Observed";
  if (dimension.status === "insufficient_evidence")
    return "Not Enough Evidence";
  if (dimension.status === "not_applicable") return "Not Applicable";
  return null;
}
