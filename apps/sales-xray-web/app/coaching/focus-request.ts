/** A report link adds context; it never selects a person or rotates a mission. */
const labels = {
  human_connection_trust: "Human Connection & Trust",
  discovery_deep_understanding: "Discovery & Deep Understanding",
  qualification: "Qualification",
  problem_impact_desire: "Problem, Impact & Desire Clarity",
  solution_relevance_presentation: "Solution Relevance & Presentation",
  certainty_objection_intelligence: "Certainty & Objection Intelligence",
  closing_decision_management: "Closing & Decision Management",
  communication_tonality: "Communication & Tonality",
} as const;

export type RequestedSkill = keyof typeof labels;

export function requestedSkill(value: unknown): RequestedSkill | undefined {
  return typeof value === "string" && Object.hasOwn(labels, value)
    ? (value as RequestedSkill)
    : undefined;
}

export function requestedSkillLabel(value: RequestedSkill): string {
  return labels[value];
}
