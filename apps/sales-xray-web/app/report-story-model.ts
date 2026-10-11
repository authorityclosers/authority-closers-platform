import { computeCallMetrics } from "./call-metrics";
import type {
  Finding,
  ReportEvidence,
  SalesReport,
  Transcript,
} from "./report-contract";
import {
  BIG_PICTURE,
  CALL_FLOW,
  DEAL,
  METRIC_LABELS,
  MOMENTS,
  PILLAR_COPY,
  STAGE_LABELS,
  WORKED_DIDNT,
} from "./report-copy";
import type { PillarNote, ReportPillars } from "./report-pillars-contract";
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
  /** Someone's own words: the text is (nearly all of) one of its quotes. */
  quoted?: boolean;
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
  | "Buying Signal"
  | "Important Miss"
  | "Objection"
  | "Price Moment"
  | "Decision Moment"
  | "Trust Moment"
  | "Commitment"
  | "Risk"
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
  /** Price Moment only: the words that named the price, and what came back. */
  priceStated?: Line;
  prospectResponse?: Line;
};

export type Item = {
  title: string;
  what: Line;
  why: Line | null;
  /** The title is the whole sentence; `what` only repeats it (not shown). */
  sentence?: boolean;
  /** What Didn't only: the possible areas left open (spec 3.2). */
  areas?: string[];
};

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
      /** Stage names either side of the switch, when the analysis gives them. */
      beforeLabel?: string | null;
      afterLabel?: string | null;
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
    /** Spec 5, Deep Analysis: the four groups, each only with what we have. */
    discovery: {
      clear: string[];
      unclear: string[];
      openingMissed: Line | null;
    };
    decision: {
      price: Line | null;
      response: Line | null;
      likely: Line[];
      /** What the decision answer may mean, when the analysis lists it. */
      likelyStatus?: string[];
    };
    communication: {
      longest: string | null;
      observation: Line | null;
      listening?: string | null;
    };
    presentation?: {
      relevant: string[];
      lessRelevant: string | null;
      valueConnection: string | null;
    };
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
  /** The optional end strip (spec): short values, each from the report. */
  end: {
    strongest: string | null;
    issue: string | null;
    moment: Moment | null;
    nextEvent: string | null;
  };
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

const MOMENT_PRIORITY: MomentKind[] = [
  "Turning Point",
  "Important Miss",
  "Buying Signal",
  "Strong Moment",
  "Commitment",
  "Decision Moment",
  "Objection",
  "Price Moment",
  "Trust Moment",
  "Risk",
  "Worth Replaying",
];

const normal = (text: string) =>
  text
    .toLowerCase()
    .replace(/[\s\p{P}]+/gu, " ")
    .trim();

/** A line whose text is one of its own quotes says so, so it reads as speech. */
function sourced(text: string, sources: ReportEvidence[]): Line {
  const said = normal(text);
  const quoted = sources.some((source) => {
    const quote = normal(source.quote);
    return (
      quote === said ||
      (said.length > 12 && quote.includes(said)) ||
      (quote.length > 12 &&
        said.includes(quote) &&
        quote.length >= said.length * 0.8)
    );
  });
  return quoted ? { text, sources, quoted } : { text, sources };
}

/**
 * A card title that only repeats the start of its sentence (the same words,
 * or the sentence cut mid-word) becomes the sentence itself, shown once.
 * Same rule as the Document view (G, `sentenceAsTitle`).
 */
function asSentence(item: Item): Item {
  const head = item.title.trim().replace(/[\s.…]+$/u, "");
  const body = item.what.text.trim();
  if (!head || !body.startsWith(head)) return item;
  const rest = body.slice(head.length).replace(/^[\s.]+$/u, "");
  const cut = /^[\p{L}\p{N}]/u.test(rest) || head.length >= 40;
  return !rest || cut
    ? { ...item, title: body.replace(/(?<!\.)\.$/u, ""), sentence: true }
    : item;
}

const words = (text: string) =>
  text
    .toLowerCase()
    .replace(/[\s\p{P}]+/gu, " ")
    .trim()
    .split(" ")
    .filter(Boolean);

/**
 * True when a second paragraph only restates the first: the same text, one
 * inside the other, or the same opening ("You conducted …" twice). The Big
 * Picture then shows one summary, as the spec asks.
 */
function repeats(
  first: string | null | undefined,
  second: string | null | undefined,
) {
  if (!first?.trim() || !second?.trim()) return false;
  const a = words(first);
  const b = words(second);
  const joinedA = a.join(" ");
  const joinedB = b.join(" ");
  if (joinedA.includes(joinedB) || joinedB.includes(joinedA)) return true;
  return a.length > 2 && b.length > 2 && a[0] === b[0] && a[1] === b[1];
}

/** A line that stands alone starts with a capital ("next Tuesday" → "Next Tuesday"). */
const upperFirst = (text: string) =>
  text ? text.charAt(0).toLocaleUpperCase() + text.slice(1) : text;

/**
 * Placeholder notes some sources put where a skill observation belongs; they
 * say nothing about the call, so the Report shows the state and evidence only.
 */
const STOCK_NOTES = new Set([
  "relevant behaviour is evidenced by the cited turn.",
]);
const observationText = (text: string | null | undefined) => {
  const value = clean(text);
  return value && !STOCK_NOTES.has(value.toLowerCase()) ? value : null;
};

/** A spec heading in sentence case, for the one-line gaps. */
const sentence = (heading: string) =>
  heading.charAt(0) + heading.slice(1).toLowerCase();

/** Names of the parts a report can leave out, as the gap line says them. */
const GAP = {
  outcome: BIG_PICTURE.outcome.label,
  summary: BIG_PICTURE.summary.label,
  influence: BIG_PICTURE.influence.label,
  strongest: BIG_PICTURE.strongest.label,
  concern: BIG_PICTURE.concern.label,
  nextStep: BIG_PICTURE.nextStep.label,
  stages: CALL_FLOW.stagesGap,
  change: CALL_FLOW.change.label,
  worked: WORKED_DIDNT.worked.label,
  didnt: WORKED_DIDNT.didnt.label,
  moments: PILLAR_COPY.missed.short,
  blocker: DEAL.blocker.label,
  prospectCommitment: sentence(DEAL.prospectCommitment.heading),
  sellerCommitment: sentence(DEAL.sellerCommitment.heading),
  nextEvent: DEAL.nextEvent.label,
  quality: DEAL.quality.label,
};

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
  // Whole seconds, as the header and player count them (never rounded up).
  const total = Math.max(0, Math.floor(ms / 1000));
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
  // A person's outcome wins. The call's own line stays under it only when it
  // says the same thing; otherwise ("Won" over "wants to think it over") it
  // would contradict the badge, and it still reads in Prospect's position.
  if (recorded)
    return {
      status: recorded.status,
      origin: "person",
      detail:
        line(recorded.note, []) ?? (recorded.status === status ? detail : null),
    };
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
      ? METRIC_LABELS.youProspect
      : ordered.length === 2
        ? METRIC_LABELS.speakers
        : null;
  const metrics: Metric[] = [
    {
      label: METRIC_LABELS.callLength,
      value: formatDuration(transcript.duration_ms),
    },
  ];
  if (ordered.length === 2 && names) {
    const shares = ordered.map((id) =>
      Math.round((measured.speakers[id].talk_share ?? 0) * 100),
    );
    metrics.push({
      label: METRIC_LABELS.talkShare,
      value: `${shares[0]} : ${shares[1]}`,
      note: names,
    });
    metrics.push({
      label: METRIC_LABELS.questions,
      value: `${measured.speakers[ordered[0]].questions} : ${measured.speakers[ordered[1]].questions}`,
      note: names,
    });
  }
  // With confirmed roles this is the seller's own longest turn (spec 2.1).
  const seller =
    roles?.seller && ids.includes(roles.seller) ? roles.seller : null;
  const longest = seller
    ? measured.speakers[seller].longest_monologue_ms
    : Math.max(
        0,
        ...ids.map((id) => measured.speakers[id].longest_monologue_ms),
      );
  if (longest > 0)
    metrics.push({
      label: seller
        ? METRIC_LABELS.longestSellerTurn
        : METRIC_LABELS.longestTurn,
      value: formatDuration(longest),
    });
  metrics.push({
    label: METRIC_LABELS.talkOvers,
    value: String(measured.cut_ins.length),
  });
  return metrics;
}

function phasesFor(report: SalesReport, durationMs: number | undefined) {
  const phases = report.story?.phases;
  if (!phases?.length || !durationMs) return null;
  return phases.map((phase, index) => ({
    label: STAGE_LABELS[phase.name],
    start_ms: phase.start_ms,
    end_ms: phases[index + 1]?.start_ms ?? durationMs,
  }));
}

function momentsFor(
  report: SalesReport,
  transcript: Transcript | undefined,
  roles?: { seller?: string | null; prospect?: string | null },
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
      title: MOMENTS.titleTurn,
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
      movedToward: clean(missed.closer_response.text)
        ? sourced(
            missed.closer_response.text.trim(),
            missed.closer_response.evidence,
          )
        : undefined,
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
          ? MOMENTS.titleNextStep
          : MOMENTS.titleEnding,
      source: closing,
      why: line(outcome?.text ?? report.story?.next_step?.text, []),
    });
  if (transcript?.segments.length) {
    const measured = computeCallMetrics(
      transcript.segments,
      transcript.duration_ms,
    );
    const price = priceExchange(transcript, measured.price_moments, roles);
    if (price)
      add({
        kind: "Price Moment",
        title: MOMENTS.titlePrice,
        source: price.stated.sources[0],
        why: null,
        ...(price.attributed
          ? {
              priceStated: price.stated,
              prospectResponse: price.response ?? undefined,
            }
          : {}),
      });
  }
  // "Watch this again" clips are Coaching material; only the ones to repeat
  // are moments of this call (Dipak's labels have no "Worth Replaying").
  for (const item of overview?.rewatch ?? []) {
    const source = item.evidence[0];
    if (source && item.purpose === "repeat")
      add({
        kind: "Strong Moment",
        title: item.text,
        source,
        why: null,
      });
  }
  return moments;
}

/** A line that names an amount: digits, or a currency or amount word. */
const FIGURE =
  /([0-9०-९][0-9०-९,.]*|₹|\$|€|£|\brs\.?|\brupees?\b|\blakhs?\b|\blacs?\b|\bcrores?\b|\bdollars?\b|लाख|रुपये|रुपए|हजार|हज़ार)/iu;

/**
 * The words that named a price, and what the prospect said back. With known
 * roles the price is the seller's first line naming an amount, at or just
 * after a moment where money came up; the response is the prospect's next
 * line. A figure only the prospect names is their budget, not a price. With
 * roles unknown nobody can say who quoted what: the moment keeps its quote
 * and no "Price stated" is claimed.
 */
function priceExchange(
  transcript: Transcript,
  moments: { segment_id: string }[],
  roles?: { seller?: string | null; prospect?: string | null },
): { stated: Line; response: Line | null; attributed: boolean } | null {
  const segments = transcript.segments;
  const starts = moments
    .map((moment) => segments.findIndex((s) => s.id === moment.segment_id))
    .filter((index) => index >= 0);
  if (!starts.length) return null;
  const evidence = (s: Transcript["segments"][number]): ReportEvidence => ({
    segment_id: s.id,
    quote: s.text,
    start_ms: s.start_ms,
    end_ms: s.end_ms,
  });
  const seller = roles?.seller ?? null;
  const prospect = roles?.prospect ?? null;
  if (!seller || !prospect) {
    const first = segments[starts[0]];
    return {
      stated: { text: first.text, sources: [evidence(first)] },
      response: null,
      attributed: false,
    };
  }
  let at = -1;
  for (const start of starts) {
    for (
      let index = start;
      index < Math.min(segments.length, start + 5);
      index++
    )
      if (
        segments[index].speaker_id === seller &&
        FIGURE.test(segments[index].text)
      ) {
        at = index;
        break;
      }
    if (at >= 0) break;
  }
  if (at < 0) return null;
  const segment = segments[at];
  const reply = segments
    .slice(at + 1, at + 5)
    .find((s) => s.speaker_id === prospect);
  return {
    stated: { text: segment.text, sources: [evidence(segment)] },
    response: reply ? { text: reply.text, sources: [evidence(reply)] } : null,
    attributed: true,
  };
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

const findings = (list: Finding[] | null | undefined): Finding[] =>
  (Array.isArray(list) ? list : [])
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      ...item,
      title: item.title ?? "",
      explanation: item.explanation ?? "",
      evidence: Array.isArray(item.evidence) ? item.evidence : [],
    }));

/**
 * Lists default to empty and findings always carry an evidence list, so a
 * report from any era opens; missing parts become honest gaps.
 */
function normalized(report: SalesReport): SalesReport {
  const overview = report.overview;
  return {
    ...report,
    strengths: findings(report.strengths),
    improvements: findings(report.improvements),
    missed_opportunities: findings(report.missed_opportunities),
    objection_analysis: findings(report.objection_analysis),
    closing_analysis: findings(report.closing_analysis),
    dimensions: Array.isArray(report.dimensions) ? report.dimensions : [],
    overview: overview
      ? {
          ...overview,
          strength_details: overview.strength_details ?? [],
          improvement_details: overview.improvement_details ?? [],
          golden_moments: overview.golden_moments ?? [],
          missed_details: overview.missed_details ?? [],
          prospect_interpretations: overview.prospect_interpretations ?? [],
          rewatch: overview.rewatch ?? [],
          final_assessment: overview.final_assessment ?? {
            repeat: "",
            fix_first: "",
            next_focus: "",
            assessment: "",
          },
        }
      : undefined,
  };
}

/** Builds every pillar from one saved report; older reports simply say less. */
export function reportStoryModel(
  input: SalesReport,
  transcript?: Transcript,
  options: {
    roles?: { seller?: string | null; prospect?: string | null };
    recorded?: { status: OutcomeStatus; note?: string | null } | null;
  } = {},
): StoryModel {
  const report = normalized(input);
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
    assessment: repeats(report.summary, overview?.final_assessment.assessment)
      ? null
      : clean(overview?.final_assessment.assessment),
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
          before: sourced(change.before.text, change.before.evidence),
          turn: sourced(change.change.text, change.change.evidence),
          after: sourced(change.after.text, change.after.evidence),
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

  const moments = momentsFor(report, transcript, options.roles);

  const skills = REPORT_SKILLS.map(([id, label]): SkillRow => {
    const dimension = report.dimensions.find((d) => d.dimension_id === id);
    const state = dimension ? skillState(dimension) : null;
    return {
      id,
      label,
      short: SKILL_SHORT[id] ?? label,
      state,
      observation:
        state && dimension ? observationText(dimension.observation) : null,
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
  const priceMoment = moments.find((m) => m.kind === "Price Moment");
  const firstMiss = overview?.missed_details[0];
  const communication = report.dimensions.find(
    (d) => d.dimension_id === "communication_tonality",
  );
  const longestMetric = flow.metrics.find((m) => /^Longest/.test(m.label));
  const deeper = {
    unclear,
    concerns,
    findings: [...report.objection_analysis, ...report.closing_analysis].map(
      (finding) => findingItem(finding, null, false),
    ),
    discovery: {
      clear: [] as string[],
      unclear,
      openingMissed: firstMiss
        ? line(
            firstMiss.prospect_signal.text,
            firstMiss.prospect_signal.evidence,
          )
        : null,
    },
    decision: {
      price: priceMoment?.priceStated ?? null,
      response: priceMoment?.prospectResponse ?? null,
      likely: concerns,
    },
    communication: {
      longest: longestMetric?.value ?? null,
      observation:
        communication && skillState(communication)
          ? line(
              observationText(communication.observation),
              communication.evidence,
            )
          : null,
    },
  };

  const rung = story?.outcome.next_step_rung;
  const deal = {
    outcome,
    // Where the prospect stands is what the call heard, whoever set the status.
    position: callOutcome(report).detail,
    blocker: concerns[0] ?? null,
    prospectCommitments: (story?.prospect_commitments ?? []).map((note) => ({
      text: note.text,
      sources: note.evidence,
    })),
    sellerCommitments: (story?.seller_commitments ?? []).map((note) => ({
      text: [note.text, note.due_text].filter(Boolean).join(" · "),
      sources: note.evidence,
    })),
    nextEvent:
      story?.outcome.next_step_when && story.outcome.evidence.length
        ? {
            text: upperFirst(story.outcome.next_step_when),
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
      // The outcome badge always says when no outcome is set.
      !picture.summary && GAP.summary,
      !picture.influence && GAP.influence,
      !strongest && GAP.strongest,
      !concern && GAP.concern,
      !nextStep && GAP.nextStep,
    ].filter((v): v is string => Boolean(v)),
    [!flow.phases && GAP.stages, !flow.change && GAP.change].filter(
      (v): v is string => Boolean(v),
    ),
    [!worked.length && GAP.worked, !didnt.length && GAP.didnt].filter(
      (v): v is string => Boolean(v),
    ),
    moments.length ? [] : [GAP.moments],
    // Each skill row already says "Not covered" when it is.
    [],
    [
      !deal.blocker && GAP.blocker,
      !deal.prospectCommitments.length && GAP.prospectCommitment,
      !deal.sellerCommitments.length && GAP.sellerCommitment,
      !deal.nextEvent && GAP.nextEvent,
      !deal.quality && GAP.quality,
    ].filter((v): v is string => Boolean(v)),
  ];

  const top = topMoments(moments);
  const end = {
    strongest: worked[0]?.title ?? null,
    issue: didnt[0]?.title ?? null,
    moment: top.find((m) => m.kind === "Turning Point") ?? top[0] ?? null,
    nextEvent: deal.nextEvent?.text ?? null,
  };

  const model: StoryModel = {
    picture,
    flow,
    worked: worked.map(asSentence),
    didnt: didnt.map(asSentence),
    moments,
    topMoments: top,
    skills,
    deeper,
    deal,
    missing,
    end,
  };
  return report.pillars
    ? withPillars(
        model,
        report.pillars,
        transcript?.duration_ms,
        options.recorded,
      )
    : model;
}

const note = (value: PillarNote | null | undefined, inferred = false) =>
  value ? line(value.text, value.evidence, inferred) : null;

/**
 * The analysis' own pillar words (report-pillars/1) replace what the Report
 * would otherwise derive, part by part; anything it leaves out keeps the
 * derived value, so older and newer reports read the same way.
 */
function withPillars(
  base: StoryModel,
  p: ReportPillars,
  durationMs: number | undefined,
  recorded: { status: OutcomeStatus; note?: string | null } | null | undefined,
): StoryModel {
  const outcome: Outcome =
    !recorded && p.outcome
      ? {
          status: p.outcome.status,
          origin: "call",
          detail:
            line(p.outcome.line, p.outcome.evidence) ??
            base.picture.outcome.detail,
        }
      : base.picture.outcome;
  const nextStep = note(p.next_step) ?? base.picture.nextStep;
  const picture = {
    ...base.picture,
    outcome,
    summary: p.summary
      ? p.summary === base.picture.summary?.text
        ? base.picture.summary
        : { text: p.summary, sources: [] }
      : base.picture.summary,
    // The supplied summary is already the three to five sentences.
    assessment: p.summary ? null : base.picture.assessment,
    influence: note(p.biggest_influence) ?? base.picture.influence,
    strongest: note(p.strongest_part) ?? base.picture.strongest,
    concern: note(p.biggest_concern) ?? base.picture.concern,
    nextStep,
  };

  const phases =
    p.timeline && durationMs
      ? p.timeline
          .filter((stage) => stage.start_ms < durationMs)
          .map((stage, index, all) => ({
            label: stage.label,
            start_ms: stage.start_ms,
            end_ms: all[index + 1]?.start_ms ?? durationMs,
          }))
      : null;
  const change = p.key_change
    ? {
        before: { text: p.key_change.before.text, sources: [] },
        turn: { text: p.key_change.text, sources: p.key_change.evidence },
        after: { text: p.key_change.after.text, sources: [] },
        effect: null,
        beforeLabel: p.key_change.before.label,
        afterLabel: p.key_change.after.label,
      }
    : base.flow.change;
  const flow = {
    ...base.flow,
    phases: phases?.length ? phases : base.flow.phases,
    change,
  };

  const worked = p.worked?.length
    ? p.worked.map((item) =>
        asSentence({
          title: item.title,
          what: { text: item.what, sources: item.evidence.slice(0, 1) },
          why: line(item.why_it_helped, []),
        }),
      )
    : base.worked;
  const didnt = p.didnt?.length
    ? p.didnt.map((item) =>
        asSentence({
          title: item.title,
          what: { text: item.what, sources: item.evidence.slice(0, 1) },
          why: line(item.what_it_affected, []),
          areas: item.possible_areas,
        }),
      )
    : base.didnt;

  let moments = base.moments;
  let top = base.topMoments;
  let keyMoment = base.end.moment;
  if (p.moments?.length) {
    // Supplied in order of importance: the first five are the key moments.
    moments = p.moments.map((item, index) => ({
      key: `pillar-${index}-${evidenceKey(item.evidence[0])}`,
      kind: item.kind,
      title: item.title,
      source: item.evidence[0],
      why: line(item.why, []),
      movedToward: line(item.moved_toward, []) ?? undefined,
      couldExplore: item.what_was_missed ?? undefined,
      priceStated: note(item.price_stated) ?? undefined,
      prospectResponse: note(item.prospect_response) ?? undefined,
    }));
    top = moments
      .slice(0, 5)
      .sort((a, b) => a.source.start_ms - b.source.start_ms);
    keyMoment =
      p.most_important_moment !== undefined
        ? moments[p.most_important_moment]
        : (top.find((m) => m.kind === "Turning Point") ?? moments[0]);
  }

  const d = p.deeper;
  const deeper = d
    ? {
        ...base.deeper,
        discovery: {
          clear: d.became_clear,
          unclear: d.still_unclear.length
            ? d.still_unclear
            : base.deeper.discovery.unclear,
          openingMissed:
            note(d.opening_missed) ?? base.deeper.discovery.openingMissed,
        },
        decision: {
          price: note(d.price) ?? base.deeper.decision.price,
          response: note(d.prospect_response) ?? base.deeper.decision.response,
          likely: base.deeper.decision.likely,
          likelyStatus: d.likely_status,
        },
        communication: {
          ...base.deeper.communication,
          listening: d.listening,
          observation:
            note(d.communication_note) ?? base.deeper.communication.observation,
        },
        presentation:
          d.relevant.length || d.less_relevant || d.value_connection
            ? {
                relevant: d.relevant,
                lessRelevant: d.less_relevant,
                valueConnection: d.value_connection,
              }
            : undefined,
      }
    : base.deeper;

  const pd = p.deal;
  const nextEvent = pd?.next_event
    ? {
        text: upperFirst(pd.next_event.when ?? pd.next_event.text),
        sources: pd.next_event.evidence,
      }
    : p.next_step?.when
      ? { text: upperFirst(p.next_step.when), sources: p.next_step.evidence }
      : base.deal.nextEvent;
  const deal = {
    ...base.deal,
    outcome,
    position: note(pd?.position) ?? base.deal.position,
    blocker: pd?.blocker
      ? note(pd.blocker, pd.blocker.basis === "inferred")
      : base.deal.blocker,
    prospectCommitments: pd?.prospect_commitments.length
      ? pd.prospect_commitments.map((item) => note(item)!)
      : base.deal.prospectCommitments,
    sellerCommitments: pd?.seller_commitments.length
      ? pd.seller_commitments.map((item) => note(item)!)
      : base.deal.sellerCommitments,
    nextEvent,
    quality: pd?.commitment_quality ?? base.deal.quality,
    unclear: pd?.still_unclear.length ? pd.still_unclear : base.deal.unclear,
    action: pd?.deal_action ?? base.deal.action,
    coachingMission: pd?.coaching_mission ?? base.deal.coachingMission,
  };

  const missing = base.missing.map((list) => [
    ...list,
  ]) as StoryModel["missing"];
  const drop = (index: number, name: string, has: unknown) => {
    if (has) missing[index] = missing[index].filter((item) => item !== name);
  };
  drop(0, GAP.summary, picture.summary);
  drop(0, GAP.influence, picture.influence);
  drop(0, GAP.strongest, picture.strongest);
  drop(0, GAP.concern, picture.concern);
  drop(0, GAP.nextStep, picture.nextStep);
  drop(1, GAP.stages, flow.phases);
  drop(1, GAP.change, flow.change);
  drop(2, GAP.worked, worked.length);
  drop(2, GAP.didnt, didnt.length);
  drop(3, GAP.moments, moments.length);
  drop(5, GAP.blocker, deal.blocker);
  drop(5, GAP.prospectCommitment, deal.prospectCommitments.length);
  drop(5, GAP.sellerCommitment, deal.sellerCommitments.length);
  drop(5, GAP.nextEvent, deal.nextEvent);
  drop(5, GAP.quality, deal.quality);

  return {
    ...base,
    picture,
    flow,
    worked,
    didnt,
    moments,
    topMoments: top,
    deeper,
    deal,
    missing,
    end: {
      strongest: p.strongest_part?.short ?? worked[0]?.title ?? null,
      issue: p.biggest_concern?.short ?? didnt[0]?.title ?? null,
      moment: keyMoment,
      nextEvent: nextEvent?.text ?? null,
    },
  };
}
