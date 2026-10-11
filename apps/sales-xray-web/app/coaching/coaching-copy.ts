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

/**
 * Another rep's coaching (a fictional AC Sandbox rep, or a rep who shared
 * theirs): the same pillars, said about "them" instead of "you".
 */
export const THEIR_PILLARS: Record<CoachingPillarId, CoachingPillarCopy> = {
  focus: {
    number: 1,
    label: "What They Should Work On Now",
    subtitle: "Their highest-priority improvement.",
  },
  why: COACHING_PILLARS.why,
  better: {
    ...COACHING_PILLARS.better,
    subtitle:
      "Learn the better approach using their own calls and Dipak’s coaching.",
  },
  next: { ...COACHING_PILLARS.next, label: "Try This on Their Next Call" },
  progress: {
    ...COACHING_PILLARS.progress,
    label: "See How They’re Improving",
  },
  path: {
    ...COACHING_PILLARS.path,
    subtitle: "See the next stage of their development.",
  },
};

/** A fictional AC Sandbox rep's call, read by the person who imported it. */
export const THEIR_CALL_PILLARS: typeof CALL_PILLARS = {
  focus: { ...CALL_PILLARS.focus, label: THEIR_PILLARS.focus.label },
  why: CALL_PILLARS.why,
  better: THEIR_PILLARS.better,
  next: THEIR_PILLARS.next,
};

export const FOCUS = {
  current: "Current focus",
  status: "Status",
  whyMatters: "Why this matters",
  whyFocus: "Why this focus",
  onNextCall: "On your next call",
  seeMission: "See the mission",
  take: "Hear Dipak’s take",
  active: "Current focus",
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
  moments: "Moments from your calls",
  callEvidence: "From this call",
  yourContext: "Your context",
  theirContext: "Their context",
  noTimestamp: "No time was saved for this moment. Read it in the report.",
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
    name: "Too much at once",
    line: "The skill drops when several things happen at once.",
  },
  belief_buy_in: {
    name: "Not convinced yet",
    line: "You understand the advice but don’t yet believe it helps the call.",
  },
  adherence: {
    name: "Not tried yet",
    line: "The issue is trying it on calls, not knowing it.",
  },
  skill_dependency: {
    name: "Earlier step",
    line: "An earlier part of the call is causing this.",
  },
  context_specific: {
    name: "Only in some calls",
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
    "From your latest call. One call doesn’t prove a strength yet.",
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

/** Dipak's lesson card (spec 3.4 "Media card requirements"). */
export const MEDIA = {
  recommended: "Recommended for your current focus",
  /** A call's coaching and the Report: the focus is this call's, not My coaching's. */
  recommendedCall: "Recommended for this call’s focus",
  other: "Also relevant",
  why: "Why this is recommended",
  takeaways: "Read key takeaways",
  kind: (video: boolean) => (video ? "Video" : "Audio"),
  byline: "Dipak’s words",
  voice: "read by a stand-in",
  freePreview: "Free preview",
  locked: "Full coaching",
  narrationNote:
    "A stand-in voice reads Dipak’s words. Listening alone doesn’t finish your mission.",
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
  suggested: "Needed work",
  no_suggestion: "Skill used, nothing to fix",
  not_covered: "Didn’t come up",
};

/** Trend words, only when the server knows them (spec pillar 5). */
export const TREND_COPY: Record<string, string | undefined> = {
  improving: "Improving ↑",
  stable: "Stable →",
  declining: "Declining ↓",
};

/** Regression, said gently: it never erases what was achieved (spec 5). */
export const REGRESSION_COPY: Record<string, string> = {
  unknown: "Not enough calls on this skill to tell yet",
  monitor: "One unusual miss. Just watching it",
  reminder: "Slipping a little. A short reminder helps",
  recurring: "Coming back. Worth a second look",
  severe: "Back as your main focus for now",
  re_stabilizing: "Getting steady again",
};

export const PROGRESS = {
  status: "Status",
  regression: "Regression",
  recent: "Recent",
  previous: "Previous",
  trend: "Trend",
  journey: "Mastery journey",
  calls: "Your calls on this skill, oldest first",
  callsLabel: "Your calls on this skill",
  oldestFirst: "oldest first",
  /** One sentence for screen readers instead of a row per dot. */
  summary: (needed: number, used: number, missing: number) =>
    [
      `${needed} needed work`,
      used ? `${used} used the skill with nothing to fix` : null,
      missing ? `${missing} didn’t give a chance to use it` : null,
    ]
      .filter(Boolean)
      .join(", ") + ".",
  correct: (correct: number, relevant: number) =>
    `Done well in ${correct} of ${relevant} chances`,
  sinceMission: (quiet: number, after: number) =>
    `Since your mission started: ${quiet} of ${after} call${after === 1 ? "" : "s"} on this skill needed no fix. Too early to call it a change.`,
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

/**
 * Spec pillar 6, "What stopped you here?": the learner's possible answers.
 * One tap keeps the answer as their context beside the likely reason.
 */
export const REFLECTION = {
  answers: [
    "I didn’t know what to ask",
    "I noticed it later",
    "I forgot in the moment",
    "I worried it would feel like an interrogation",
    "I thought I already understood enough",
    "I moved on on purpose",
  ],
  hint: "Tap the closest answer. Only you see it unless you share your coaching.",
  saved: "Saved as your context. It shows with the likely reason.",
} as const;

/** Who sees the learner's Coaching: private until they share it. */
export const SHARING = {
  title: "Who sees your coaching",
  shared: "Shared",
  private: "Private",
  personal: "Personal workspace: only you can see this coaching.",
  sharedText: (names?: string) =>
    `Your admins can see your focus, its likely reason and your mission${names ? `: ${names}` : ""}.`,
  privateText: (names?: string) =>
    `Only you can see it. Sharing lets your admins${names ? ` (${names})` : ""} see your focus, its likely reason and your mission.`,
  stop: "Stop sharing",
  share: "Share with your admins",
  note: "Your admins can already open your calls. Sharing also shows them this page. You can stop any time.",
  unchanged: "Your sharing is shown as it is now.",
} as const;

/** Spec pillar 6: agree, disagree or add context. */
export const FEEDBACK = {
  group: "Your view",
  agree: "Agree",
  notCompletely: "Not completely",
  addContext: "Add context",
  noted: "Noted. Your mission stays the same.",
  ask: "Does this focus fit you? Tell us, or add context.",
  save: "Save",
  cancel: "Cancel",
  saving: "Saving…",
  contextHint:
    "Only you see it unless you share your coaching. It is deleted with your account.",
} as const;

/** Spec pillar 6 disagreement flow: the evidence first, then what we missed. */
export const DISAGREE = {
  basis: "This focus is based on",
  replay: "Replay them above",
  noted: "Noted. Here’s what this focus is based on. Tell us what we missed.",
  missed: "What did we miss?",
  context: "What should we know about this focus?",
} as const;

export const CALLS = {
  title: "Coaching for each call",
  recent: (count: number) => `${count} recent`,
  label: "Your recent calls",
  analysing: "Analysing…",
  unavailable: "Report couldn’t be read",
  fallback: "One practice for your next call",
  recurring: "Also on other calls",
  showAll: (count: number) => `Show all ${count} calls`,
} as const;

/** The labels on another rep's coaching that would otherwise say "you". */
const THEIR_GAP_LINES: Record<string, string> = {
  knowledge: "They need a clearer framework for what to explore here.",
  judgment: "They usually see the opportunity after the call.",
  execution: "They know what to ask but struggle to say it naturally.",
  confidence: "They avoid the question because it feels uncomfortable.",
  belief_buy_in:
    "They understand the advice but don’t yet believe it helps the call.",
};

export const THEIR = {
  onNextCall: "On their next call",
  evidence: "From their calls",
  moments: "Moments from their calls",
  call: "Their call",
  callAt: (clock: string) => `Their call · ${clock}`,
  strength: "Their strength",
  strengthAcross:
    "From their latest call. One call doesn’t prove a strength yet.",
  strengthCall: "They already did this on the call.",
  strengthKeep: "Keep it while they practise the mission.",
  mission: "Their next-call mission",
  recommended: "Recommended for their current focus",
  narrationNote:
    "A stand-in voice reads Dipak’s words. Listening alone doesn’t finish their mission.",
  calls: "Their calls on this skill, oldest first",
  callsLabel: "Their calls on this skill",
  sinceMission: (quiet: number, after: number) =>
    `Since their mission started: ${quiet} of ${after} call${after === 1 ? "" : "s"} on this skill needed no fix. Too early to call it a change.`,
  noCallSince:
    "No call on this skill since their mission started. Their next call is the first check.",
  severe: "Back as their main focus for now",
  path: "Their development path",
  nextFallback: "Their next calls decide",
  laterFallback: "Their future calls will guide this",
  recentCalls: "Their recent calls",
  callFallback: "One practice for their next call",
  oneCall: (name: string | null) =>
    `One call gives a suggestion, not a pattern. ${name ? `${name}’s` : "Their"} coaching follows all their calls.`,
  gapLine: (gap: string) => THEIR_GAP_LINES[gap] ?? gapCopy(gap).line,
} as const;

export const ABOUT = "About this coaching";

/** My coaching before a focus exists (no calls yet, or no pattern yet). */
export const START = {
  noFocus: "Start with one call’s coaching",
  noCalls: "Analyse a call to start",
  noFocusText:
    "No one skill stands out across your calls yet. Each call below has its own focus and mission.",
  noCallsText:
    "Coaching follows your own calls. Your first report brings one focus and one mission for your next call.",
  pending: (count: number) =>
    `${count} call${count === 1 ? " is" : "s are"} still being analysed.`,
  sandboxReps: (count: number) => `See ${count} fictional reps’ coaching`,
  analyse: "Analyse a call",
  sandboxNote:
    "This is AC Sandbox: Team shows the coaching of the fictional reps you imported. Your own coaching follows your own calls.",
  theirNoFocus: "Their calls don’t show one focus yet",
  theirNoCalls: "No analysed calls yet",
  theirNoFocusText:
    "Each analysed call below has its own focus and next-call mission.",
  theirNoCallsText: "Their coaching starts with their first analysed call.",
  path: "Your development path",
} as const;

/** One call's coaching: its frame, empty state and links onward. */
export const CALL = {
  title: "Coaching for this call",
  unavailable: "Unavailable",
  backToTeam: "Back to team coaching",
  backToReport: "Back to this call’s report",
  notReady: "This call’s coaching isn’t ready",
  notReadyText:
    "Its moments are hidden or not ready yet. The report shows what’s there.",
  openTeam: "Open team coaching",
  openReport: "Open the report",
  moments: "Moments from this call",
  keepGoing: "Keep going",
  moreSuggestions: (count: number) =>
    `${count} more suggestion${count === 1 ? "" : "s"} there; Coaching keeps one focus`,
  repAcross: (name: string | null) =>
    `${name ?? "This rep"}’s coaching across calls`,
  mineAcross: "My coaching across calls",
} as const;

/** This call's coaching inside the Report (its tab and states). */
export const REPORT_COACHING = {
  failed: "Coaching didn’t load",
  failedText: "Your report is fine.",
  retry: "Try again",
  chooseWorkspace:
    "Choose your signed-in workspace to see this call’s coaching.",
  unavailable: "This call’s coaching isn’t available right now.",
  otherWorkspace:
    "Coaching is unavailable in this workspace. Your report can be reopened from the call list.",
  openFull: "Open full coaching for this call",
} as const;

/** A moment's play control (spec 5.5: every moment inspectable). */
export const MOMENT = {
  withContext: "With context",
  pause: "Pause",
  playContext: "Play with context",
  pauseContext: "Pause context playback",
  play: (span: string) => `Play moment ${span}`,
  pauseMoment: (span: string) => `Pause moment ${span}`,
  retry: (span: string) => `Try audio again ${span}`,
  at: (time: string) => `Moment at ${time}`,
  audio: (time: string) => `Moment from ${time}`,
  loading: "Loading audio…",
  fictional: "Fictional call text; no audio.",
  failed: "Audio could not be played. Try audio again; the quote stays here.",
} as const;

/** Dipak's clip card controls and the full-coaching offer (spec 3.4, 11). */
export const CLIP = {
  play: "Play coaching clip",
  loading: "Loading clip…",
  pause: "Pause",
  resume: "Resume clip",
  again: "Play again",
  limit: "Preview finished",
  retry: "Try clip again",
  lockedTitle: "Part of the full coaching",
  locked: "Locked coaching clip",
  progress: "Clip progress",
  previewEnd: "End of the free preview",
  loadingShort: "Loading…",
  playing: "Playing",
  failed: "Narration is unavailable. Try again, or read the clip below.",
  previousSlide: "Previous slide",
  nextSlide: "Next slide",
  audio: "Placeholder coaching narration",
  offer: "Full coaching",
  previewDone: "That’s the free preview",
  partOfFull: "Part of Dipak’s full coaching",
  offerText:
    "Hear the complete lesson and every clip for this skill with full coaching.",
  getFull: "Get the full coaching",
} as const;

/** The Coaching page's own frame: titles, header lines and page states. */
export const PAGE = {
  mine: "My coaching",
  call: "Coaching for this call",
  team: "Team coaching",
  rep: "Rep coaching",
  mineContext: "Your focus, mission and progress across calls",
  callContext: "One focus from this call’s report",
  sandboxRep: ["Fictional AC Sandbox rep", "Only you see this"],
  sharedRep: "Shared with you. They can stop sharing at any time.",
  sandboxTeam: ["Fictional AC Sandbox reps and calls", "Only you see them"],
  teamContext: "Team totals from analysed calls, with no names",
  backToTeam: "Back to team",
  backToReport: "Back to report",
  tabTeam: "Team",
  failed: "Coaching didn’t load",
  failedText: "Your calls and reports are fine. Open a call to see its report.",
  openCall: "Open the call",
  openCalls: "Open calls",
  workspaceChanged: "Your workspace changed. Try again.",
  signIn: "Sign in for your Coaching",
  chooseWorkspace: "Choose your workspace",
  signInText:
    "Coaching follows your own analysed calls in the selected workspace.",
  signInAction: "Sign in",
  badCallLink: "This link doesn’t work. Open the call’s report again.",
  badTeamLink: "This link doesn’t work. Open Team coaching again.",
} as const;

/** The Report's fallback when this call's coaching can't be read. */
export const RETAINED = {
  keep: "Keep doing",
  reason: "From this call’s report. One call is a suggestion, not a pattern.",
  tryNext: "Try this next time",
  carry: "Carry this into the next call",
  suggested: "The report’s suggestion, not words from your call.",
  noCheck:
    "The report didn’t say how to check it. Before your next call, decide what “done” looks like.",
  none: "This report has no suggestion tied to a moment in the call. Pick a skill below to work on.",
} as const;

/** Team coaching for owners and admins: totals, objections, shared reps. */
export const TEAM = {
  allAreas: "All areas",
  repCount: (count: number) => `${count} ${count === 1 ? "rep" : "reps"}`,
  people: (count: number) => `${count} ${count === 1 ? "person" : "people"}`,
  latest: (date: string) => `Latest call ${date}.`,
  last40: "last 40",
  inView: "In this view",
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
    "How many calls had a suggestion in each skill. Not a score. Updates after every call.",
  sandboxNote:
    "Each fictional call comes with one written focus. The counts are those focuses, not real mistakes.",
  emptyTitle: "No team suggestions yet",
  emptyText:
    "Each analysed call can add one. A skill with nothing to show never counts against the team.",
  objections: "Objections your team hears",
  objectionsSub: (calls: number) =>
    `From ${calls} call${calls === 1 ? "" : "s"}`,
  objectionsNote:
    "Left open: the reply dodged or skipped it. Counts only — never the words or who said them.",
  noObjections: "No objections in these calls",
  noObjectionsText: "Buyers’ objections show here as calls are analysed.",
  who: "Who needs help with what",
  sharedSub: (count: number) => `${count} shared with you`,
  fictionalSub: (count: number) =>
    `${count} fictional ${count === 1 ? "rep" : "reps"}`,
  sharedOnly: "Shared only",
  namedTitle: "Named coaching appears when a rep shares it",
  namedText:
    "Each rep’s focus, reason and mission stay private until they share them with one tap. They can stop sharing at any time.",
  privateTitle: "Private by default",
  privateBadge: "No names",
  privateWho: "Owners and admins see these totals",
  privateText:
    "Totals never name a rep or show their calls, quotes, focus or mission. Owners and admins follow the same rule as everyone else.",
  privateShare:
    "A rep can share their coaching with you in one tap, and stop at any time.",
  sandboxTitle: "Fictional AC Sandbox",
  sandboxWho: "Only you see these reps",
  sandboxText:
    "You imported these fictional reps, calls and coaching. Each call comes with one written focus.",
  sandboxPrivate:
    "Real reps’ coaching stays private until they share it; their totals never name anyone.",
  insightsTitle: "Every call, over time",
  insights: "Open Insights",
  insightsNote: "Trends, outcomes and people across all calls",
  counted: "How these totals are counted",
} as const;
