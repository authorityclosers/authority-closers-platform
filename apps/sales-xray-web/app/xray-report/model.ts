import type { ReportEvidence } from "../report-contract";
import type { Line, OutcomeStatus, StoryModel } from "../report-story-model";

/**
 * The Report's three parts (owner doc "15th Oct sales x-ray structure"):
 * Overview & Score, Detailed Call Analysis, Final Call Outcome.
 *
 * Scores are never computed here. A score, a pointer status and the pointer
 * feedback only ever come from the analysis payload (AC-SVAL: no new
 * autonomous scoring in the browser); without one a pointer is "not scored".
 */

export type PointerStatus =
  | "excellent"
  | "good"
  | "average"
  | "needs_improvement"
  | "not_observed"
  | "not_applicable"
  | "insufficient_evidence";

export const SCORED_STATUSES = [
  "excellent",
  "good",
  "average",
  "needs_improvement",
] as const satisfies readonly PointerStatus[];

export const UNSCORED_STATUSES = [
  "not_observed",
  "not_applicable",
  "insufficient_evidence",
] as const satisfies readonly PointerStatus[];

export type ScoredStatus = (typeof SCORED_STATUSES)[number];
export type UnscoredStatus = (typeof UNSCORED_STATUSES)[number];

export function isScored(status: PointerStatus | null): status is ScoredStatus {
  return (SCORED_STATUSES as readonly string[]).includes(status ?? "");
}

/** The doc's score legend: 90-100 Excellent, 70-89 Good, 50-69 Average, below 50. */
export function scoreBand(score: number): ScoredStatus {
  if (score >= 90) return "excellent";
  if (score >= 70) return "good";
  if (score >= 50) return "average";
  return "needs_improvement";
}

export type PointerQuote = {
  who: "you" | "prospect" | "other";
  /** A confirmed name when the call map has one; otherwise the role is shown. */
  name: string | null;
  at_ms: number;
  text: string;
  /** The playable source; fictional examples carry none. */
  source: ReportEvidence | null;
};

export type Pointer = {
  id: string;
  number: number;
  name: string;
  evaluates: string;
  /** Null: the analysis has not evaluated this pointer yet. */
  status: PointerStatus | null;
  score: number | null;
  whatHappened: string | null;
  whyItMatters: string | null;
  evidence: PointerQuote[];
  howToImprove: string[];
  training: {
    title: string;
    minutes: number | null;
    href: string | null;
  } | null;
  /** What the analysis saw that bears on this pointer, without judging it. */
  related: Line[];
};

export type Stat = { value: string; sub: string };

export type OutcomeKind = "won" | "lost" | "follow_up" | "decision_pending";

export type NextStep = {
  text: string;
  date: string | null;
  owner: "you" | "prospect" | null;
  source: ReportEvidence | null;
};

/** The server's word on a report without scores (owner, 18 Oct). */
export type Scoring = {
  status: "scoring" | "before_scores" | "not_scored";
  reportCreatedAt: string | null;
} | null;

/** Scores usually land this long after the report (2-minute runner + review). */
export const SCORING_MINUTES = 3;

/** What to say while a call has no scores: "Scoring…" for a new call. */
export function scoringNote(
  scoring: Scoring | undefined,
  now = Date.now(),
): { title: string; body: string; pending: boolean } {
  if (scoring?.status === "scoring") {
    const created = scoring.reportCreatedAt
      ? Date.parse(scoring.reportCreatedAt)
      : NaN;
    const elapsed = Number.isNaN(created) ? 0 : (now - created) / 60_000;
    if (elapsed < 10) {
      const left = Math.max(1, Math.ceil(SCORING_MINUTES - elapsed));
      return {
        title: "Scoring…",
        body: `Scoring this call’s 27 pointers, about ${left} min. The scores appear here by themselves.`,
        pending: true,
      };
    }
    return {
      title: "Scoring…",
      body: "Scoring is taking longer than usual. The scores appear here as soon as they’re ready.",
      pending: true,
    };
  }
  if (scoring?.status === "not_scored")
    return {
      title: "Not scored",
      body: "This call has no pointer scores. Its next analysis scores the pointers.",
      pending: false,
    };
  return {
    title: "Not scored yet",
    body: "This call was analysed before pointer scores existed. Its next analysis scores this pointer.",
    pending: false,
  };
}

export type XrayView = {
  /** True for the doc's illustrative example; every number is then fictional. */
  illustrative: boolean;
  /** A guest preview: the rest of the report waits behind a free account. */
  guest: boolean;
  /** Scores came from the analysis: shown as an AI draft, not reviewed by Dipak. */
  aiDraft: boolean;
  /** Why there are no scores yet (server-told); absent from older servers. */
  scoring?: Scoring;
  overview: {
    summary: Line | null;
    score: { value: number; label: string; line: string } | null;
    stats: {
      duration: Stat | null;
      talk: Stat | null;
      questions: Stat | null;
      longest: Stat | null;
    };
    strength: Line | null;
    improvement: Line | null;
  };
  pointers: Pointer[];
  outcome: {
    kind: OutcomeKind | null;
    /** The analysis' own outcome words when it is not one of the four. */
    label: string | null;
    origin: "person" | "call" | null;
    detail: Line | null;
    value: { amount: string; note: string } | null;
    date: string | null;
    stages: string[];
    reasons: Line[];
    objections: Array<Line & { handled?: boolean }>;
    nextSteps: NextStep[];
    notes: Line[];
    suggested: string | null;
  };
};

/**
 * All points in the 15 Oct doc (owner, 16 Oct: "use ALL the points; the count
 * does not matter"): image6's 23 in its order, then the four only image9 has.
 */
export const POINTERS: ReadonlyArray<{
  id: string;
  name: string;
  evaluates: string;
}> = [
  {
    id: "call_opening",
    name: "Call Opening & First Impression",
    evaluates: "How you introduced yourself and created a positive start.",
  },
  {
    id: "purpose_agenda",
    name: "Purpose & Agenda Setting",
    evaluates: "Whether you set a clear purpose and structure for the call.",
  },
  {
    id: "tone_energy",
    name: "Tone and Energy",
    evaluates: "Your tone, confidence and enthusiasm during the call.",
  },
  {
    id: "active_listening",
    name: "Active Listening",
    evaluates: "Whether you listened without interrupting and showed interest.",
  },
  {
    id: "open_ended_questions",
    name: "Asking Open-Ended Questions",
    evaluates: "Use of open-ended questions to explore the prospect's needs.",
  },
  {
    id: "enough_questions",
    name: "Asking Enough Questions",
    evaluates:
      "Whether you asked enough questions to understand the bigger picture.",
  },
  {
    id: "prospect_role",
    name: "Understanding the Prospect's Role",
    evaluates:
      "How well you understood their role, authority and decision-making power.",
  },
  {
    id: "needs_challenges",
    name: "Identifying Needs and Challenges",
    evaluates: "How deeply you explored their key needs and challenges.",
  },
  {
    id: "current_solution",
    name: "Exploring Current Solution",
    evaluates: "Whether you understood their current solution and gaps.",
  },
  {
    id: "business_impact",
    name: "Quantifying Business Impact",
    evaluates:
      "Whether you explored the impact on revenue, cost, time or resources.",
  },
  {
    id: "decision_process",
    name: "Understanding Decision Process",
    evaluates:
      "How well you explored their decision-making process and timeline.",
  },
  {
    id: "stakeholders",
    name: "Identifying Stakeholders",
    evaluates: "Whether you discussed other people involved in the decision.",
  },
  {
    id: "objections",
    name: "Handling Objections",
    evaluates:
      "How you addressed concerns or objections raised by the prospect.",
  },
  {
    id: "solution_value",
    name: "Positioning Solution Value",
    // Kept distinct from Presenting the Solution (owner: keep all 27).
    evaluates:
      "How clearly you tied the value and results of your solution to their needs.",
  },
  {
    id: "pricing",
    name: "Discussing Pricing",
    evaluates:
      "How confidently and transparently you handled pricing discussions.",
  },
  {
    id: "competition",
    name: "Handling Competition",
    evaluates:
      "How well you positioned your differentiation against competitors.",
  },
  {
    id: "concerns_check",
    name: "Checking for Concerns",
    evaluates:
      "Whether you asked if they had any other concerns before moving forward.",
  },
  {
    id: "next_steps",
    name: "Next Steps",
    evaluates: "How clearly you defined and agreed on the next steps.",
  },
  {
    id: "call_control",
    name: "Call Control",
    evaluates:
      "Whether you kept the conversation focused and avoided tangents.",
  },
  {
    id: "question_talk_ratio",
    name: "Question to Talk Ratio",
    evaluates:
      "The balance between the questions you asked and the time you spoke.",
  },
  {
    id: "handling_silence",
    name: "Handling Silence",
    evaluates: "How well you handled pauses and used them effectively.",
  },
  {
    id: "professionalism",
    name: "Professionalism",
    evaluates: "Your overall professionalism, respect and courtesy.",
  },
  {
    id: "closing_attitude",
    name: "Closing Attitude",
    evaluates: "Your confidence and intent to move the deal forward.",
  },
  {
    id: "building_rapport",
    name: "Building Rapport",
    evaluates:
      "Whether you built rapport and created a comfortable conversation.",
  },
  {
    id: "presenting_solution",
    name: "Presenting the Solution",
    evaluates:
      "Whether you explained what your solution is and how it works, in a clear order.",
  },
  {
    id: "creating_value",
    name: "Creating Value",
    evaluates:
      "Whether you clearly communicated the value and benefits of your solution.",
  },
  {
    id: "overall_communication",
    name: "Overall Communication",
    evaluates:
      "Whether your communication was clear, structured and easy to follow.",
  },
];

/** Every pointer, not yet evaluated: what a call shows until the analysis scores it. */
export function unscoredPointers(): Pointer[] {
  return POINTERS.map((pointer, index) => ({
    ...pointer,
    number: index + 1,
    status: null,
    score: null,
    whatHappened: null,
    whyItMatters: null,
    evidence: [],
    howToImprove: [],
    training: null,
    related: [],
  }));
}

const OUTCOME_KINDS: Partial<Record<OutcomeStatus, OutcomeKind>> = {
  Won: "won",
  Lost: "lost",
  "Follow-up Set": "follow_up",
  "Decision Pending": "decision_pending",
};

export function outcomeKind(status: OutcomeStatus | null): OutcomeKind | null {
  return status ? (OUTCOME_KINDS[status] ?? null) : null;
}

/** "19:30" (or "1:02:05") for a call length. */
export function clock(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return hours
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${pad(minutes)}:${pad(seconds)}`;
}

/** "19 min 30 sec" for the same length, in words. */
export function spelled(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return [
    hours ? `${hours} hr` : null,
    minutes || hours ? `${minutes} min` : null,
    `${seconds} sec`,
  ]
    .filter(Boolean)
    .join(" ");
}

/** The parts of the existing story model this Report reads, for real calls. */
export function outcomeFromStory(model: StoryModel): XrayView["outcome"] {
  const { deal, picture, flow, deeper } = model;
  const outcome = deal.outcome.status ? deal.outcome : picture.outcome;
  const kind = outcomeKind(outcome.status);
  const steps: NextStep[] = [
    ...deal.sellerCommitments.map((line) => ({
      text: line.text,
      date: null,
      owner: "you" as const,
      source: line.sources[0] ?? null,
    })),
    ...deal.prospectCommitments.map((line) => ({
      text: line.text,
      date: null,
      owner: "prospect" as const,
      source: line.sources[0] ?? null,
    })),
  ].sort(
    (a, b) =>
      (a.source?.start_ms ?? Number.MAX_SAFE_INTEGER) -
      (b.source?.start_ms ?? Number.MAX_SAFE_INTEGER),
  );
  if (deal.nextEvent)
    steps.push({
      text: deal.nextEvent.text,
      date: null,
      owner: null,
      source: deal.nextEvent.sources[0] ?? null,
    });
  return {
    kind,
    label: kind ? null : outcome.status,
    origin: outcome.origin,
    detail: outcome.detail ?? deal.position,
    value: null,
    date: null,
    stages: (flow.phases ?? []).map((phase) => phase.label),
    reasons: deal.position ? [deal.position] : [],
    objections: [
      ...(deal.blocker ? [deal.blocker] : []),
      ...deeper.concerns.filter((line) => line.text !== deal.blocker?.text),
    ].slice(0, 4),
    nextSteps: steps.slice(0, 4),
    notes: deeper.decision.likely.slice(0, 3),
    suggested: deal.action,
  };
}
