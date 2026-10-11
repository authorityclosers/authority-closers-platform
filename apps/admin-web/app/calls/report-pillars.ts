/**
 * The six pillars of the 9 October specification, as the rep's Report shows
 * them. A line-for-line port of apps/sales-xray-web/app/report-pillars.ts onto
 * the console's types, so reviewers judge exactly what reps see: presentation
 * of validated C5 output only — no extraction, no scoring, gaps stay gaps.
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
};
export type ReportPillar = {
  id: PillarId;
  label: string;
  entries: PillarEntry[];
  timeline?: { label: string; startMs: number; endMs: number }[];
};

const gap = (
  label: string,
  text = "Not established in this report.",
): PillarEntry => ({
  label,
  text,
  evidence: [],
  gap: true,
});

const PHASE_LABEL: Record<string, string> = {
  opening: "Opening",
  discovery: "Discovery",
  pitch: "Offer discussion",
  objection: "Concerns",
  close: "Decision discussion",
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

export function reportPillars(
  report: Report,
  durationMs?: number | null,
): ReportPillar[] {
  const overview = report.overview;
  const story = report.story;
  const sourced = (
    label: string,
    text: string,
    evidence: Evidence[] | undefined,
    hypothesis = false,
  ): PillarEntry =>
    evidence?.length
      ? { label, text, evidence, hypothesis }
      : gap(label, "No supporting quote was supplied for this observation.");

  const outcomeText: Record<string, string> = {
    won: "Won",
    lost: "Lost",
    disqualified: "Disqualified",
  };
  const picture: PillarEntry[] = [
    story?.outcome.evidence.length && outcomeText[story.outcome.kind]
      ? {
          label: "Call outcome",
          text: outcomeText[story.outcome.kind]!,
          evidence: story.outcome.evidence,
        }
      : story?.outcome.kind === "follow_up" &&
          story.nextStep &&
          ["dated_call", "invite_sent", "committed"].includes(
            story.outcome.nextStepRung,
          )
        ? {
            label: "Call outcome",
            text: "Follow-up Set",
            evidence: story.outcome.evidence,
          }
        : gap("Call outcome"),
    {
      label: "Call summary",
      text: report.summary,
      evidence: report.summaryEvidence,
    },
    ...(!report.summaryEvidence.length
      ? [
          gap(
            "Summary evidence",
            "No supporting quote was supplied for the summary.",
          ),
        ]
      : []),
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
    story?.nextStep
      ? { label: "Next agreed step", ...story.nextStep }
      : gap("Next agreed step"),
  ];

  const timeline = durationMs
    ? story?.phases.map((phase, index) => ({
        label: PHASE_LABEL[phase.name] ?? phase.name,
        startMs: phase.startMs,
        endMs: story.phases[index + 1]?.startMs ?? durationMs,
      }))
    : undefined;
  const flow: PillarEntry[] = timeline?.length
    ? []
    : [
        gap(
          "Conversation timeline",
          "Conversation phases were not supplied for this call.",
        ),
      ];
  const change = overview?.conversationChange;
  if (change) {
    for (const [label, entry] of [
      ["Before", change.before],
      ["Key change", change.change],
      ["After", change.after],
    ] as const)
      flow.push(sourced(label, entry.text, entry.evidence));
    flow.push({
      label: "Possible effect",
      text: change.possibleEffect,
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
    const detail = overview?.strengthDetails.find(
      (item) => item.findingIndex === index,
    );
    if (detail && finding.evidence.length)
      worked.push({
        label: "Why it may have helped",
        text: detail.whyItMatters,
        evidence: finding.evidence,
        hypothesis: true,
      });
  });
  if (report.strengths.filter((finding) => finding.evidence.length).length < 3)
    worked.push(
      gap(
        "Strengths",
        "Fewer than three supported strengths were supplied. No extra strengths have been added.",
      ),
    );
  report.improvements.slice(0, 3).forEach((finding, index) => {
    const detail = overview?.improvementDetails.find(
      (item) => item.findingIndex === index,
    );
    worked.push(
      detail
        ? sourced(
            `What didn't · ${finding.title}`,
            detail.whatHappened.text,
            detail.whatHappened.evidence,
          )
        : gap(
            `What didn't · ${finding.title}`,
            "A separate call observation was not supplied for this item.",
          ),
    );
    if (detail?.whatHappened.evidence.length)
      worked.push({
        label: "What it may have affected",
        text: detail.whyItMatters,
        evidence: detail.whatHappened.evidence,
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
  for (const moment of overview?.goldenMoments ?? []) {
    const finding = report.strengths[moment.strengthIndex];
    const quote = finding?.evidence[moment.evidenceIndex];
    if (!finding || !quote) continue;
    const key = `${quote.segmentId}:${quote.startMs}:${quote.endMs}`;
    if (seen.has(key)) continue;
    seen.add(key);
    moments.push({
      label: `Strong moment · ${finding.title}`,
      text: moment.whyEffective,
      evidence: [quote],
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
    const dimension = report.dimensions.find((item) => item.id === id);
    if (!dimension)
      return gap(label, "No assessment was supplied for this skill.");
    const state = skillState(dimension);
    return {
      label: `${label} · ${state ?? "State not established"}`,
      text: state
        ? dimension.observation
        : "The supplied assessment does not establish one of this report's skill states.",
      evidence: state ? dimension.evidence : [],
      gap: state === null,
    };
  });

  const outcome = picture[0]!;
  const deal: PillarEntry[] = [
    { ...outcome, label: "Current status" },
    overview?.outcome
      ? sourced(
          "Prospect's position",
          overview.outcome.text,
          overview.outcome.evidence,
        )
      : gap("Prospect's position"),
    gap("Current blocker"),
    ...(story?.prospectTasks ?? []).map((entry) => ({
      label: "Task for the prospect mentioned",
      text: entry.text,
      evidence: entry.evidence,
    })),
    ...(story?.prospectCommitments.length
      ? story.prospectCommitments.map((entry) => ({
          label: "Prospect commitment",
          text: entry.text,
          evidence: entry.evidence,
        }))
      : [gap("Prospect commitment")]),
    ...(story?.sellerCommitments.length
      ? story.sellerCommitments.map((entry) => ({
          label: "Seller commitment",
          text: [entry.text, entry.dueText].filter(Boolean).join(" · "),
          evidence: entry.evidence,
        }))
      : [gap("Seller commitment")]),
    story?.outcome.nextStepWhen && story.outcome.evidence.length
      ? {
          label: "Next event timing · as stated",
          text: story.outcome.nextStepWhen,
          evidence: story.outcome.evidence,
        }
      : gap("Next event"),
    gap("Commitment quality"),
    gap("What is still unclear"),
    gap("Recommended deal action"),
  ];

  return REPORT_PILLARS.map((pillar, index) => ({
    ...pillar,
    entries: [picture, flow, worked, moments, skills, deal][index]!,
    ...(index === 1 && timeline?.length ? { timeline } : {}),
  }));
}
