/**
 * Every fixed word the Report shows, in one place (owner order, 11 Oct 2026).
 *
 * Written the way Dipak writes: short, direct, "you", everyday sales words.
 * Headings follow his document word for word (Final X-ray Structure, 9 Oct;
 * `/home/acdev/scratch/specs/final-xray-structure-2026-10-09.md`). The Report
 * screen, the Document view and the Word file all read from here, so the same
 * thing is always called the same name.
 *
 * Words the analysis writes about a call (summaries, quotes, reasons) do not
 * live here; only labels, headings, empty states and helper lines do.
 * Owner of this file: strike 1798. Ask in its INBOX to change a line.
 */

export const REPORT_COPY_VERSION = "report-copy/1";

/* ── The six pillars ─────────────────────────────────────────────────── */

/** Pillar ids are the Report's stable section ids (URLs, Word bookmarks). */
export const PILLAR_IDS = [
  "overview",
  "coaching",
  "moments",
  "missed",
  "skills",
  "facts",
] as const;
export type PillarId = (typeof PILLAR_IDS)[number];

export type PillarCopy = {
  /** Spec number, shown in the Document view ("1. The Big Picture"). */
  number: number;
  label: string;
  /** For tight places: the phone section row and the side rail. */
  short: string;
  subtitle: string;
};

export const PILLAR_COPY: Record<PillarId, PillarCopy> = {
  overview: {
    number: 1,
    label: "The Big Picture",
    short: "Big Picture",
    subtitle: "Understand the call in seconds.",
  },
  coaching: {
    number: 2,
    label: "How the Call Played Out",
    short: "Call Flow",
    subtitle: "See how the conversation moved.",
  },
  moments: {
    number: 3,
    label: "What Worked — & What Didn't",
    short: "Worked / Didn't",
    subtitle: "See what helped the conversation and what made it harder.",
  },
  missed: {
    number: 4,
    label: "Moments That Mattered",
    short: "Moments",
    subtitle: "Replay the moments that changed the conversation.",
  },
  skills: {
    number: 5,
    label: "Your Skills on This Call",
    short: "Skills",
    subtitle: "See how your sales skills showed up in this conversation.",
  },
  facts: {
    number: 6,
    label: "Where the Deal Stands",
    short: "Deal",
    subtitle: "Know exactly what happens next.",
  },
};

/** "1. The Big Picture": a pillar heading as Dipak's document writes it. */
export const pillarHeading = (id: PillarId) =>
  `${PILLAR_COPY[id].number}. ${PILLAR_COPY[id].label}`;

/**
 * One part of a pillar. `heading` is Dipak's numbered heading (Document view
 * and Word); `label` is the short card label the Report screen shows.
 */
export type PartCopy = { number: string; heading: string; label: string };

const part = (number: string, heading: string, label: string): PartCopy => ({
  number,
  heading,
  label,
});

/** "1.4 Strongest Part" */
export const partHeading = (value: PartCopy) =>
  `${value.number} ${value.heading}`;

/* ── Shared words ────────────────────────────────────────────────────── */

export const COMMON = {
  play: "Play",
  pause: "Pause",
  /** Put on a line Sales Xray reads into the call rather than hears said. */
  possible: "Possible",
  possibleHint:
    "Sales Xray's reading of the call. Nobody said this in so many words.",
  /** One quiet line per pillar listing what this report leaves out. */
  gapsLead: "This report doesn't cover:",
  pillarFailed: "This part didn't load. The rest of the report is fine.",
  reportFailed: "This report didn't load. Please try again.",
  tryAgain: "Try again",
  you: "You",
  prospect: "Prospect",
  seller: "Seller",
};

/** "18:42 · Play", or "06:35–06:58 · Play" for a stretch of the call. */
export const playAt = (clock: string) => `${clock} · ${COMMON.play}`;
export const playRange = (from: string, to: string) =>
  `${from}–${to} · ${COMMON.play}`;
/** Screen readers: "Play 18:42: Strongest part". */
export const playLabel = (playing: boolean, clock: string, what: string) =>
  `${playing ? COMMON.pause : COMMON.play} ${clock}: ${what}`;

/* ── 1. The Big Picture ──────────────────────────────────────────────── */

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

export const BIG_PICTURE = {
  outcome: part("1.1", "Call Outcome", "Call outcome"),
  summary: part("1.2", "Executive Summary", "Summary"),
  influence: part(
    "1.3",
    "What Most Affected This Call",
    "What most affected this call",
  ),
  strongest: part("1.4", "Strongest Part", "Strongest part"),
  concern: part("1.5", "Biggest Concern", "Biggest concern"),
  nextStep: part("1.6", "Next Agreed Step", "Next step"),
  /** Where the outcome came from. Won and Lost only ever come from a person. */
  outcomeNotSet: "Outcome not set",
  outcomeByPerson: "Set by your team",
  outcomeFromCall: "As heard on the call",
  outcomeOnlyPerson: "Only a person can mark a call Won or Lost",
};

/** "Follow-up: Friday · 4:00 PM" */
export const followUpOn = (when: string) => `Follow-up: ${when}`;

/* ── 2. How the Call Played Out ──────────────────────────────────────── */

export const CALL_FLOW = {
  metrics: part("2.1", "Call Metrics", "Call numbers"),
  timeline: part("2.2", "Conversation Timeline", "How the call moved"),
  change: part("2.3", "Key Change in the Conversation", "Key change"),
  beforeAfter: part("2.4", "Before / Switch / After", "Before and after"),
  before: "Before",
  switch: "The switch",
  after: "After",
  /** What the switch possibly changed (always marked Possible). */
  effect: "What it changed",
  /** Metrics are evidence, not a verdict (spec 2.1). */
  metricsNote:
    "These numbers show what happened, not how well. What they mean depends on the moment.",
  noStages: "The call's stages aren't marked in this report.",
  whoSpokeWhen: "Who spoke when",
  momentsLane: "Moments",
  /** On the timeline, beside the line where the call changed: "Changed here · 11:18". */
  changedShort: "Changed here",
};

/** "The call changed here · 11:18" */
export const changedAt = (clock: string) => `The call changed here · ${clock}`;

export const METRIC_LABELS = {
  callLength: "Call length",
  talkShare: "Talk share",
  questions: "Questions asked",
  longestSellerTurn: "Longest seller turn",
  longestTurn: "Longest turn",
  talkOvers: "Talk-overs",
  /** Who each side of "62 : 38" is. */
  youProspect: "You : Prospect",
  sellerProspect: "Seller : Prospect",
  speakers: "Speaker 1 : Speaker 2",
};

/** Conversation stages as a salesperson names them (spec 2.2, 2.4). */
export const STAGE_LABELS = {
  opening: "Opening",
  discovery: "Discovery",
  pitch: "Presentation",
  objection: "Objections",
  close: "Decision & Next Step",
};

/* ── 3. What Worked — & What Didn't ──────────────────────────────────── */

export const WORKED_DIDNT = {
  worked: part("3.1", "What Worked", "What worked"),
  didnt: part("3.2", "What Didn't", "What didn't"),
  whyHelped: "Why it helped",
  whatAffected: "What it affected",
  /** Before the open areas a What Didn't item lists (spec 3.2). */
  areasLead: "Possible unanswered areas included:",
  noneWorked: "Nothing stood out as a clear strength we can point to.",
  noneDidnt:
    "No clear issue we can point to. That doesn't mean everything went right.",
};

/* ── 4. Moments That Mattered ────────────────────────────────────────── */

/**
 * Dipak's ten moment labels (spec 4). "Worth Replaying" stays only for older
 * consumers: the Report no longer makes such moments (B, `9c2abc63`).
 */
export const MOMENT_KINDS = [
  "Strong Moment",
  "Turning Point",
  "Buying Signal",
  "Important Miss",
  "Objection",
  "Price Moment",
  "Decision Moment",
  "Trust Moment",
  "Commitment",
  "Risk",
  "Worth Replaying",
] as const;
export type MomentKindLabel = (typeof MOMENT_KINDS)[number];

export const MOMENTS = {
  whyMattered: "Why it mattered",
  movedToward: "You moved toward",
  whatMissed: "What was missed",
  couldFirst: "You could have first understood:",
  priceStated: "Price stated",
  prospectResponse: "Prospect response",
  showTop: "Show top moments only",
  /** Document view: the moments that sit under "View all" on screen. */
  titleMore: "More moments",
  none: "No moments were picked out for this call.",
  /** Titles Sales Xray gives a moment when the analysis gives none. */
  titleTurn: "The call changed here",
  titleNextStep: "A next step was agreed",
  titleEnding: "How the call ended",
  titlePrice: "Price came up",
};

/** "View all 8 moments" */
export const viewAllMoments = (count: number) => `View all ${count} moments`;

/** "STRONG MOMENT · 06:35" (the screen sets the capitals in CSS). */
export const momentHead = (kind: string, clock: string) => `${kind} · ${clock}`;

/* ── 5. Your Skills on This Call ─────────────────────────────────────── */

export const SKILL_STATES = [
  "Strongly Demonstrated",
  "Observed",
  "Needs Attention",
  "Not Enough Evidence",
  "Not Applicable",
] as const;
export type SkillStateLabel = (typeof SKILL_STATES)[number];

/** What each state means, in one line (spec 5, recommended states). */
export const SKILL_STATE_MEANING: Record<SkillStateLabel, string> = {
  "Strongly Demonstrated": "Clear positive evidence.",
  Observed: "Enough evidence to comment.",
  "Needs Attention": "A clear weakness on this call.",
  "Not Enough Evidence": "The chance to use this skill didn't come up enough.",
  "Not Applicable": "Not relevant to this call.",
};

/** The eight Authority Closers skills: full name and the short row name. */
export const SKILL_NAMES = {
  human_connection_trust: {
    label: "Human Connection & Trust",
    short: "Human Connection & Trust",
  },
  discovery_deep_understanding: {
    label: "Discovery & Deep Understanding",
    short: "Discovery",
  },
  qualification: { label: "Qualification", short: "Qualification" },
  problem_impact_desire: {
    label: "Problem, Impact & Desire Clarity",
    short: "Problem / Impact / Desire",
  },
  solution_relevance_presentation: {
    label: "Solution Relevance & Presentation",
    short: "Presentation & Value",
  },
  certainty_objection_intelligence: {
    label: "Certainty & Objection Intelligence",
    short: "Objection Intelligence",
  },
  closing_decision_management: {
    label: "Closing & Decision Management",
    short: "Closing",
  },
  communication_tonality: {
    label: "Communication & Tonality",
    short: "Communication",
  },
};
export type SkillId = keyof typeof SKILL_NAMES;

export const SKILLS = {
  /** A skill this report says nothing about (no state at all). */
  notCovered: "Not covered",
  notCoveredText: "This report doesn't cover this skill.",
  observation: "Observation",
  evidence: "Evidence",
  toCoaching: "Work on this in Coaching",
  deeper: "Explore deeper analysis",
  /** The same part, opened, in the Document view and the Word file. */
  deeperTitle: "Deeper Analysis",
  /** Deep analysis groups (spec 5, Deep Analysis). */
  deeperDiscovery: "Discovery & Qualification",
  deeperPresentation: "Presentation & Value",
  deeperDecision: "Objection / Price / Decision",
  deeperCommunication: "Communication",
  becameClear: "Became clear",
  stillUnclear: "Still unclear",
  openingMissed: "Important opening missed",
  relevant: "Relevant",
  lessRelevant: "Less clearly relevant",
  valueConnection: "Value connection",
  price: "Price",
  prospectResponse: "Prospect response",
  likelyStatus: "Likely status",
  listening: "Listening",
  longestMonologue: "Longest monologue",
  importantObservation: "Important observation",
  /** The analysis' possible reading of a worry, always marked Possible. */
  possibleWorries: "What the prospect may be worried about",
  objectionsClosing: "Objections & closing",
};

/* ── 6. Where the Deal Stands ────────────────────────────────────────── */

export const COMMITMENT_QUALITIES = ["Clear", "Soft", "Unclear"] as const;
export type CommitmentQuality = (typeof COMMITMENT_QUALITIES)[number];

export const COMMITMENT_MEANING: Record<CommitmentQuality, string> = {
  Clear: "Specific action + specific date/time.",
  Soft: "Action mentioned but no firm timing.",
  Unclear: "No reliable next step.",
};

export const DEAL = {
  status: part("6.1", "Current Status", "Current status"),
  position: part("6.2", "Prospect's Position", "Prospect's position"),
  blocker: part("6.3", "Current Blocker", "Current blocker"),
  prospectCommitment: part("6.4", "Prospect Commitment", "Prospect agreed to"),
  sellerCommitment: part("6.5", "Seller Commitment", "You agreed to"),
  nextEvent: part("6.6", "Next Event", "Next event"),
  quality: part("6.7", "Commitment Quality", "Commitment quality"),
  unclear: part(
    "6.8",
    "What Still Needs to Become Clear",
    "Still needs to become clear",
  ),
  action: part("6.9", "Recommended Deal Action", "Next move on this deal"),
  coachingMission: "Coaching mission for your next call",
  prospectSection: "Prospect for this call",
  viewProspect: "View Prospect Information",
  viewCoaching: "View Personalized Coaching",
  coachingForCall: "Coaching for this call",
  recurring: "This issue may be part of a recurring pattern",
  viewCoachingShort: "View Coaching",
  viewProspectShort: "View Prospect",
  noneAgreed: "Nothing was agreed on this call.",
};

/** "Amit agreed to" when the prospect is named, else "Prospect agreed to". */
export const prospectAgreed = (name?: string | null) =>
  name?.trim() ? `${name.trim()} agreed to` : DEAL.prospectCommitment.label;

/** "Commitment: Clear" */
export const commitmentIs = (quality: CommitmentQuality) =>
  `${DEAL.quality.label}: ${quality}`;

/** Spec 6.7: "Clear because Friday · 4:00 PM is agreed." */
export const clearBecause = (when: string) =>
  `Clear because ${when} is agreed.`;

/** "12 prospect insights captured" */
export const prospectInsights = (count: number) =>
  `${count} prospect ${count === 1 ? "insight" : "insights"} captured`;

/* ── Report end summary (spec, optional strip) ───────────────────────── */

export const END_SUMMARY = {
  title: "Report summary",
  outcome: "Call Outcome",
  strongest: "Strongest Part",
  issue: "Biggest Issue",
  moment: "Most Important Moment",
  nextEvent: "Next Event",
  /** A next step was agreed but the call gave no date or time. */
  agreedNoDate: "Agreed, no date yet",
};

/* ── Views and the Document ──────────────────────────────────────────── */

/** `text` on the toolbar, `hint` for screen readers, `menu` in "More views". */
export const VIEWS = {
  report: { text: "Report", hint: "Report view" },
  coaching: { text: "Coaching", hint: "Coaching view" },
  details: {
    text: "Details",
    hint: "Details view",
    menu: "All analysis details",
  },
  document: {
    text: "Document",
    hint: "Document view",
    menu: "Document · print or Word",
  },
  more: "More views",
};

export const DOCUMENT = {
  kicker: "Sales Xray · Call Report",
  untitled: "Sales call",
  /** Under the title: the analysis is a draft until a coach reviews it. */
  draftNote: "Sales Xray's reading of this call. Not reviewed by a coach yet.",
  callLength: "Call length",
  callDate: "Call date",
  callType: "Call type",
  seller: "Salesperson",
  prospect: "Prospect",
  analysed: "Analysed",
  download: "Download Word file",
  print: "Print or save as PDF",
  /** Phones: the same two buttons, short. */
  downloadShort: "Word file",
  printShort: "Print",
  preparing: "Preparing your Word file…",
  wordFailed: "The Word file didn't build. Please try again.",
  contents: "In this report",
  regionLabel: "Report document",
  footer: "Sales Xray · Times are from the recording",
  /** Closing line: where the call's longer story lives. */
  closing:
    "Prospect Information and Personalized Coaching for this call are in Sales Xray.",
  /** Word file name: "<title> – Sales Xray report.docx" */
  fileName: "Sales Xray report",
};
