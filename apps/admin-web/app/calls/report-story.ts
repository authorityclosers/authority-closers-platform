/**
 * The rep's Report as one story (binding spec, 9 Oct, section 1): a port of
 * apps/sales-xray-web/app/report-story-model.ts onto the console's types, so
 * reviewers judge each pillar exactly as reps read it. Every sentence is a C5
 * field or a fixed label, every play link is a C5 quote (or a measured line),
 * and a missing field is listed, never filled in.
 */
import type { Evidence, Finding, Metrics, Report, Segment } from "./call-data";
import {
  REPORT_PILLARS,
  REPORT_SKILLS,
  skillState,
  type PillarEntry,
  type ReportPillar,
} from "./report-pillars";

export type Line = {
  text: string;
  sources: Evidence[];
  /** The analysis offers this as a possibility, not an established fact. */
  inferred?: boolean;
};

export type OutcomeStatus =
  | "Won"
  | "Lost"
  | "Follow-up Set"
  | "Decision Pending"
  | "Deferred"
  | "Meeting Booked"
  | "Disqualified"
  | "No Clear Next Step"
  | "Still Open";

export type Outcome = {
  /** Won and Lost only ever come from a person, never from the analysis. */
  status: OutcomeStatus | null;
  origin: "person" | "call" | null;
  detail: Line | null;
};

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
  source: Evidence;
  why: Line | null;
  movedToward?: Line;
  couldExplore?: string;
};

export type Item = { title: string; what: Line; why: Line | null };
export type SkillRow = {
  id: string;
  label: string;
  state: string | null;
  observation: string | null;
  sources: Evidence[];
};
export type Phase = { label: string; startMs: number; endMs: number };
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
  /** The moments the rep sees before "View all". */
  topMoments: Moment[];
  skills: SkillRow[];
  deeper: { unclear: string[]; concerns: Line[]; findings: Item[] };
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
  /** Per pillar, what this report does not establish. */
  missing: [string[], string[], string[], string[], string[], string[]];
};

const PHASE_LABELS: Record<string, string> = {
  opening: "Opening",
  discovery: "Discovery",
  pitch: "Offer discussion",
  objection: "Concerns",
  close: "Decision discussion",
};

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
  sources: Evidence[] | undefined,
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
export function callOutcome(report: Report): Outcome {
  const overview = report.overview?.outcome ?? null;
  const story = report.story?.outcome ?? null;
  const detail =
    line(overview?.text, overview?.evidence) ??
    line(report.story?.nextStep?.text, report.story?.nextStep?.evidence);
  let status: OutcomeStatus | null = null;
  if (story) {
    if (story.kind === "follow_up") status = "Follow-up Set";
    else if (story.kind === "disqualified") status = "Disqualified";
    else if (story.kind === "none")
      status =
        story.nextStepRung === "none" || story.nextStepRung === "vague"
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

const evidenceKey = (source: Evidence) =>
  `${source.segmentId}:${source.startMs}`;

function findingItem(
  finding: Finding,
  why: string | null | undefined,
  inferredWhy: boolean,
): Item {
  return {
    title: finding.title,
    what: { text: finding.explanation, sources: finding.evidence.slice(0, 1) },
    why: line(why, [], inferredWhy),
  };
}

type Roles = { seller: string | null; prospect: string | null };

/** The report's call map: who it read as the seller and the prospect. */
export function callMapRoles(report: Report): Roles {
  const find = (role: string) =>
    Object.entries(report.speakers).find(([, value]) => value === role)?.[0] ??
    null;
  return { seller: find("seller"), prospect: find("prospect") };
}

function metricsFor(
  metrics: Metrics | null,
  durationMs: number | null,
  roles: Roles,
): Metric[] {
  if (!metrics || !durationMs) return [];
  const speakers = metrics.speakers;
  const ids = Object.keys(speakers).sort(
    (a, b) => speakers[b]!.talkMs - speakers[a]!.talkMs,
  );
  const ordered =
    roles.seller && roles.prospect && ids.includes(roles.seller)
      ? [roles.seller, roles.prospect].filter((id) => ids.includes(id))
      : ids.slice(0, 2);
  const names =
    roles.seller && roles.prospect && ordered[0] === roles.seller
      ? "Rep : Prospect"
      : ordered.length === 2
        ? "Speaker 1 : Speaker 2"
        : null;
  const result: Metric[] = [
    { label: "Call length", value: formatDuration(durationMs) },
  ];
  if (ordered.length === 2 && names) {
    const [first, second] = ordered.map((id) => speakers[id]!);
    result.push({
      label: "Talk share",
      value: `${Math.round((first!.talkShare ?? 0) * 100)} : ${Math.round((second!.talkShare ?? 0) * 100)}`,
      note: names,
    });
    result.push({
      label: "Questions asked",
      value: `${first!.questions} : ${second!.questions}`,
      note: names,
    });
  }
  const seller =
    roles.seller && ids.includes(roles.seller) ? roles.seller : null;
  const longest = seller
    ? speakers[seller]!.longestMonologueMs
    : Math.max(0, ...ids.map((id) => speakers[id]!.longestMonologueMs));
  if (longest > 0)
    result.push({
      label: seller ? "Longest seller turn" : "Longest turn",
      value: formatDuration(longest),
    });
  result.push({ label: "Talk-overs", value: String(metrics.cutIns) });
  return result;
}

function phasesFor(report: Report, durationMs: number | null): Phase[] | null {
  const phases = report.story?.phases;
  if (!phases?.length || !durationMs) return null;
  return phases.map((phase, index) => ({
    label: PHASE_LABELS[phase.name] ?? phase.name,
    startMs: phase.startMs,
    endMs: phases[index + 1]?.startMs ?? durationMs,
  }));
}

function momentsFor(
  report: Report,
  segments: Segment[],
  metrics: Metrics | null,
): Moment[] {
  const overview = report.overview;
  const story = report.story;
  const moments: Moment[] = [];
  const seen = new Set<string>();
  const add = (moment: Omit<Moment, "key">) => {
    const key = evidenceKey(moment.source);
    if (seen.has(key)) return;
    seen.add(key);
    moments.push({ ...moment, key });
  };
  const change = overview?.conversationChange;
  if (change?.change.evidence[0])
    add({
      kind: "Turning Point",
      title: "The conversation changed here",
      source: change.change.evidence[0],
      why: line(change.possibleEffect, [], true),
    });
  for (const missed of overview?.missedDetails ?? []) {
    const finding = report.missedOpportunities[missed.findingIndex];
    const source = missed.prospectSignal.evidence[0];
    if (!finding || !source) continue;
    add({
      kind: "Important Miss",
      title: finding.title,
      source,
      why: line(missed.potentialImpact, [], true),
      movedToward:
        line(missed.closerResponse.text, missed.closerResponse.evidence) ??
        undefined,
      couldExplore: clean(missed.followUp) ?? undefined,
    });
  }
  for (const golden of overview?.goldenMoments ?? []) {
    const finding = report.strengths[golden.strengthIndex];
    const source = finding?.evidence[golden.evidenceIndex];
    if (!finding || !source) continue;
    add({
      kind: "Strong Moment",
      title: finding.title,
      source,
      why: line(golden.whyEffective, [], true),
    });
  }
  for (const finding of report.objectionAnalysis) {
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
  const closing = outcome?.evidence.at(-1) ?? story?.outcome.evidence[0];
  const followUp =
    outcome?.kind === "follow_up" || story?.outcome.kind === "follow_up";
  if (closing)
    add({
      kind:
        followUp || outcome?.kind === "future_date"
          ? "Commitment"
          : "Decision Moment",
      title: followUp ? "A next step was agreed" : "How the call ended",
      source: closing,
      why: line(outcome?.text ?? story?.nextStep?.text, []),
    });
  const price = metrics?.priceMoments[0];
  const segment = price
    ? segments.find((item) => item.id === price.segmentId)
    : null;
  if (segment)
    add({
      kind: "Price Moment",
      title: "Price or money came up",
      source: {
        segmentId: segment.id,
        quote: segment.text,
        startMs: segment.startMs,
        endMs: segment.endMs,
      },
      why: null,
    });
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
  return [...moments]
    .sort(
      (a, b) =>
        MOMENT_PRIORITY.indexOf(a.kind) - MOMENT_PRIORITY.indexOf(b.kind) ||
        a.source.startMs - b.source.startMs,
    )
    .slice(0, limit)
    .sort((a, b) => a.source.startMs - b.source.startMs);
}

const present = (values: (string | false)[]) =>
  values.filter((value): value is string => Boolean(value));

/** Builds every pillar from one saved report; older reports simply say less. */
export function reportStoryModel(
  report: Report,
  options: {
    segments?: Segment[];
    metrics?: Metrics | null;
    durationMs?: number | null;
  } = {},
): StoryModel {
  const segments = options.segments ?? [];
  const metrics = options.metrics ?? null;
  const durationMs = options.durationMs ?? null;
  const overview = report.overview;
  const story = report.story;
  const outcome = callOutcome(report);

  const strength = report.strengths.find((item) => item.evidence.length);
  const concernIndex = overview?.nextCallFocus?.improvementIndex ?? 0;
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
    line(story?.nextStep?.text, story?.nextStep?.evidence) ??
    (outcomeLeadsOn ? outcome.detail : null);

  const picture = {
    outcome,
    summary: line(report.summary, report.summaryEvidence),
    assessment: clean(overview?.finalAssessment?.assessment),
    influence: line(overview?.diagnosis?.text, overview?.diagnosis?.evidence),
    strongest,
    concern,
    nextStep,
  };

  const change = overview?.conversationChange;
  const flow = {
    metrics: metricsFor(metrics, durationMs, callMapRoles(report)),
    phases: phasesFor(report, durationMs),
    change: change
      ? {
          before: { text: change.before.text, sources: change.before.evidence },
          turn: { text: change.change.text, sources: change.change.evidence },
          after: { text: change.after.text, sources: change.after.evidence },
          effect: clean(change.possibleEffect),
        }
      : null,
  };

  const worked = report.strengths
    .slice(0, 5)
    .map((finding, index) =>
      findingItem(
        finding,
        overview?.strengthDetails.find((d) => d.findingIndex === index)
          ?.whyItMatters,
        true,
      ),
    );
  const didnt = report.improvements.slice(0, 3).map((finding, index) => {
    const detail = overview?.improvementDetails.find(
      (d) => d.findingIndex === index,
    );
    const item = findingItem(finding, detail?.whyItMatters, true);
    // The separate call observation, when supplied, is the better play link.
    const observed = detail?.whatHappened.evidence.slice(0, 1);
    return observed?.length
      ? { ...item, what: { ...item.what, sources: observed } }
      : item;
  });

  const moments = momentsFor(report, segments, metrics);

  const skills = REPORT_SKILLS.map(([id, label]): SkillRow => {
    const dimension = report.dimensions.find((d) => d.id === id);
    const state = dimension ? skillState(dimension) : null;
    return {
      id,
      label,
      state,
      observation: state && dimension ? clean(dimension.observation) : null,
      sources: state ? (dimension?.evidence ?? []) : [],
    };
  });

  const unclear = overview?.missingInputs ?? [];
  const concerns = (overview?.prospectInterpretations ?? []).map(
    (item): Line => ({
      text: item.possibleConcern,
      sources: item.source.evidence,
      inferred: true,
    }),
  );
  const deeper = {
    unclear,
    concerns,
    findings: [...report.objectionAnalysis, ...report.closingAnalysis].map(
      (finding) => findingItem(finding, null, false),
    ),
  };

  const rung = story?.outcome.nextStepRung;
  const deal = {
    outcome,
    position: outcome.detail,
    blocker: concerns[0] ?? null,
    prospectCommitments: [
      ...(story?.prospectCommitments ?? []),
      ...(story?.prospectTasks ?? []),
    ].map((note) => ({ text: note.text, sources: note.evidence })),
    sellerCommitments: (story?.sellerCommitments ?? []).map((note) => ({
      text: [note.text, note.dueText].filter(Boolean).join(" · "),
      sources: note.evidence,
    })),
    nextEvent:
      story?.outcome.nextStepWhen && story.outcome.evidence.length
        ? { text: story.outcome.nextStepWhen, sources: story.outcome.evidence }
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
    action: clean(overview?.finalAssessment?.nextFocus),
    coachingMission: clean(overview?.nextCallFocus?.behavior),
  };

  const missing: StoryModel["missing"] = [
    present([
      !outcome.status && "Call outcome",
      !picture.summary && "Summary",
      !picture.influence && "What most affected this call",
      !strongest && "Strongest part",
      !concern && "Biggest concern",
      !nextStep && "Next agreed step",
    ]),
    present([
      !flow.phases && "Conversation stages",
      !flow.change && "Key change",
    ]),
    present([!worked.length && "What worked", !didnt.length && "What didn't"]),
    moments.length ? [] : ["Moments"],
    skills.filter((skill) => !skill.state).map((skill) => skill.label),
    present([
      !deal.blocker && "Current blocker",
      !deal.prospectCommitments.length && "Prospect commitment",
      !deal.sellerCommitments.length && "Seller commitment",
      !deal.nextEvent && "Next event date",
      !deal.quality && "Commitment quality",
    ]),
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

const ORIGIN_NOTE: Record<NonNullable<Outcome["origin"]>, string> = {
  person: "Recorded by the rep's team",
  call: "As heard on the call",
};

function lineEntry(
  label: string,
  value: Line | null,
  extra: Partial<PillarEntry> = {},
): PillarEntry[] {
  return value
    ? [
        {
          label,
          text: value.text,
          evidence: value.sources,
          ...(value.inferred ? { hypothesis: true } : {}),
          ...extra,
        },
      ]
    : [];
}

const textEntry = (label: string, text: string | null): PillarEntry[] =>
  text ? [{ label, text, evidence: [] }] : [];

/** One quiet line naming what this report does not establish. */
const notInReport = (items: string[]): PillarEntry[] =>
  items.length
    ? [
        {
          label: "Not in this report",
          text: items.join(" · "),
          evidence: [],
          gap: true,
        },
      ]
    : [];

function outcomeEntry(label: string, outcome: Outcome): PillarEntry {
  return {
    label,
    text: outcome.status ?? "Outcome not recorded",
    evidence: [],
    note: outcome.origin
      ? ORIGIN_NOTE[outcome.origin]
      : "Only a person records won or lost",
    ...(outcome.status ? {} : { gap: true }),
  };
}

function itemEntries(items: Item[], kind: string, whyLabel: string) {
  return items.flatMap((item): PillarEntry[] => [
    {
      label: `${kind} · ${item.title}`,
      text: item.what.text,
      evidence: item.what.sources,
    },
    ...lineEntry(whyLabel, item.why),
  ]);
}

/**
 * The six pillars as reviewers read them: the rep's story, laid out as
 * labelled entries with their play links, possibilities marked, and one line
 * per pillar for what the report doesn't establish.
 */
export function reportPillars(
  report: Report,
  options: {
    segments?: Segment[];
    metrics?: Metrics | null;
    durationMs?: number | null;
  } = {},
): ReportPillar[] {
  const model = reportStoryModel(report, options);
  const { picture, flow, deal, deeper } = model;
  const nextStepRepeats =
    picture.nextStep && picture.nextStep.text === picture.outcome.detail?.text;

  const bigPicture: PillarEntry[] = [
    outcomeEntry("Call outcome", picture.outcome),
    ...(nextStepRepeats
      ? []
      : lineEntry("How it ended", picture.outcome.detail)),
    ...lineEntry("Summary", picture.summary),
    ...textEntry("Assessment", picture.assessment),
    ...lineEntry("What most affected this call", picture.influence),
    ...lineEntry("Strongest part", picture.strongest),
    ...lineEntry("Biggest concern", picture.concern),
    ...lineEntry("Next step", picture.nextStep),
    ...notInReport(model.missing[0]),
  ];

  const change = flow.change;
  const playedOut: PillarEntry[] = [
    ...(change
      ? [
          ...lineEntry("Before", change.before),
          ...lineEntry("The call changed here", change.turn),
          ...lineEntry("After", change.after),
          ...lineEntry("Possible effect", line(change.effect, [], true)),
        ]
      : []),
    ...notInReport(model.missing[1]),
  ];

  const workedDidnt: PillarEntry[] = [
    ...itemEntries(model.worked, "What worked", "Why it helped"),
    ...itemEntries(model.didnt, "What didn't", "What it affected"),
    ...notInReport(model.missing[2]),
  ];

  const shownFirst = new Set(model.topMoments.map((moment) => moment.key));
  const moments: PillarEntry[] = [
    ...model.moments
      .slice()
      .sort((a, b) => a.source.startMs - b.source.startMs)
      .map((moment): PillarEntry => {
        const note = [
          moment.movedToward &&
            `The rep moved toward: ${moment.movedToward.text}`,
          moment.couldExplore && `Could explore: ${moment.couldExplore}`,
        ]
          .filter(Boolean)
          .join(" · ");
        return {
          label: `${moment.kind} · ${moment.title}`,
          text: moment.why?.text ?? "",
          evidence: [moment.source],
          ...(moment.why?.inferred ? { hypothesis: true } : {}),
          ...(note ? { note } : {}),
          ...(shownFirst.has(moment.key) ? {} : { secondary: true }),
        };
      }),
    ...notInReport(model.missing[3]),
  ];

  const skills: PillarEntry[] = [
    ...model.skills.map(
      (skill): PillarEntry => ({
        label: `${skill.label} · ${skill.state ?? "Not established"}`,
        text: skill.observation ?? "Not established in this report.",
        evidence: skill.sources,
        ...(skill.state ? {} : { gap: true }),
      }),
    ),
    ...textEntry("Deeper · Still unclear", deeper.unclear.join(" · ") || null),
    ...deeper.concerns.flatMap((concern) =>
      lineEntry("Deeper · Possible concern", concern),
    ),
    ...itemEntries(deeper.findings, "Deeper · Objections and closing", ""),
  ];

  const dealStands: PillarEntry[] = [
    outcomeEntry("Current status", deal.outcome),
    ...lineEntry("Prospect's position", deal.position),
    ...lineEntry("Possible blocker", deal.blocker),
    ...deal.prospectCommitments.flatMap((item) =>
      lineEntry("Prospect agreed to", item),
    ),
    ...deal.sellerCommitments.flatMap((item) =>
      lineEntry("Rep agreed to", item),
    ),
    ...lineEntry("Next event", deal.nextEvent),
    ...textEntry("Commitment", deal.quality),
    ...textEntry(
      "Still needs to become clear",
      deal.unclear.join(" · ") || null,
    ),
    ...textEntry("Recommended next move", deal.action),
    ...textEntry("Coaching mission for the next call", deal.coachingMission),
    ...notInReport(model.missing[5]),
  ];

  const entries = [
    bigPicture,
    playedOut,
    workedDidnt,
    moments,
    skills,
    dealStands,
  ];
  return REPORT_PILLARS.map((pillar, index) => ({
    ...pillar,
    entries: entries[index]!,
    ...(index === 1 && flow.phases?.length ? { timeline: flow.phases } : {}),
    ...(index === 1 && flow.metrics.length ? { metrics: flow.metrics } : {}),
  }));
}
