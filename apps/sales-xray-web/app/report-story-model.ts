import { computeCallMetrics } from "./call-metrics";
import type {
  Finding,
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import { REPORT_SKILLS } from "./report-pillars";

/**
 * The Report as one story (binding spec, 9 Oct, section 1): six pillars built
 * only from what this call's analysis already says. Nothing here is written by
 * the browser: every sentence is a C5 field or a fixed label, every play link
 * is a C5 quote, and a missing field is listed, never filled in.
 */

export type Line = {
  text: string;
  sources: ReportEvidence[];
  /** The analysis offers this as a possibility, not an established fact. */
  inferred?: boolean;
};

export const OUTCOME_STATUSES = [
  "Won",
  "Lost",
  "Follow-up Set",
  "Decision Pending",
  "Deferred",
  "Meeting Booked",
  "Disqualified",
  "No Clear Next Step",
  "Still Open",
] as const;
export type OutcomeStatus = (typeof OUTCOME_STATUSES)[number];

export type Outcome = {
  /** Won and Lost only ever come from a person, never from the analysis. */
  status: OutcomeStatus | null;
  origin: "person" | "call" | null;
  detail: Line | null;
};

export type SkillState =
  | "Strongly Demonstrated"
  | "Observed"
  | "Needs Attention"
  | "Not Enough Evidence"
  | "Not Applicable";

export type MomentKind =
  | "Strong Moment"
  | "Turning Point"
  | "Important Miss"
  | "Objection"
  | "Price Moment"
  | "Decision Moment"
  | "Commitment"
  | "Worth Replaying";

export type Moment = {
  key: string;
  kind: MomentKind;
  title: string;
  source: ReportEvidence;
  why: Line | null;
  /** Important Miss only: what the seller did instead, and the open question. */
  movedToward?: Line;
  couldExplore?: string;
};

export type Item = { title: string; what: Line; why: Line | null };

export type SkillRow = {
  id: string;
  label: string;
  short: string;
  state: SkillState | null;
  observation: string | null;
  sources: ReportEvidence[];
};

export type Phase = { label: string; start_ms: number; end_ms: number };

export type Metric = { label: string; value: string; note?: string };

export type StoryModel = {
  picture: {
    outcome: Outcome;
    summary: Line | null;
    assessment: string | null;
    influence: Line | null;
    strongest: Line | null;
    concern: Line | null;
    nextStep: Line | null;
  };
  flow: {
    metrics: Metric[];
    phases: Phase[] | null;
    change: {
      before: Line;
      turn: Line;
      after: Line;
      effect: string | null;
    } | null;
  };
  worked: Item[];
  didnt: Item[];
  moments: Moment[];
  /** Moments shown before "View all", by importance, then in call order. */
  topMoments: Moment[];
  skills: SkillRow[];
  deeper: {
    unclear: string[];
    concerns: Line[];
    findings: Item[];
  };
  deal: {
    outcome: Outcome;
    position: Line | null;
    blocker: Line | null;
    prospectCommitments: Line[];
    sellerCommitments: Line[];
    nextEvent: Line | null;
    quality: "Clear" | "Soft" | "Unclear" | null;
    unclear: string[];
    action: string | null;
    coachingMission: string | null;
  };
  /** Per pillar, what this report does not establish (shown as one line). */
  missing: [string[], string[], string[], string[], string[], string[]];
};

const SKILL_SHORT: Record<string, string> = {
  human_connection_trust: "Human Connection & Trust",
  discovery_deep_understanding: "Discovery",
  qualification: "Qualification",
  problem_impact_desire: "Problem / Impact / Desire",
  solution_relevance_presentation: "Presentation & Value",
  certainty_objection_intelligence: "Objection Intelligence",
  closing_decision_management: "Closing",
  communication_tonality: "Communication",
};

const CALL_STATE: Record<string, SkillState> = {
  strongly_demonstrated: "Strongly Demonstrated",
  observed: "Observed",
  needs_attention: "Needs Attention",
  insufficient_evidence: "Not Enough Evidence",
  not_applicable: "Not Applicable",
};

const PHASE_LABELS = {
  opening: "Opening",
  discovery: "Discovery",
  pitch: "Offer discussion",
  objection: "Concerns",
  close: "Decision discussion",
} as const;

const MOMENT_PRIORITY: MomentKind[] = [
  "Turning Point",
  "Important Miss",
  "Strong Moment",
  "Commitment",
  "Decision Moment",
  "Objection",
  "Price Moment",
  "Worth Replaying",
];

const clean = (value: string | null | undefined) => {
  const text = value?.trim();
  return text ? text : null;
};

const line = (
  text: string | null | undefined,
  sources: ReportEvidence[] | undefined,
  inferred = false,
): Line | null => {
  const value = clean(text);
  return value
    ? { text: value, sources: sources ?? [], ...(inferred ? { inferred } : {}) }
    : null;
};

export function formatDuration(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(seconds).padStart(2, "0");
  return hours ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** What the analysis heard about how the call ended. Won/Lost stay human. */
export function callOutcome(
  report: SalesReport,
  recorded?: { status: OutcomeStatus; note?: string | null } | null,
): Outcome {
  const overview = report.overview?.outcome ?? null;
  const story = report.story?.outcome ?? null;
  const detail =
    line(overview?.text, overview?.evidence) ??
    line(report.story?.next_step?.text, report.story?.next_step?.evidence);
  if (recorded)
    return {
      status: recorded.status,
      origin: "person",
      detail: line(recorded.note, []) ?? detail,
    };
  let status: OutcomeStatus | null = null;
  if (story) {
    if (story.kind === "follow_up") status = "Follow-up Set";
    else if (story.kind === "disqualified") status = "Disqualified";
    else if (story.kind === "none")
      status =
        story.next_step_rung === "none" || story.next_step_rung === "vague"
          ? "No Clear Next Step"
          : "Follow-up Set";
  }
  if (!status && overview) {
    status =
      overview.kind === "follow_up"
        ? "Follow-up Set"
        : overview.kind === "future_date"
          ? "Deferred"
          : overview.kind === "disqualified"
            ? "Disqualified"
            : overview.kind === "unclear"
              ? "No Clear Next Step"
              : null; // closed / no_sale: only a person records Won or Lost.
  }
  return { status, origin: status ? "call" : null, detail };
}

function evidenceKey(source: ReportEvidence) {
  return `${source.segment_id}:${source.start_ms}`;
}

function findingItem(
  finding: Finding,
  why: string | null | undefined,
  inferredWhy: boolean,
): Item {
  return {
    title: finding.title,
    what: {
      text: finding.explanation,
      sources: finding.evidence.slice(0, 1),
    },
    why: line(why, [], inferredWhy),
  };
}

function skillState(
  dimension: SalesReport["dimensions"][number],
): SkillState | null {
  if (dimension.call_state) return CALL_STATE[dimension.call_state] ?? null;
  if (dimension.status === "observed" && dimension.evidence?.length)
    return "Observed";
  if (dimension.status === "insufficient_evidence")
    return "Not Enough Evidence";
  if (dimension.status === "not_applicable") return "Not Applicable";
  return null;
}

function metricsFor(
  transcript: Transcript | undefined,
  roles: { seller?: string | null; prospect?: string | null } | undefined,
): Metric[] {
  if (!transcript?.segments.length) return [];
  const measured = computeCallMetrics(
    transcript.segments,
    transcript.duration_ms,
  );
  const ids = Object.keys(measured.speakers).sort(
    (a, b) => measured.speakers[b].talk_ms - measured.speakers[a].talk_ms,
  );
  const ordered =
    roles?.seller && roles.prospect && ids.includes(roles.seller)
      ? [roles.seller, roles.prospect].filter((id) => ids.includes(id))
      : ids.slice(0, 2);
  const names =
    roles?.seller && roles.prospect && ordered[0] === roles.seller
      ? "You : Prospect"
      : ordered.length === 2
        ? "Speaker 1 : Speaker 2"
        : null;
  const metrics: Metric[] = [
    { label: "Call length", value: formatDuration(transcript.duration_ms) },
  ];
  if (ordered.length === 2 && names) {
    const shares = ordered.map((id) =>
      Math.round((measured.speakers[id].talk_share ?? 0) * 100),
    );
    metrics.push({
      label: "Talk share",
      value: `${shares[0]} : ${shares[1]}`,
      note: names,
    });
    metrics.push({
      label: "Questions asked",
      value: `${measured.speakers[ordered[0]].questions} : ${measured.speakers[ordered[1]].questions}`,
      note: names,
    });
  }
  const longest = Math.max(
    0,
    ...ids.map((id) => measured.speakers[id].longest_monologue_ms),
  );
  if (longest > 0)
    metrics.push({ label: "Longest turn", value: formatDuration(longest) });
  metrics.push({
    label: "Talk-overs",
    value: String(measured.cut_ins.length),
  });
  return metrics;
}

function phasesFor(report: SalesReport, durationMs: number | undefined) {
  const phases = report.story?.phases;
  if (!phases?.length || !durationMs) return null;
  return phases.map((phase, index) => ({
    label: PHASE_LABELS[phase.name],
    start_ms: phase.start_ms,
    end_ms: phases[index + 1]?.start_ms ?? durationMs,
  }));
}

function momentsFor(
  report: SalesReport,
  transcript: Transcript | undefined,
): Moment[] {
  const overview = report.overview;
  const moments: Moment[] = [];
  const seen = new Set<string>();
  const add = (moment: Omit<Moment, "key">) => {
    const key = evidenceKey(moment.source);
    if (seen.has(key)) return;
    seen.add(key);
    moments.push({ ...moment, key });
  };
  const change = overview?.conversation_change;
  if (change?.change.evidence[0])
    add({
      kind: "Turning Point",
      title: "The conversation changed here",
      source: change.change.evidence[0],
      why: line(change.possible_effect, [], true),
    });
  for (const missed of overview?.missed_details ?? []) {
    const finding = report.missed_opportunities[missed.finding_index];
    const source = missed.prospect_signal.evidence[0];
    if (!finding || !source) continue;
    add({
      kind: "Important Miss",
      title: finding.title,
      source,
      why: line(missed.potential_impact, [], true),
      movedToward:
        line(missed.closer_response.text, missed.closer_response.evidence) ??
        undefined,
      couldExplore: clean(missed.follow_up) ?? undefined,
    });
  }
  for (const golden of overview?.golden_moments ?? []) {
    const finding = report.strengths[golden.strength_index];
    const source = finding?.evidence[golden.evidence_index];
    if (!finding || !source) continue;
    add({
      kind: "Strong Moment",
      title: finding.title,
      source,
      why: line(golden.why_effective, [], true),
    });
  }
  for (const finding of report.objection_analysis) {
    const source = finding.evidence[0];
    if (source)
      add({
        kind: "Objection",
        title: finding.title,
        source,
        why: line(finding.explanation, []),
      });
  }
  const outcome = overview?.outcome;
  const closing = outcome?.evidence.at(-1) ?? report.story?.outcome.evidence[0];
  if (closing)
    add({
      kind:
        outcome?.kind === "follow_up" ||
        outcome?.kind === "future_date" ||
        report.story?.outcome.kind === "follow_up"
          ? "Commitment"
          : "Decision Moment",
      title:
        outcome?.kind === "follow_up" ||
        report.story?.outcome.kind === "follow_up"
          ? "A next step was agreed"
          : "How the call ended",
      source: closing,
      why: line(outcome?.text ?? report.story?.next_step?.text, []),
    });
  if (transcript?.segments.length) {
    const measured = computeCallMetrics(
      transcript.segments,
      transcript.duration_ms,
    );
    const price = measured.price_moments[0];
    const segment = price
      ? transcript.segments.find((item) => item.id === price.segment_id)
      : null;
    if (segment)
      add({
        kind: "Price Moment",
        title: "Price or money came up",
        source: {
          segment_id: segment.id,
          quote: segment.text,
          start_ms: segment.start_ms,
          end_ms: segment.end_ms,
        },
        why: null,
      });
  }
  for (const item of overview?.rewatch ?? []) {
    const source = item.evidence[0];
    if (source)
      add({
        kind: item.purpose === "repeat" ? "Strong Moment" : "Worth Replaying",
        title: item.text,
        source,
        why: null,
      });
  }
  return moments;
}

function topMoments(moments: Moment[], limit = 5) {
  const ranked = [...moments].sort(
    (a, b) =>
      MOMENT_PRIORITY.indexOf(a.kind) - MOMENT_PRIORITY.indexOf(b.kind) ||
      a.source.start_ms - b.source.start_ms,
  );
  return ranked
    .slice(0, limit)
    .sort((a, b) => a.source.start_ms - b.source.start_ms);
}

function missingInputs(report: SalesReport) {
  const overview = report.overview;
  const items: string[] = [];
  const add = (impact: unknown) => {
    if (
      impact &&
      typeof impact === "object" &&
      "status" in impact &&
      impact.status === "insufficient_data" &&
      "missing_inputs" in impact &&
      Array.isArray(impact.missing_inputs)
    )
      for (const input of impact.missing_inputs)
        if (typeof input === "string" && clean(input)) items.push(input.trim());
  };
  add(overview?.business_impact);
  for (const detail of overview?.improvement_details ?? [])
    add(detail.business_impact);
  return [...new Set(items)].slice(0, 6);
}

/** Builds every pillar from one saved report; older reports simply say less. */
export function reportStoryModel(
  report: SalesReport,
  transcript?: Transcript,
  options: {
    roles?: { seller?: string | null; prospect?: string | null };
    recorded?: { status: OutcomeStatus; note?: string | null } | null;
  } = {},
): StoryModel {
  const overview = report.overview;
  const story = report.story;
  const outcome = callOutcome(report, options.recorded);

  const strength = report.strengths.find((item) => item.evidence.length);
  const concernIndex = overview?.next_call_focus?.improvement_index ?? 0;
  const concernFinding =
    report.improvements[concernIndex] ?? report.improvements[0];
  const strongest = strength
    ? line(strength.explanation, strength.evidence.slice(0, 1))
    : null;
  const concern = concernFinding
    ? line(concernFinding.explanation, concernFinding.evidence.slice(0, 1))
    : null;
  const outcomeLeadsOn =
    overview?.outcome?.kind === "follow_up" ||
    overview?.outcome?.kind === "future_date";
  const nextStep =
    line(story?.next_step?.text, story?.next_step?.evidence) ??
    (outcomeLeadsOn ? outcome.detail : null);

  const picture = {
    outcome,
    summary: line(report.summary, report.summary_evidence),
    assessment: clean(overview?.final_assessment.assessment),
    influence: line(overview?.diagnosis?.text, overview?.diagnosis?.evidence),
    strongest,
    concern,
    nextStep,
  };

  const change = overview?.conversation_change;
  const flow = {
    metrics: metricsFor(transcript, options.roles),
    phases: phasesFor(report, transcript?.duration_ms),
    change: change
      ? {
          before: { text: change.before.text, sources: change.before.evidence },
          turn: { text: change.change.text, sources: change.change.evidence },
          after: { text: change.after.text, sources: change.after.evidence },
          effect: clean(change.possible_effect),
        }
      : null,
  };

  const worked = report.strengths
    .slice(0, 5)
    .map((finding, index) =>
      findingItem(
        finding,
        overview?.strength_details.find((d) => d.finding_index === index)
          ?.why_it_matters,
        true,
      ),
    );
  const didnt = report.improvements.slice(0, 3).map((finding, index) => {
    const detail = overview?.improvement_details.find(
      (d) => d.finding_index === index,
    );
    const item = findingItem(finding, detail?.why_it_matters, true);
    // The separate call observation, when supplied, is the better play link.
    const observed = detail?.what_happened.evidence.slice(0, 1);
    return observed?.length
      ? { ...item, what: { ...item.what, sources: observed } }
      : item;
  });

  const moments = momentsFor(report, transcript);

  const skills = REPORT_SKILLS.map(([id, label]): SkillRow => {
    const dimension = report.dimensions.find((d) => d.dimension_id === id);
    const state = dimension ? skillState(dimension) : null;
    return {
      id,
      label,
      short: SKILL_SHORT[id] ?? label,
      state,
      observation: state && dimension ? clean(dimension.observation) : null,
      sources: state ? (dimension?.evidence ?? []) : [],
    };
  });

  const unclear = missingInputs(report);
  const concerns = (overview?.prospect_interpretations ?? []).map(
    (item): Line => ({
      text: item.possible_concern,
      sources: item.source.evidence,
      inferred: true,
    }),
  );
  const deeper = {
    unclear,
    concerns,
    findings: [...report.objection_analysis, ...report.closing_analysis].map(
      (finding) => findingItem(finding, null, false),
    ),
  };

  const rung = story?.outcome.next_step_rung;
  const deal = {
    outcome,
    position: outcome.detail,
    blocker: concerns[0] ?? null,
    prospectCommitments: [
      ...(story?.prospect_commitments ?? []),
      ...(story?.prospect_tasks ?? []),
    ].map((note) => ({ text: note.text, sources: note.evidence })),
    sellerCommitments: (story?.seller_commitments ?? []).map((note) => ({
      text: [note.text, note.due_text].filter(Boolean).join(" · "),
      sources: note.evidence,
    })),
    nextEvent:
      story?.outcome.next_step_when && story.outcome.evidence.length
        ? {
            text: story.outcome.next_step_when,
            sources: story.outcome.evidence,
          }
        : null,
    quality:
      rung === "dated_call" || rung === "committed" || rung === "invite_sent"
        ? ("Clear" as const)
        : rung === "vague"
          ? ("Soft" as const)
          : rung === "none"
            ? ("Unclear" as const)
            : null,
    unclear,
    action: clean(overview?.final_assessment.next_focus),
    coachingMission: clean(overview?.next_call_focus?.behavior),
  };

  const missing: StoryModel["missing"] = [
    [
      !outcome.status && "Call outcome",
      !picture.summary && "Summary",
      !picture.influence && "What most affected this call",
      !strongest && "Strongest part",
      !concern && "Biggest concern",
      !nextStep && "Next agreed step",
    ].filter((v): v is string => Boolean(v)),
    [
      !flow.phases && "Conversation stages",
      !flow.change && "Key change",
    ].filter((v): v is string => Boolean(v)),
    [!worked.length && "What worked", !didnt.length && "What didn't"].filter(
      (v): v is string => Boolean(v),
    ),
    moments.length ? [] : ["Moments"],
    skills.filter((s) => !s.state).map((s) => s.short),
    [
      !deal.blocker && "Current blocker",
      !deal.prospectCommitments.length && "Prospect commitment",
      !deal.sellerCommitments.length && "Seller commitment",
      !deal.nextEvent && "Next event date",
      !deal.quality && "Commitment quality",
    ].filter((v): v is string => Boolean(v)),
  ];

  return {
    picture,
    flow,
    worked,
    didnt,
    moments,
    topMoments: topMoments(moments),
    skills,
    deeper,
    deal,
    missing,
  };
}
