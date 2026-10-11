/**
 * Every fixed word the Coaching screens show, in one place (owner order,
 * 11 Oct 2026), written the way the Report's copy module is: short, direct,
 * "you", everyday sales words. Pillar headings and subtitles follow Dipak's
 * document word for word (Final X-ray Structure, 9 Oct, "Under COACHING").
 *
 * Words the analysis writes about a call (focus, quotes, lessons) come from
 * the server; only labels, headings, empty states and helper lines live here.
 */
import type { MasteryState, ProgressPoint } from "./coaching-client";

export type CoachingPillarId =
  | "focus"
  | "why"
  | "better"
  | "next"
  | "progress"
  | "path";

export type CoachingPillarCopy = {
  number: number;
  label: string;
  subtitle: string;
};

/** The six learner-facing pillars (spec 2), in the order they are read. */
export const COACHING_PILLARS: Record<CoachingPillarId, CoachingPillarCopy> = {
  focus: {
    number: 1,
    label: "What You Should Work On Now",
    subtitle: "Your highest-priority improvement.",
  },
  why: {
    number: 2,
    label: "Why This Keeps Happening",
    subtitle: "Understand the pattern behind the problem.",
  },
  better: {
    number: 3,
    label: "Here’s What Better Looks Like",
    subtitle:
      "Learn the better approach using your own calls and Dipak’s coaching.",
  },
  next: {
    number: 4,
    label: "Try This on Your Next Call",
    subtitle: "One practice. One mission. One clear target.",
  },
  progress: {
    number: 5,
    label: "See How You’re Improving",
    subtitle: "Track real progress, not completed content.",
  },
  path: {
    number: 6,
    label: "Where We Go From Here",
    subtitle: "See the next stage of your development.",
  },
};

/**
 * One call's coaching has no history yet, so pillar 2 says what happened on
 * this call instead of claiming a pattern (spec 5.5, 5.7).
 */
export const CALL_PILLARS: Record<
  "focus" | "why" | "better" | "next",
  CoachingPillarCopy
> = {
  focus: {
    number: 1,
    label: "What You Should Work On Now",
    subtitle: "The one thing this call says to work on.",
  },
  why: {
    number: 2,
    label: "What Happened on This Call",
    subtitle: "Replay the moments behind this focus.",
  },
  better: COACHING_PILLARS.better,
  next: COACHING_PILLARS.next,
};

/** Another rep's coaching (a manager or a shared view): "they", not "you". */
export const THEIR_FOCUS = "What They Should Work On Now";

export const FOCUS = {
  current: "Current focus",
  status: "Status",
  whyMatters: "Why this matters",
  whyFocus: "Why this focus",
  onNextCall: "On your next call",
  seeMission: "See the mission",
  take: "Hear Dipak’s take",
  active: "Active focus",
  provisional: "From one call so far",
  fromReport: "From this call’s report",
  fromSkills: "From this call’s skill check",
  general: "General practice",
  sandbox: "Fictional AC Sandbox",
  notYet: "Still learning your pattern",
  theirNotYet: "No focus yet",
} as const;

export const WHY = {
  pattern: "Pattern",
  likelyReason: "Likely reason",
  gap: "Gap",
  confidence: "Confidence",
  evidence: "From your calls",
  callEvidence: "From this call",
  yourContext: "Your context",
  theirContext: "Their context",
  noTimestamp:
    "This report kept no time for this suggestion. Open the report to read it in context.",
} as const;

/**
 * Gap types: Dipak's name and the plain line a seller reads (spec pillar 2,
 * "Gap-type mapping"). Shown under "Likely reason", so it stays a hypothesis.
 */
export const GAP_COPY: Record<string, { name: string; line: string }> = {
  knowledge: {
    name: "Knowledge",
    line: "You need a clearer framework for what to explore here.",
  },
  judgment: {
    name: "Judgment / Recognition",
    line: "You usually see the opportunity after the call.",
  },
  execution: {
    name: "Execution",
    line: "You know what to ask but struggle to say it naturally.",
  },
  habit_recall: {
    name: "Habit / Recall",
    line: "The skill is there; the reminder is missing.",
  },
  confidence: {
    name: "Confidence",
    line: "You avoid the question because it feels uncomfortable.",
  },
  cognitive_load: {
    name: "Cognitive load",
    line: "The skill drops when several things happen at once.",
  },
  belief_buy_in: {
    name: "Belief / Buy-in",
    line: "You understand the advice but don’t yet believe it helps the call.",
  },
  adherence: {
    name: "Adherence",
    line: "The issue is trying it on calls, not knowing it.",
  },
  skill_dependency: {
    name: "Skill dependency",
    line: "An earlier part of the call is causing this.",
  },
  context_specific: {
    name: "Context-specific",
    line: "This happens mainly in certain situations.",
  },
  uncertain: {
    name: "Not clear yet",
    line: "We don’t have enough evidence yet to say why.",
  },
};

export const gapCopy = (gap: string) => GAP_COPY[gap] ?? GAP_COPY.uncertain;

/** High / Medium / Low; nothing when we cannot say (spec: "only if useful"). */
export const CONFIDENCE_COPY: Record<string, string | undefined> = {
  high: "High",
  medium: "Moderate",
  moderate: "Moderate",
  low: "Low",
};

export const BETTER = {
  dipak: "Dipak’s coaching",
  textLesson: "Text lesson",
  simpleIdea: "Simple idea",
  framework: "Framework",
  frameworkNote: "A thinking guide, not a word-for-word script.",
  yourCall: "Your call",
  yourCallAt: (clock: string) => `Your call · ${clock}`,
  betterDirection: "Better direction",
  wording: "Possible wording, in your own style",
  strength: "Use your strength",
  strengthAcross:
    "From your latest call where the report noted one. One call doesn’t make it a proven strength yet.",
  strengthCall: "You already did this on the call.",
  strengthKeep: "Keep it while you practise the mission.",
  fullLesson: "Read the full lesson",
  whyMatters: "Why it matters",
  good: "What good looks like",
  whenUse: "When to use it",
  whenNot: "When not to use it",
  checklist: "Quick checklist",
  mission: "Your next-call mission",
} as const;

export const NEXT = {
  mission: "Your next-call mission",
  since: (date: string) => `Active since ${date}`,
  useWhen: "Use it when",
  doneWhen: "Done when",
  cue: "Pre-call cue",
  practice: "Practice",
  minutes: (minutes: number) => `${minutes} min`,
  success: "Success",
  stays: "It stays until real calls show the change.",
  oneCall:
    "One call gives a suggestion, not a pattern. My coaching follows all your calls.",
} as const;

/** Brain 3.0 mastery states (spec pillar 5), in the learner's words. */
export const MASTERY_COPY: Record<MasteryState, string> = {
  not_enough_evidence: "Not Enough Evidence",
  emerging: "Emerging",
  developing: "Developing",
  consistent: "Consistent",
  strong: "Strong",
  mastered: "Mastered",
  regression_detected: "Regression Detected",
  re_stabilizing: "Re-stabilizing",
};

/** Arrows only when the server says the trend is known (spec 5 guidance). */
export const TREND_ARROW: Record<string, string> = {
  improving: " ↑",
  declining: " ↓",
  stable: " →",
};

/** What one call's report said about the focus skill. Never "success". */
export const POINT_COPY: Record<ProgressPoint["state"], string> = {
  suggested: "Came up again",
  no_suggestion: "Skill used, nothing to fix",
  not_covered: "Didn’t come up",
};

export const PROGRESS = {
  status: "Status",
  recent: "Recent",
  previous: "Previous",
  trend: "Trend",
  journey: "Mastery journey",
  calls: "Your calls on this skill, oldest first",
  callsLabel: "Your calls on this skill",
  oldestFirst: "oldest first",
  correct: (correct: number, relevant: number) =>
    `Done well in ${correct} of ${relevant} relevant moments`,
  sinceMission: (quiet: number, after: number) =>
    `Since your mission started: ${quiet} of ${after} call${after === 1 ? "" : "s"} used this skill with nothing to fix. Not proof of change yet.`,
  noCallSince:
    "No call on this skill since your mission started. Your next call is the first check.",
  how: "How progress is measured",
  baseline: "Previous baseline",
  achieved: "Best so far",
  watching:
    "Watching a lesson is not progress. Progress comes from real calls.",
} as const;

export const PATH = {
  now: "Working on now",
  next: "Likely next",
  later: "Later",
  maintain: "Keep strong",
  nextFallback: "Your next calls decide",
  laterFallback: "Your future calls will guide this",
  dynamic: "This path changes when new calls change the priority.",
} as const;

export const CALLS = {
  title: "Coaching for each call",
  recent: (count: number) => `${count} recent`,
  label: "Your recent calls",
  analysing: "Analysing…",
  unavailable: "No usable report",
  fallback: "One practice for your next call",
  showAll: (count: number) => `Show all ${count} calls`,
} as const;

export const ABOUT = "About this coaching";

/** Team coaching for owners and admins: totals, objections, shared reps. */
export const TEAM = {
  calls: "Analysed calls",
  top: "Top area to work on",
  noneYet: "No suggestions yet",
  areas: "Skills to work on",
  areasNote: "Across the team",
  pending: "Still analysing",
  pendingNote: "Reports on the way",
  unusable: (count: number) => `${count} couldn’t be read`,
  sandboxReps: "Fictional reps",
  sandboxRepsNote: "AC Sandbox, only you",
  practise: "What the team should work on",
  practiseSub: "Share of calls",
  practiseNote:
    "How many calls had a report suggestion in each skill. Not a score and not mastery. Updates after every call.",
  sandboxNote:
    "Each fictional call carries one authored focus. Counts are those focuses, not measured mistakes or mastery.",
  emptyTitle: "No team suggestions yet",
  emptyText:
    "Each analysed report can add one. A skill with no evidence never counts as a team weakness.",
  objections: "Objections your team hears",
  objectionsSub: (calls: number) =>
    `In ${calls} mapped call${calls === 1 ? "" : "s"}`,
  objectionsNote:
    "Left open: the reply dodged or skipped it. Counts only — never the words or who said them.",
  noObjections: "No objections in these calls",
  noObjectionsText: "Each analysed call’s map lists the buyer’s objections.",
  who: "Who needs help with what",
  sharedSub: (count: number) => `${count} shared with you`,
  fictionalSub: (count: number) =>
    `${count} fictional ${count === 1 ? "rep" : "reps"}`,
  sharedOnly: "Shared only",
  namedTitle: "Named coaching appears when a rep shares it",
  namedText:
    "Each rep’s focus, reason and mission stay private until they share them with one tap. They can stop sharing at any time.",
  privateTitle: "Private by default",
  privateBadge: "Anonymous",
  privateWho: "Owners and admins see these totals",
  privateText:
    "Totals never name a rep or show their calls, quotes, focus or mission. Owners and admins follow the same rule as everyone else.",
  privateShare:
    "A rep can share their coaching with you in one tap, and stop at any time.",
  sandboxTitle: "Fictional AC Sandbox",
  sandboxWho: "Only you see these reps",
  sandboxText:
    "These reps, calls and coaching are fictional records you imported. Each call carries one authored focus.",
  sandboxPrivate:
    "Real reps’ coaching stays private until they share it; their totals never name anyone.",
  insightsTitle: "Every call, over time",
  insights: "Open Insights",
  insightsNote: "Trends, outcomes and people across all calls",
  counted: "How these totals are counted",
} as const;
