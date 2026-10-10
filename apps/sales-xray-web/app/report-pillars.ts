import type { ReportEvidence, SalesReport } from "./report-contract";

/** Stable Word bookmarks, in the 9 October specification's story order. */
export const REPORT_PILLARS = [
  { id: "overview", label: "The Big Picture" },
  { id: "coaching", label: "How the Call Played Out" },
  { id: "moments", label: "What Worked & What Didn't" },
  { id: "missed", label: "Moments That Mattered" },
  { id: "skills", label: "Your Skills on This Call" },
  { id: "facts", label: "Where the Deal Stands" },
] as const;

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

export type PillarEntry = {
  label: string;
  text: string;
  evidence: ReportEvidence[];
  gap?: boolean;
  hypothesis?: boolean;
};
export type ReportPillar = {
  id: (typeof REPORT_PILLARS)[number]["id"];
  label: string;
  entries: PillarEntry[];
};

const gap = (
  label: string,
  text = "Not established in this report.",
): PillarEntry => ({ label, text, evidence: [], gap: true });

/** Presentation of existing validated C5 output; no extraction or scoring. */
export function reportPillars(report: SalesReport): ReportPillar[] {
  const overview = report.overview;
  const sourced = (
    label: string,
    text: string,
    evidence: ReportEvidence[] | undefined,
    hypothesis = false,
  ): PillarEntry =>
    evidence?.length
      ? { label, text, evidence, hypothesis }
      : gap(label, "No supporting quote was supplied for this observation.");
  const picture: PillarEntry[] = [
    {
      label: "Call summary",
      text: report.summary,
      evidence: report.summary_evidence ?? [],
    },
    ...(!report.summary_evidence?.length
      ? [
          gap(
            "Summary evidence",
            "No supporting quote was supplied for the summary.",
          ),
        ]
      : []),
    gap("Call outcome"),
    ...(overview?.outcome
      ? [
          sourced(
            "Outcome observation",
            overview.outcome.text,
            overview.outcome.evidence,
          ),
        ]
      : []),
    ...(overview?.diagnosis
      ? [
          sourced(
            "Possible influence",
            overview.diagnosis.text,
            overview.diagnosis.evidence,
            true,
          ),
        ]
      : [gap("What most affected this call")]),
    gap("Strongest part"),
    gap("Biggest concern"),
    gap("Next agreed step"),
  ];
  const flow: PillarEntry[] = [
    gap(
      "Conversation timeline",
      "Conversation phases were not supplied for this call.",
    ),
  ];
  const change = overview?.conversation_change;
  if (change) {
    for (const [label, note] of [
      ["Before", change.before],
      ["Key change", change.change],
      ["After", change.after],
    ] as const)
      flow.push(sourced(label, note.text, note.evidence));
    flow.push({
      label: "Possible effect",
      text: change.possible_effect,
      evidence: change.change.evidence,
      hypothesis: true,
    });
  } else flow.push(gap("Key change"));

  const worked: PillarEntry[] = [];
  report.strengths.slice(0, 5).forEach((finding, index) => {
    worked.push(
      sourced(
        `What worked · ${finding.title}`,
        finding.explanation,
        finding.evidence,
      ),
    );
    const detail = overview?.strength_details.find(
      (item) => item.finding_index === index,
    );
    if (detail && finding.evidence.length)
      worked.push({
        label: "Why it may have helped",
        text: detail.why_it_matters,
        evidence: finding.evidence,
        hypothesis: true,
      });
  });
  if (report.strengths.filter((f) => f.evidence.length).length < 3)
    worked.push(
      gap(
        "Strengths",
        "Fewer than three supported strengths were supplied. No extra strengths have been added.",
      ),
    );
  report.improvements.slice(0, 3).forEach((finding, index) => {
    const detail = overview?.improvement_details.find(
      (item) => item.finding_index === index,
    );
    worked.push(
      detail
        ? sourced(
            `What didn't · ${finding.title}`,
            detail.what_happened.text,
            detail.what_happened.evidence,
          )
        : gap(
            `What didn't · ${finding.title}`,
            "A separate call observation was not supplied for this item.",
          ),
    );
    if (detail?.what_happened.evidence.length)
      worked.push({
        label: "What it may have affected",
        text: detail.why_it_matters,
        evidence: detail.what_happened.evidence,
        hypothesis: true,
      });
  });
  if (!report.improvements.length)
    worked.push(
      gap(
        "What didn't",
        "No supported issue was supplied. This does not establish that there were no issues.",
      ),
    );

  const moments: PillarEntry[] = [];
  const seen = new Set<string>();
  for (const moment of overview?.golden_moments ?? []) {
    const finding = report.strengths[moment.strength_index];
    const evidence = finding?.evidence[moment.evidence_index];
    if (!evidence) continue;
    const key = `${evidence.segment_id}:${evidence.start_ms}:${evidence.end_ms}`;
    if (seen.has(key)) continue;
    seen.add(key);
    moments.push({
      label: `Strong moment · ${finding.title}`,
      text: moment.why_effective,
      evidence: [evidence],
      hypothesis: true,
    });
    if (moments.length === 5) break;
  }
  if (moments.length < 3)
    moments.push(
      gap(
        "Moments",
        "Fewer than three categorised moments were supplied. No extra moments have been added.",
      ),
    );
  // Legacy missed_details do not establish the opportunity/speaker gate.
  moments.push(
    gap(
      "Missed chances",
      "The evidence needed to verify a missed chance was not supplied.",
    ),
  );
  const skills = REPORT_SKILLS.map(([id, label]): PillarEntry => {
    const dimension = report.dimensions.find(
      (item) => item.dimension_id === id,
    );
    if (!dimension)
      return gap(label, "No assessment was supplied for this skill.");
    const state =
      dimension.status === "observed" && dimension.evidence?.length
        ? "Observed"
        : dimension.status === "insufficient_evidence"
          ? "Not Enough Evidence"
          : dimension.status === "not_applicable"
            ? "Not Applicable"
            : null;
    return {
      label: `${label} · ${state ?? "State not established"}`,
      text: state
        ? dimension.observation
        : "The supplied assessment does not establish one of this report's skill states.",
      evidence: state ? (dimension.evidence ?? []) : [],
      gap: state === null,
    };
  });
  const deal = [
    "Current status",
    "Prospect's position",
    "Current blocker",
    "Prospect commitment",
    "Seller commitment",
    "Next event",
    "Commitment quality",
    "What is still unclear",
    "Recommended deal action",
  ].map((label) => gap(label));
  return REPORT_PILLARS.map((pillar, index) => ({
    ...pillar,
    entries: [picture, flow, worked, moments, skills, deal][index],
  }));
}
