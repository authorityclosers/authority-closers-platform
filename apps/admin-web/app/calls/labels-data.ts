/**
 * Reviewer labels on a call (GET/POST /v1/admin/conversation/calls/{id}/labels)
 * and the gold-set view (GET /v1/admin/conversation/gold). Internal reviewer
 * records: never an official score (AC-SVAL) and never shown to reps.
 */
import { read } from "../lib/read";
import { REPORT_PILLARS, REPORT_SKILLS } from "./report-pillars";

export const REVIEW_STATES = [
  "new",
  "needs_review",
  "disputed",
  "done",
] as const;
export type ReviewState = (typeof REVIEW_STATES)[number];
export const REVIEW_LABEL: Record<ReviewState, string> = {
  new: "New",
  needs_review: "Needs review",
  disputed: "Disputed",
  done: "Done",
};
export const REVIEW_TONE: Record<
  ReviewState,
  "neutral" | "accent" | "bad" | "good"
> = {
  new: "neutral",
  needs_review: "accent",
  disputed: "bad",
  done: "good",
};
export const asReviewState = (value: unknown): ReviewState =>
  REVIEW_STATES.includes(value as ReviewState) ? (value as ReviewState) : "new";

export type Verdict = "correct" | "partly" | "wrong";
export const VERDICTS: { value: Verdict; label: string; key: string }[] = [
  { value: "correct", label: "Correct", key: "1" },
  { value: "partly", label: "Partly", key: "2" },
  { value: "wrong", label: "Wrong", key: "3" },
];

/** What a reviewer can judge: the six pillars, each skill, the coaching and the transcript. */
export const VERDICT_SECTIONS: { id: string; label: string; group: string }[] =
  [
    ...REPORT_PILLARS.map((pillar, index) => ({
      id: `pillar:${pillar.id}`,
      label: `${index + 1}. ${pillar.label}`,
      group: "Report pillars",
    })),
    ...REPORT_SKILLS.map(([id, label]) => ({
      id: `skill:${id}`,
      label,
      group: "Skills",
    })),
    { id: "coaching:focus", label: "Coaching focus", group: "Coaching" },
    {
      id: "coaching:practice",
      label: "Practice and mission",
      group: "Coaching",
    },
    { id: "transcript", label: "Transcript and speakers", group: "Transcript" },
  ];

export const GAP_TYPES: { value: string; label: string }[] = [
  { value: "knowledge", label: "Knowledge" },
  { value: "recognition_judgment", label: "Recognition / judgment" },
  { value: "execution", label: "Execution" },
  { value: "habit_recall", label: "Habit / recall" },
  { value: "confidence", label: "Confidence" },
  { value: "cognitive_load", label: "Cognitive load" },
  { value: "belief_buy_in", label: "Belief / buy-in" },
  { value: "adherence", label: "Adherence" },
  { value: "skill_dependency", label: "Skill dependency" },
  { value: "context_specific", label: "Context-specific" },
  { value: "uncertain", label: "Uncertain" },
];
export const SKILL_STATES: { value: string; label: string }[] = [
  { value: "strongly_demonstrated", label: "Strongly Demonstrated" },
  { value: "observed", label: "Observed" },
  { value: "needs_attention", label: "Needs Attention" },
  { value: "insufficient_evidence", label: "Not Enough Evidence" },
  { value: "not_applicable", label: "Not Applicable" },
];

export type Label = {
  id: string;
  kind: "verdict" | "note" | "gold" | "data_use" | "status";
  runId: string | null;
  section: string | null;
  value: Record<string, unknown>;
  supersedesId: string | null;
  actor: string;
  createdAt: string | null;
};
export type Labels = {
  state: ReviewState;
  effective: Label[];
  history: Label[];
};

const KINDS = new Set(["verdict", "note", "gold", "data_use", "status"]);
function label(raw: unknown): Label | null {
  const row = read.object(raw);
  const kind = read.string(row.kind);
  if (!KINDS.has(kind)) return null;
  return {
    id: read.string(row.id),
    kind: kind as Label["kind"],
    runId: read.optionalString(row.run_id),
    section: read.optionalString(row.section),
    value: read.object(row.value),
    supersedesId: read.optionalString(row.supersedes_id),
    actor: read.string(row.actor_person_id),
    createdAt: read.optionalString(row.created_at),
  };
}
const labels = (raw: unknown) =>
  read.array(raw).flatMap((item) => {
    const value = label(item);
    return value ? [value] : [];
  });

export function normalizeLabels(raw: unknown): Labels {
  const body = read.object(raw);
  return {
    state: asReviewState(body.review_state),
    effective: labels(body.effective),
    history: labels(body.history),
  };
}

/** My standing verdict per section for this run. */
export function myVerdicts(
  data: Labels,
  runId: string,
  actor: string | null,
): Record<string, Verdict> {
  const verdicts: Record<string, Verdict> = {};
  for (const row of data.effective)
    if (
      row.kind === "verdict" &&
      row.runId === runId &&
      row.section &&
      (!actor || row.actor === actor)
    ) {
      const value = row.value.verdict;
      if (value === "correct" || value === "partly" || value === "wrong")
        verdicts[row.section] = value;
    }
  return verdicts;
}

/** The latest standing label of one kind (gold, data use, status). */
export const latest = (data: Labels, kind: Label["kind"]) =>
  [...data.effective].reverse().find((row) => row.kind === kind) ?? null;

/* ---------- Gold set ---------- */

export type Gold = {
  note: string;
  calls: {
    recordingId: string;
    runId: string | null;
    prompt: string | null;
    labelledAt: string | null;
    value: Record<string, unknown>;
    dataUse: string | null;
  }[];
  dataUse: { training: number; test: number };
  skills: { skill: string; compared: number; agreed: number }[];
  pillars: {
    section: string;
    correct: number;
    partly: number;
    wrong: number;
  }[];
  byPrompt: {
    prompt: string;
    compared: number;
    agreed: number;
    correct: number;
    partly: number;
    wrong: number;
  }[];
};

export function normalizeGold(raw: unknown): Gold {
  const body = read.object(raw);
  const dataUse = read.object(body.data_use);
  return {
    note: read.string(
      body.note,
      "Internal reviewer agreement. Not an official score.",
    ),
    calls: read.array(body.calls).map((item) => {
      const row = read.object(item);
      return {
        recordingId: read.string(row.recording_id),
        runId: read.optionalString(row.run_id),
        prompt: read.optionalString(row.prompt_revision),
        labelledAt: read.optionalString(row.labelled_at),
        value: read.object(row.value),
        dataUse: read.optionalString(row.data_use),
      };
    }),
    dataUse: {
      training: read.number(dataUse.training),
      test: read.number(dataUse.test),
    },
    skills: read.array(body.skills).map((item) => {
      const row = read.object(item);
      return {
        skill: read.string(row.skill),
        compared: read.number(row.compared),
        agreed: read.number(row.agreed),
      };
    }),
    pillars: read.array(body.pillars).map((item) => {
      const row = read.object(item);
      return {
        section: read.string(row.section),
        correct: read.number(row.correct),
        partly: read.number(row.partly),
        wrong: read.number(row.wrong),
      };
    }),
    byPrompt: read.array(body.by_prompt).map((item) => {
      const row = read.object(item);
      return {
        prompt: read.string(row.prompt_revision, "unknown"),
        compared: read.number(row.skills_compared),
        agreed: read.number(row.skills_agreed),
        correct: read.number(row.correct),
        partly: read.number(row.partly),
        wrong: read.number(row.wrong),
      };
    }),
  };
}

export const share = (part: number, whole: number) =>
  whole ? `${Math.round((part / whole) * 100)}%` : "–";

export const sectionLabel = (section: string) =>
  VERDICT_SECTIONS.find((item) => item.id === section)?.label ?? section;
