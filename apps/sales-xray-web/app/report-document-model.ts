import { formatClock } from "./lightbox/time";
import {
  BIG_PICTURE,
  CALL_FLOW,
  COMMITMENT_MEANING,
  COMMON,
  DEAL,
  DOCUMENT,
  END_SUMMARY,
  MOMENTS,
  PILLAR_COPY,
  PILLAR_IDS,
  SKILLS,
  SKILL_STATE_MEANING,
  WORKED_DIDNT,
  changedAt,
  clearBecause,
  followUpOn,
  momentHead,
  partHeading,
  pillarHeading,
  prospectAgreed,
  type PartCopy,
  type PillarId,
} from "./report-copy";
import type { ReportEvidence } from "./report-contract";
import type { DocumentReportData } from "./report-document-data";
import {
  reportStoryModel,
  type Item,
  type Line,
  type Moment,
  type StoryModel,
} from "./report-story-model";

/**
 * The Document view and the Word file, as one list of blocks (owner order,
 * 11 Oct 2026: "a clean, printable page that mirrors Dipak's document").
 *
 * It follows his document's order and numbered headings (1. The Big Picture,
 * 1.1 Call Outcome …) and reads only the Report's own story model, so the
 * page, the Word file and the Report screen always say the same thing. A part
 * the report can't fill is left out and named once in the pillar's gap line.
 */

export type DocClip = {
  /** "18:42" */
  at: string;
  /** "18:42–19:05" */
  range: string;
  quote: string;
  speaker: string | null;
  source: ReportEvidence;
};

export type DocTone = "good" | "warn" | "accent" | "neutral";

export type DocItem =
  /** The outcome as one status word, with where it came from. */
  | { type: "status"; status: string; origin: string; tone: DocTone }
  | {
      type: "text";
      text: string;
      strong?: boolean;
      possible?: boolean;
      clip?: DocClip;
    }
  /** A small bold label inside a part ("Why it helped"). */
  | { type: "label"; text: string; possible?: boolean }
  /** A group heading inside a part (the Deep Analysis groups). */
  | { type: "subheading"; text: string }
  | { type: "list"; items: string[] }
  | { type: "quote"; clip: DocClip }
  | { type: "play"; clip: DocClip; range?: boolean }
  | {
      type: "metrics";
      items: { value: string; label: string; note?: string }[];
      note: string;
    }
  | {
      type: "timeline";
      durationMs: number;
      stages: {
        label: string;
        /** Same stage, same colour: the stage's place among distinct stages. */
        tone: number;
        from: string;
        to: string;
        share: number;
      }[];
    }
  | {
      type: "steps";
      steps: { label: string; title?: string; text: string }[];
    }
  /** One worked/didn't item or one moment: a titled block of items. */
  | {
      type: "card";
      kicker?: string;
      title: string;
      tone: DocTone;
      items: DocItem[];
    }
  /** Skill rows: name, state and what was seen, with its play times. */
  | {
      type: "skills";
      rows: {
        name: string;
        state: string;
        tone: DocTone;
        meaning: string | null;
        observation: string;
        clips: DocClip[];
      }[];
    }
  | { type: "summary"; cells: { label: string; value: string }[] };

export type DocPart = { heading: string | null; items: DocItem[] };

export type DocSection = {
  id: PillarId;
  heading: string;
  subtitle: string;
  parts: DocPart[];
  gaps: string[];
};

export type ReportDoc = {
  kicker: string;
  title: string;
  draftNote: string;
  facts: { label: string; value: string }[];
  sections: DocSection[];
  summary: DocItem | null;
  closing: string;
};

export type DocPeople = {
  /** A confirmed or default name for a transcript speaker id. */
  speakerName?: (speakerId: string) => string | null | undefined;
  roles?: { seller?: string | null; prospect?: string | null };
};

const OUTCOME_TONE: Record<string, DocTone> = {
  Won: "good",
  "Follow-up Set": "good",
  "Meeting Booked": "good",
  Commitment: "good",
  "Decision Pending": "warn",
  Deferred: "warn",
  "Still Open": "warn",
  "No Clear Next Step": "warn",
  Lost: "neutral",
  Disqualified: "neutral",
};

const MOMENT_TONE: Record<string, DocTone> = {
  "Strong Moment": "good",
  "Buying Signal": "good",
  "Trust Moment": "good",
  Commitment: "good",
  "Turning Point": "accent",
  "Decision Moment": "accent",
  "Price Moment": "accent",
  "Important Miss": "warn",
  Objection: "warn",
  Risk: "warn",
};

const STATE_TONE: Record<string, DocTone> = {
  "Strongly Demonstrated": "good",
  Observed: "accent",
  "Needs Attention": "warn",
};

const present = <T>(value: T | null | undefined | false): value is T =>
  Boolean(value);

/** The same words, ignoring case, quotes and punctuation. */
const same = (a: string | null | undefined, b: string | null | undefined) => {
  const norm = (v: string | null | undefined) =>
    (v ?? "")
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, " ")
      .trim();
  return norm(a) !== "" && norm(a) === norm(b);
};

/** Blocks without the ones a report can't fill. */
const keep = (list: (DocItem | null | undefined | false)[]): DocItem[] =>
  list.filter(present);

function clipOf(
  source: ReportEvidence | undefined,
  speakerOf: (segmentId: string) => string | null,
): DocClip | undefined {
  if (!source) return undefined;
  const at = formatClock(source.start_ms);
  const end = formatClock(Math.max(source.end_ms, source.start_ms));
  return {
    at,
    range: end === at ? at : `${at}–${end}`,
    quote: source.quote?.trim() ?? "",
    speaker: speakerOf(source.segment_id),
    source,
  };
}

/** Builds the document from one saved report; older reports simply say less. */
export function reportDocumentModel(
  data: DocumentReportData,
  people: DocPeople = {},
): ReportDoc {
  if (!data.report) throw new Error("document_report_missing");
  const transcript = data.transcript;
  const segmentSpeaker = new Map(
    (transcript?.segments ?? []).map((s) => [s.id, s.speaker_id]),
  );
  const nameOf = (speakerId: string | null | undefined) =>
    speakerId
      ? people.speakerName?.(speakerId)?.trim() ||
        data.speakerNames?.[speakerId]?.trim() ||
        null
      : null;
  const speakerOf = (segmentId: string) =>
    nameOf(segmentSpeaker.get(segmentId));
  const clip = (source: ReportEvidence | undefined) =>
    clipOf(source, speakerOf);

  const model: StoryModel = reportStoryModel(data.report, transcript, {
    roles: people.roles,
  });

  const prospectName =
    nameOf(people.roles?.prospect) || data.prospectName?.trim() || null;
  const sellerName =
    nameOf(people.roles?.seller) || data.repName?.trim() || null;

  const lineItem = (
    line: Line | null,
    options: { strong?: boolean; last?: boolean } = {},
  ): DocItem | null =>
    line
      ? {
          type: "text",
          text: line.text,
          strong: options.strong,
          possible: line.inferred,
          clip: clip(options.last ? line.sources.at(-1) : line.sources[0]),
        }
      : null;

  const partOf = (
    copy: PartCopy,
    items: (DocItem | null)[],
  ): DocPart | null => {
    const kept = items.filter(present);
    return kept.length ? { heading: partHeading(copy), items: kept } : null;
  };

  const section = (
    id: PillarId,
    parts: (DocPart | null)[],
    gaps: string[],
  ): DocSection => ({
    id,
    heading: pillarHeading(id),
    subtitle: PILLAR_COPY[id].subtitle,
    parts: parts.filter(present),
    gaps,
  });

  const { picture, flow, deal } = model;
  const outcome = picture.outcome;
  const statusItem: DocItem = {
    type: "status",
    status: outcome.status ?? BIG_PICTURE.outcomeNotSet,
    origin:
      outcome.origin === "person"
        ? BIG_PICTURE.outcomeByPerson
        : outcome.origin === "call"
          ? BIG_PICTURE.outcomeFromCall
          : BIG_PICTURE.outcomeOnlyPerson,
    tone: outcome.status
      ? (OUTCOME_TONE[outcome.status] ?? "neutral")
      : "neutral",
  };
  const nextStepRepeats =
    picture.nextStep && picture.nextStep.text === outcome.detail?.text;

  /* 1. The Big Picture */
  const bigPicture = section(
    "overview",
    [
      partOf(BIG_PICTURE.outcome, [
        statusItem,
        nextStepRepeats ? null : lineItem(outcome.detail),
      ]),
      partOf(BIG_PICTURE.summary, [
        lineItem(picture.summary),
        picture.assessment ? { type: "text", text: picture.assessment } : null,
      ]),
      partOf(BIG_PICTURE.influence, [
        lineItem(picture.influence, { strong: true }),
      ]),
      partOf(BIG_PICTURE.strongest, [lineItem(picture.strongest)]),
      partOf(BIG_PICTURE.concern, [lineItem(picture.concern)]),
      partOf(BIG_PICTURE.nextStep, [
        lineItem(picture.nextStep, { last: true }),
        deal.nextEvent && !picture.nextStep?.text.includes(deal.nextEvent.text)
          ? {
              type: "text",
              text: followUpOn(deal.nextEvent.text),
              strong: true,
            }
          : null,
      ]),
    ],
    model.missing[0],
  );

  /* 2. How the Call Played Out */
  const duration = transcript?.duration_ms ?? 0;
  const turn = flow.change?.turn.sources[0];
  const turnClip = clip(turn);
  const callFlow = section(
    "coaching",
    [
      flow.metrics.length
        ? partOf(CALL_FLOW.metrics, [
            {
              type: "metrics",
              items: flow.metrics.map((m) => ({
                value: m.value,
                label: m.label,
                note: m.note,
              })),
              note: CALL_FLOW.metricsNote,
            },
          ])
        : null,
      flow.phases?.length && duration
        ? partOf(CALL_FLOW.timeline, [
            {
              type: "timeline",
              durationMs: duration,
              stages: flow.phases.map((phase, _, all) => ({
                label: phase.label,
                tone: [...new Set(all.map((p) => p.label))].indexOf(
                  phase.label,
                ),
                from: formatClock(phase.start_ms),
                to: formatClock(phase.end_ms),
                share: Math.max(0, phase.end_ms - phase.start_ms) / duration,
              })),
            },
          ])
        : null,
      flow.change && turnClip
        ? partOf(CALL_FLOW.change, [
            { type: "text", text: changedAt(turnClip.at), strong: true },
            turnClip.quote ? { type: "quote", clip: turnClip } : null,
            // Some reports describe the switch with the quote itself.
            same(flow.change.turn.text, turnClip.quote)
              ? null
              : { type: "text", text: flow.change.turn.text },
            { type: "play", clip: turnClip },
          ])
        : null,
      flow.change
        ? partOf(CALL_FLOW.beforeAfter, [
            {
              type: "steps",
              steps: [
                {
                  label: CALL_FLOW.before,
                  title: flow.change.beforeLabel ?? undefined,
                  text: flow.change.before.text,
                },
                {
                  label: CALL_FLOW.switch,
                  title: turnClip?.at,
                  text: flow.change.turn.text,
                },
                {
                  label: CALL_FLOW.after,
                  title: flow.change.afterLabel ?? undefined,
                  text: flow.change.after.text,
                },
              ],
            },
            flow.change.effect
              ? { type: "label", text: CALL_FLOW.effect, possible: true }
              : null,
            flow.change.effect
              ? { type: "text", text: flow.change.effect }
              : null,
          ])
        : null,
    ],
    model.missing[1],
  );

  /* 3. What Worked — & What Didn't */
  const itemCard = (item: Item, why: string, tone: DocTone): DocItem => {
    const play = clip(item.what.sources[0]);
    const areas = item.areas?.filter((area) => area?.trim()) ?? [];
    return {
      type: "card",
      title: item.title,
      tone,
      items: keep([
        { type: "text", text: item.what.text },
        areas.length ? { type: "label", text: WORKED_DIDNT.areasLead } : null,
        areas.length ? { type: "list", items: areas } : null,
        play ? { type: "play", clip: play } : null,
        item.why ? { type: "label", text: why } : null,
        item.why ? { type: "text", text: item.why.text } : null,
      ]),
    };
  };
  const workedDidnt = section(
    "moments",
    [
      {
        heading: partHeading(WORKED_DIDNT.worked),
        items: model.worked.length
          ? model.worked.map((item) =>
              itemCard(item, WORKED_DIDNT.whyHelped, "good"),
            )
          : [{ type: "text", text: WORKED_DIDNT.noneWorked }],
      },
      {
        heading: partHeading(WORKED_DIDNT.didnt),
        items: model.didnt.length
          ? model.didnt.map((item) =>
              itemCard(item, WORKED_DIDNT.whatAffected, "warn"),
            )
          : [{ type: "text", text: WORKED_DIDNT.noneDidnt }],
      },
    ],
    model.missing[2],
  );

  /* 4. Moments That Mattered */
  const momentCard = (moment: Moment): DocItem => {
    const at = clip(moment.source);
    return {
      type: "card",
      kicker: momentHead(moment.kind, at?.at ?? ""),
      title: moment.title,
      tone: MOMENT_TONE[moment.kind] ?? "neutral",
      items: keep([
        ...(moment.priceStated
          ? [
              { type: "label", text: MOMENTS.priceStated } as const,
              quoteOf(moment.priceStated),
              moment.prospectResponse
                ? ({ type: "label", text: MOMENTS.prospectResponse } as const)
                : null,
              moment.prospectResponse ? quoteOf(moment.prospectResponse) : null,
            ]
          : [at?.quote ? ({ type: "quote", clip: at } as const) : null]),
        moment.movedToward
          ? { type: "label", text: MOMENTS.movedToward }
          : null,
        moment.movedToward
          ? { type: "text", text: moment.movedToward.text }
          : null,
        moment.couldExplore
          ? { type: "label", text: MOMENTS.whatMissed }
          : null,
        moment.couldExplore
          ? {
              type: "text",
              text: `${MOMENTS.couldFirst} ${moment.couldExplore}`,
            }
          : null,
        moment.why ? { type: "label", text: MOMENTS.whyMattered } : null,
        moment.why ? { type: "text", text: moment.why.text } : null,
        at ? { type: "play", clip: at, range: true } : null,
      ]),
    };
  };
  function quoteOf(said: Line): DocItem {
    const at = clip(said.sources[0]);
    return at
      ? { type: "quote", clip: { ...at, quote: said.text } }
      : { type: "text", text: said.text };
  }
  const topKeys = new Set(model.topMoments.map((m) => m.key));
  const otherMoments = [...model.moments]
    .filter((m) => !topKeys.has(m.key))
    .sort((a, b) => a.source.start_ms - b.source.start_ms);
  const moments = section(
    "missed",
    [
      model.topMoments.length
        ? { heading: null, items: model.topMoments.map(momentCard) }
        : null,
      otherMoments.length
        ? {
            heading: `${MOMENTS.titleMore} (${otherMoments.length})`,
            items: [
              {
                type: "list",
                items: otherMoments.map(
                  (m) =>
                    `${momentHead(m.kind, formatClock(m.source.start_ms))} — ${m.title}`,
                ),
              },
            ],
          }
        : null,
    ],
    model.missing[3],
  );

  /** "Discuss the program with his partner before Friday. (24:12)" */
  const listOf = (lines: Line[]) =>
    lines.map((item) => {
      const at = clip(item.sources.at(-1));
      return at ? `${item.text} (${at.at})` : item.text;
    });

  /* 5. Your Skills on This Call */
  const { discovery, decision, communication, findings, presentation } =
    model.deeper;
  const labelled = (label: string, item: DocItem | null): DocItem[] =>
    item ? [{ type: "label", text: label }, item] : [];
  const listItem = (list: string[] | undefined): DocItem | null =>
    list?.length ? { type: "list", items: list } : null;
  const plain = (text: string | null | undefined): DocItem | null =>
    text?.trim() ? { type: "text", text } : null;
  const deeperItems = keep([
    ...(discovery.clear.length ||
    discovery.unclear.length ||
    discovery.openingMissed
      ? [
          { type: "subheading", text: SKILLS.deeperDiscovery } as const,
          ...labelled(SKILLS.becameClear, listItem(discovery.clear)),
          ...labelled(SKILLS.stillUnclear, listItem(discovery.unclear)),
          ...labelled(SKILLS.openingMissed, lineItem(discovery.openingMissed)),
        ]
      : []),
    ...(presentation
      ? [
          { type: "subheading", text: SKILLS.deeperPresentation } as const,
          ...labelled(SKILLS.relevant, listItem(presentation.relevant)),
          ...labelled(SKILLS.lessRelevant, plain(presentation.lessRelevant)),
          ...labelled(
            SKILLS.valueConnection,
            plain(presentation.valueConnection),
          ),
        ]
      : []),
    ...(decision.price || decision.likely.length || findings.length
      ? [
          { type: "subheading", text: SKILLS.deeperDecision } as const,
          ...labelled(SKILLS.price, lineItem(decision.price)),
          ...labelled(SKILLS.prospectResponse, lineItem(decision.response)),
          ...(decision.likely.length
            ? [
                {
                  type: "label",
                  text: SKILLS.possibleWorries,
                  possible: true,
                } as const,
                { type: "list", items: listOf(decision.likely) } as const,
              ]
            : []),
          ...labelled(
            SKILLS.objectionsClosing,
            listItem(
              findings.map((f) => {
                const at = clip(f.what.sources[0]);
                return `${f.title}: ${f.what.text}${at ? ` (${at.at})` : ""}`;
              }),
            ),
          ),
        ]
      : []),
    ...(communication.longest ||
    communication.observation ||
    communication.listening
      ? [
          { type: "subheading", text: SKILLS.deeperCommunication } as const,
          ...labelled(SKILLS.listening, plain(communication.listening)),
          ...labelled(SKILLS.longestMonologue, plain(communication.longest)),
          ...labelled(
            SKILLS.importantObservation,
            lineItem(communication.observation),
          ),
        ]
      : []),
  ]);
  const skills = section(
    "skills",
    [
      {
        heading: null,
        items: [
          {
            type: "skills",
            rows: model.skills.map((skill) => ({
              name: skill.label,
              state: skill.state ?? SKILLS.notCovered,
              tone: skill.state
                ? (STATE_TONE[skill.state] ?? "neutral")
                : "neutral",
              meaning: skill.state ? SKILL_STATE_MEANING[skill.state] : null,
              observation: skill.observation ?? SKILLS.notCoveredText,
              clips: skill.sources
                .slice(0, 3)
                .map((source) => clip(source))
                .filter(present),
            })),
          },
        ],
      },
      deeperItems.length
        ? { heading: SKILLS.deeperTitle, items: deeperItems }
        : null,
    ],
    model.missing[4],
  );

  /* 6. Where the Deal Stands */
  const dealSection = section(
    "facts",
    [
      partOf(DEAL.status, [statusItem]),
      partOf(DEAL.position, [lineItem(deal.position, { last: true })]),
      partOf(DEAL.blocker, [
        deal.blocker
          ? {
              type: "text",
              text: deal.blocker.text,
              possible: true,
              clip: clip(deal.blocker.sources[0]),
            }
          : null,
      ]),
      deal.prospectCommitments.length
        ? partOf(DEAL.prospectCommitment, [
            { type: "label", text: `${prospectAgreed(prospectName)}:` },
            { type: "list", items: listOf(deal.prospectCommitments) },
          ])
        : null,
      deal.sellerCommitments.length
        ? partOf(DEAL.sellerCommitment, [
            {
              type: "label",
              text: `${sellerName ? `${sellerName} agreed to` : DEAL.sellerCommitment.label}:`,
            },
            { type: "list", items: listOf(deal.sellerCommitments) },
          ])
        : null,
      partOf(DEAL.nextEvent, [
        lineItem(deal.nextEvent, { strong: true, last: true }),
      ]),
      deal.quality
        ? partOf(DEAL.quality, [
            {
              type: "text",
              text:
                deal.quality === "Clear" && deal.nextEvent
                  ? clearBecause(deal.nextEvent.text)
                  : deal.quality,
              strong: true,
            },
            { type: "text", text: COMMITMENT_MEANING[deal.quality] },
          ])
        : null,
      deal.unclear.length
        ? partOf(DEAL.unclear, [{ type: "list", items: deal.unclear }])
        : null,
      deal.action || deal.coachingMission
        ? partOf(DEAL.action, [
            deal.action ? { type: "text", text: deal.action } : null,
            deal.coachingMission
              ? { type: "label", text: DEAL.coachingMission }
              : null,
            deal.coachingMission
              ? { type: "text", text: deal.coachingMission }
              : null,
          ])
        : null,
    ],
    model.missing[5],
  );

  /* Report end summary */
  const end = model.end;
  const keyMoment = end?.moment ?? null;
  type Cell = { label: string; value: string | null | undefined };
  const cells = (
    [
      { label: END_SUMMARY.outcome, value: outcome.status },
      { label: END_SUMMARY.strongest, value: end?.strongest },
      { label: END_SUMMARY.issue, value: end?.issue },
      {
        label: END_SUMMARY.moment,
        value: keyMoment
          ? `${keyMoment.title} · ${formatClock(keyMoment.source.start_ms)}`
          : null,
      },
      {
        label: END_SUMMARY.nextEvent,
        value:
          end?.nextEvent ??
          (picture.nextStep ? END_SUMMARY.agreedNoDate : null),
      },
    ] as Cell[]
  ).filter((cell): cell is { label: string; value: string } =>
    Boolean(cell.value),
  );

  const lengthMs = duration || data.callRecord?.numbers.duration_ms || 0;
  const facts = [
    data.callDate ? { label: DOCUMENT.callDate, value: data.callDate } : null,
    data.callType ? { label: DOCUMENT.callType, value: data.callType } : null,
    lengthMs
      ? { label: DOCUMENT.callLength, value: formatClock(lengthMs) }
      : null,
    sellerName ? { label: DOCUMENT.seller, value: sellerName } : null,
    prospectName ? { label: DOCUMENT.prospect, value: prospectName } : null,
    data.analysedDate
      ? { label: DOCUMENT.analysed, value: data.analysedDate }
      : null,
  ].filter(present);

  return {
    kicker: DOCUMENT.kicker,
    title: data.title?.trim() || DOCUMENT.untitled,
    draftNote: DOCUMENT.draftNote,
    facts,
    sections: [bigPicture, callFlow, workedDidnt, moments, skills, dealSection],
    summary: cells.length >= 2 ? { type: "summary", cells } : null,
    closing: DOCUMENT.closing,
  };
}

/** Plain text of one block, for screen readers, tests and the Word file. */
export function docItemText(item: DocItem): string {
  switch (item.type) {
    case "status":
      return `${item.status} · ${item.origin}`;
    case "text":
      return item.text;
    case "label":
    case "subheading":
      return item.text;
    case "list":
      return item.items.join("\n");
    case "quote":
      return `${item.clip.speaker ? `${item.clip.speaker}: ` : ""}“${item.clip.quote}”`;
    case "play":
      return `${COMMON.play} ${item.range ? item.clip.range : item.clip.at}`;
    case "metrics":
      return item.items.map((m) => `${m.value} ${m.label}`).join(" · ");
    case "timeline":
      return item.stages.map((s) => `${s.label} ${s.from}–${s.to}`).join(" · ");
    case "steps":
      return item.steps.map((s) => `${s.label}: ${s.text}`).join("\n");
    case "card":
      return [item.kicker, item.title, ...item.items.map(docItemText)]
        .filter(Boolean)
        .join("\n");
    case "skills":
      return item.rows.map((r) => `${r.name}: ${r.state}`).join("\n");
    case "summary":
      return item.cells.map((c) => `${c.label}: ${c.value}`).join("\n");
  }
}

export const DOCUMENT_SECTION_IDS = PILLAR_IDS;
