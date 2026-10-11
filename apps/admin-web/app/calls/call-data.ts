/**
 * The call review console's data: normalizers for the admin call API
 * (GET /v1/admin/conversation/calls, /calls/{id}, /runs/{id}/review) that give
 * every missing field a default, and the labels screens show. Pure.
 */
import { normalizeFailedJob, type FailedJob } from "../health/health-data";
import { read } from "../lib/read";

export const CALL_STATUSES = [
  "ready",
  "analysing",
  "failed",
  "uploaded",
] as const;
export type CallStatus = (typeof CALL_STATUSES)[number];

export const STATUS_LABEL: Record<CallStatus, string> = {
  ready: "Report ready",
  analysing: "Analysing",
  failed: "Failed",
  uploaded: "Uploaded",
};
export const STATUS_TONE: Record<
  CallStatus,
  "good" | "accent" | "bad" | "neutral"
> = {
  ready: "good",
  analysing: "accent",
  failed: "bad",
  uploaded: "neutral",
};

export const LANGUAGE_LABEL: Record<string, string> = {
  en: "English",
  "hi-Deva+en": "Hindi + English",
  "mr-Deva+en": "Marathi + English",
};
export const languageLabel = (value: string | null) =>
  value ? (LANGUAGE_LABEL[value] ?? value) : "Not recorded";

const asStatus = (value: unknown): CallStatus =>
  CALL_STATUSES.includes(value as CallStatus)
    ? (value as CallStatus)
    : "uploaded";

/* ---------- Queue ---------- */

export type Person = {
  personId: string | null;
  label: string;
  email: string | null;
  kind: string;
};
export type QueueItem = {
  recordingId: string;
  uploadedAt: string | null;
  organisation: { id: string; name: string };
  rep: Person;
  status: CallStatus;
  language: string | null;
  durationMs: number | null;
  provider: string | null;
  model: string | null;
  promptRevision: string | null;
  runs: number;
  reportRunId: string | null;
};
export type Facet = { value: string; label: string; count: number };
export type Queue = {
  items: QueueItem[];
  total: number;
  counts: Record<CallStatus, number>;
  facets: {
    organisations: Facet[];
    reps: Facet[];
    languages: Facet[];
    providers: Facet[];
  };
  nextCursor: string | null;
  truncated: boolean;
  windowSize: number;
};

function person(raw: unknown): Person {
  const row = read.object(raw);
  return {
    personId: read.optionalString(row.person_id),
    label: read.string(row.label, "Unknown rep"),
    email: read.optionalString(row.email),
    kind: read.string(row.kind, "learner"),
  };
}

const facets = (raw: unknown): Facet[] =>
  read.array(raw).map((item) => {
    const row = read.object(item);
    return {
      value: read.string(row.value),
      label: read.string(row.label, read.string(row.value)),
      count: read.number(row.count),
    };
  });

export function normalizeQueue(raw: unknown): Queue {
  const body = read.object(raw);
  const counts = read.object(body.counts);
  const facetBody = read.object(body.facets);
  const window = read.object(body.window);
  return {
    items: read.array(body.items).map((item) => {
      const row = read.object(item);
      const organisation = read.object(row.organisation);
      return {
        recordingId: read.string(row.recording_id),
        uploadedAt: read.optionalString(row.uploaded_at),
        organisation: {
          id: read.string(organisation.id),
          name: read.string(organisation.name, "Unknown organisation"),
        },
        rep: person(row.rep),
        status: asStatus(row.status),
        language: read.optionalString(row.language),
        durationMs: read.optionalNumber(row.duration_ms),
        provider: read.optionalString(row.provider),
        model: read.optionalString(row.model),
        promptRevision: read.optionalString(row.prompt_revision),
        runs: read.number(row.runs),
        reportRunId: read.optionalString(row.report_run_id),
      };
    }),
    total: read.number(body.total),
    counts: Object.fromEntries(
      CALL_STATUSES.map((status) => [status, read.number(counts[status])]),
    ) as Record<CallStatus, number>,
    facets: {
      organisations: facets(facetBody.organisations),
      reps: facets(facetBody.reps),
      languages: facets(facetBody.languages),
      providers: facets(facetBody.providers),
    },
    nextCursor: read.optionalString(body.next_cursor),
    truncated: read.boolean(window.truncated),
    windowSize: read.number(window.size, 500),
  };
}

/* ---------- One call and its runs ---------- */

export type Run = {
  id: string;
  state: string;
  createdAt: string | null;
  completedAt: string | null;
  reportId: string | null;
  language: string | null;
  provider: string | null;
  model: string | null;
  transcriptionProvider: string | null;
  promptRevision: string | null;
  factPromptRevision: string | null;
  settingsRevision: number | null;
  outputProfile: string | null;
  retryOf: string | null;
};
export type Call = {
  recordingId: string;
  uploadedAt: string | null;
  organisation: { id: string; name: string };
  rep: Person;
  status: CallStatus;
  runs: Run[];
  /** Dead-lettered steps, newest first; the admin job retry may run the retryable ones. */
  failedJobs: FailedJob[];
};

export function normalizeCall(raw: unknown): Call {
  const body = read.object(raw);
  const organisation = read.object(body.organisation);
  return {
    recordingId: read.string(body.recording_id),
    uploadedAt: read.optionalString(body.uploaded_at),
    organisation: {
      id: read.string(organisation.id),
      name: read.string(organisation.name, "Unknown organisation"),
    },
    rep: person(body.rep),
    status: asStatus(body.status),
    runs: read.array(body.runs).map((item) => {
      const row = read.object(item);
      return {
        id: read.string(row.id),
        state: read.string(row.state, "unknown"),
        createdAt: read.optionalString(row.created_at),
        completedAt: read.optionalString(row.completed_at),
        reportId: read.optionalString(row.report_id),
        language: read.optionalString(row.language),
        provider: read.optionalString(row.provider),
        model: read.optionalString(row.model),
        transcriptionProvider: read.optionalString(row.transcription_provider),
        promptRevision: read.optionalString(row.prompt_revision),
        factPromptRevision: read.optionalString(row.fact_prompt_revision),
        settingsRevision: read.optionalNumber(row.analysis_settings_revision),
        outputProfile: read.optionalString(row.output_profile),
        retryOf: read.optionalString(row.retry_of),
      };
    }),
    failedJobs: read.array(body.failed_jobs).map(normalizeFailedJob),
  };
}

/** The run to open: the one asked for if it has a report, else the newest with one. */
export function pickRun(call: Call, wanted: string | undefined): Run | null {
  const reported = call.runs.filter((run) => run.reportId);
  return reported.find((run) => run.id === wanted) ?? reported[0] ?? null;
}

/* ---------- One run's review bundle ---------- */

export type Evidence = {
  segmentId: string;
  quote: string;
  startMs: number;
  endMs: number;
};
export type Finding = {
  title: string;
  explanation: string;
  evidence: Evidence[];
};
export type Dimension = {
  id: string;
  label: string;
  status: string;
  callState: string | null;
  observation: string;
  evidence: Evidence[];
};
export type Note = { text: string; evidence: Evidence[] };
export type Overview = {
  diagnosis: Note | null;
  outcome: (Note & { kind: string }) | null;
  strengthDetails: { findingIndex: number; whyItMatters: string }[];
  improvementDetails: {
    findingIndex: number;
    whatHappened: Note;
    whyItMatters: string;
    replacementBehavior: string;
  }[];
  goldenMoments: {
    strengthIndex: number;
    evidenceIndex: number;
    whyEffective: string;
  }[];
  rewatch: (Note & { purpose: string })[];
  conversationChange: {
    before: Note;
    change: Note;
    after: Note;
    possibleEffect: string;
  } | null;
  nextCallFocus: { behavior: string; target: string } | null;
  practiceDrill: { instructions: string; successCondition: string } | null;
  finalAssessment: {
    repeat: string;
    fixFirst: string;
    nextFocus: string;
    assessment: string;
  } | null;
};
export type Story = {
  phases: { name: string; startMs: number }[];
  outcome: {
    kind: string;
    nextStepRung: string;
    nextStepWhen: string | null;
    evidence: Evidence[];
  };
  nextStep: Note | null;
  prospectTasks: Note[];
  prospectCommitments: Note[];
  sellerCommitments: (Note & { dueText: string | null })[];
};
export type Report = {
  summary: string;
  summaryEvidence: Evidence[];
  verdict: string;
  verdictEvidence: Evidence[];
  strengths: Finding[];
  improvements: Finding[];
  missedOpportunities: Finding[];
  objectionAnalysis: Finding[];
  closingAnalysis: Finding[];
  dimensions: Dimension[];
  sections: { number: number; title: string; required: string }[];
  overview: Overview | null;
  speakers: Record<string, string>;
  story: Story | null;
};
export type Segment = {
  id: string;
  speakerId: string | null;
  startMs: number;
  endMs: number;
  text: string;
};
export type Waveform = {
  durationMs: number;
  points: { startMs: number; level: number | null }[];
};
export type SpeakerMetric = {
  talkMs: number;
  talkShare: number | null;
  questions: number;
  questionsPerMinute: number | null;
  cutIns: number;
  longestMonologueMs: number;
};
export type Metrics = {
  timeUsedMs: number;
  speakers: Record<string, SpeakerMetric>;
};
export type Bundle = {
  runId: string;
  recordingId: string;
  reportId: string;
  retentionUntil: string | null;
  report: Report;
  transcript: { revision: string; segments: Segment[] };
  waveform: Waveform | null;
  metrics: Metrics | null;
  audioUrl: string;
};

export function evidence(raw: unknown): Evidence[] {
  return read.array(raw).flatMap((item) => {
    const row = read.object(item);
    const segmentId = read.string(row.segment_id);
    if (!segmentId) return [];
    return [
      {
        segmentId,
        quote: read.string(row.quote),
        startMs: read.number(row.start_ms),
        endMs: read.number(row.end_ms),
      },
    ];
  });
}

const note = (raw: unknown): Note | null => {
  const row = read.object(raw);
  const text = read.string(row.text);
  return text ? { text, evidence: evidence(row.evidence) } : null;
};
const notes = (raw: unknown): Note[] =>
  read.array(raw).flatMap((item) => {
    const value = note(item);
    return value ? [value] : [];
  });
const findings = (raw: unknown): Finding[] =>
  read.array(raw).map((item) => {
    const row = read.object(item);
    return {
      title: read.string(row.title, "Untitled finding"),
      explanation: read.string(row.explanation),
      evidence: evidence(row.evidence),
    };
  });

function overview(raw: unknown): Overview | null {
  if (raw === null || raw === undefined) return null;
  const body = read.object(raw);
  const outcome = read.object(body.outcome);
  const change = body.conversation_change
    ? read.object(body.conversation_change)
    : null;
  const focus = body.next_call_focus ? read.object(body.next_call_focus) : null;
  const drill = body.practice ? read.object(body.practice) : null;
  const assessment = body.final_assessment
    ? read.object(body.final_assessment)
    : null;
  const outcomeNote = note(body.outcome);
  return {
    diagnosis: note(body.diagnosis),
    outcome: outcomeNote
      ? { ...outcomeNote, kind: read.string(outcome.kind, "unclear") }
      : null,
    strengthDetails: read.array(body.strength_details).map((item) => {
      const row = read.object(item);
      return {
        findingIndex: read.number(row.finding_index, -1),
        whyItMatters: read.string(row.why_it_matters),
      };
    }),
    improvementDetails: read.array(body.improvement_details).map((item) => {
      const row = read.object(item);
      return {
        findingIndex: read.number(row.finding_index, -1),
        whatHappened: note(row.what_happened) ?? { text: "", evidence: [] },
        whyItMatters: read.string(row.why_it_matters),
        replacementBehavior: read.string(row.replacement_behavior),
      };
    }),
    goldenMoments: read.array(body.golden_moments).map((item) => {
      const row = read.object(item);
      return {
        strengthIndex: read.number(row.strength_index, -1),
        evidenceIndex: read.number(row.evidence_index, -1),
        whyEffective: read.string(row.why_effective),
      };
    }),
    rewatch: read.array(body.rewatch).flatMap((item) => {
      const value = note(item);
      return value
        ? [
            {
              ...value,
              purpose: read.string(read.object(item).purpose, "watch"),
            },
          ]
        : [];
    }),
    conversationChange: change
      ? {
          before: note(change.before) ?? { text: "", evidence: [] },
          change: note(change.change) ?? { text: "", evidence: [] },
          after: note(change.after) ?? { text: "", evidence: [] },
          possibleEffect: read.string(change.possible_effect),
        }
      : null,
    nextCallFocus: focus
      ? {
          behavior: read.string(focus.behavior),
          target: read.string(focus.target),
        }
      : null,
    practiceDrill: drill
      ? {
          instructions: read.string(drill.instructions),
          successCondition: read.string(drill.success_condition),
        }
      : null,
    finalAssessment: assessment
      ? {
          repeat: read.string(assessment.repeat),
          fixFirst: read.string(assessment.fix_first),
          nextFocus: read.string(assessment.next_focus),
          assessment: read.string(assessment.assessment),
        }
      : null,
  };
}

function story(raw: unknown): Story | null {
  if (raw === null || raw === undefined) return null;
  const body = read.object(raw);
  const outcome = read.object(body.outcome);
  return {
    phases: read.array(body.phases).map((item) => {
      const row = read.object(item);
      return {
        name: read.string(row.name),
        startMs: read.number(row.start_ms),
      };
    }),
    outcome: {
      kind: read.string(outcome.kind, "none"),
      nextStepRung: read.string(outcome.next_step_rung, "none"),
      nextStepWhen: read.optionalString(outcome.next_step_when),
      evidence: evidence(outcome.evidence),
    },
    nextStep: note(body.next_step),
    prospectTasks: notes(body.prospect_tasks),
    prospectCommitments: notes(body.prospect_commitments),
    sellerCommitments: read.array(body.seller_commitments).flatMap((item) => {
      const value = note(item);
      return value
        ? [
            {
              ...value,
              dueText: read.optionalString(read.object(item).due_text),
            },
          ]
        : [];
    }),
  };
}

export function normalizeReport(
  raw: unknown,
  storyRaw: unknown = null,
): Report {
  const body = read.object(raw);
  const callMap = read.object(body.call_map);
  const speakers: Record<string, string> = {};
  for (const item of read.array(callMap.speakers)) {
    const row = read.object(item);
    const id = read.string(row.speaker_id);
    if (id) speakers[id] = read.string(row.role, "other");
  }
  return {
    summary: read.string(body.summary),
    summaryEvidence: evidence(body.summary_evidence),
    verdict: read.string(body.verdict),
    verdictEvidence: evidence(body.verdict_evidence),
    strengths: findings(body.strengths),
    improvements: findings(body.improvements),
    missedOpportunities: findings(body.missed_opportunities),
    objectionAnalysis: findings(body.objection_analysis),
    closingAnalysis: findings(body.closing_analysis),
    dimensions: read.array(body.dimensions).map((item) => {
      const row = read.object(item);
      return {
        id: read.string(row.dimension_id),
        label: read.string(row.label, read.string(row.dimension_id)),
        status: read.string(row.status, "unknown"),
        callState: read.optionalString(row.call_state),
        observation: read.string(row.observation),
        evidence: evidence(row.evidence),
      };
    }),
    sections: read.array(body.report_sections).map((item) => {
      const row = read.object(item);
      return {
        number: read.number(row.number),
        title: read.string(row.title),
        required: read.string(row.required),
      };
    }),
    overview: overview(body.overview),
    speakers,
    story: story(storyRaw),
  };
}

export function normalizeBundle(raw: unknown): Bundle {
  const body = read.object(raw);
  const transcript = read.object(body.transcript);
  const waveformBody = body.waveform ? read.object(body.waveform) : null;
  const metricsBody = body.metrics ? read.object(body.metrics) : null;
  const runId = read.string(body.run_id);
  return {
    runId,
    recordingId: read.string(body.recording_id),
    reportId: read.string(body.report_id),
    retentionUntil: read.optionalString(body.retention_until),
    report: normalizeReport(body.report, body.story),
    transcript: {
      revision: read.string(transcript.revision),
      segments: read
        .array(transcript.segments)
        .map((item) => {
          const row = read.object(item);
          return {
            id: read.string(row.id),
            speakerId: read.optionalString(row.speaker_id),
            startMs: read.number(row.start_ms),
            endMs: read.number(row.end_ms),
            text: read.string(row.text),
          };
        })
        .filter((segment) => segment.id),
    },
    waveform: waveformBody
      ? {
          durationMs: read.number(waveformBody.duration_ms),
          points: read.array(waveformBody.points).map((item) => {
            const row = read.object(item);
            return {
              startMs: read.number(row.start_ms),
              level: read.optionalNumber(row.level),
            };
          }),
        }
      : null,
    metrics: metricsBody
      ? {
          timeUsedMs: read.number(metricsBody.time_used_ms),
          speakers: Object.fromEntries(
            Object.entries(read.object(metricsBody.speakers)).map(
              ([id, value]) => {
                const row = read.object(value);
                return [
                  id,
                  {
                    talkMs: read.number(row.talk_ms),
                    talkShare: read.optionalNumber(row.talk_share),
                    questions: read.number(row.questions),
                    questionsPerMinute: read.optionalNumber(
                      row.questions_per_minute,
                    ),
                    cutIns: read.number(row.cut_ins),
                    longestMonologueMs: read.number(row.longest_monologue_ms),
                  },
                ];
              },
            ),
          ),
        }
      : null,
    // Only the admin route for this run; never a URL from the payload.
    audioUrl: runId
      ? `/v1/admin/conversation/runs/${encodeURIComponent(runId)}/source`
      : "",
  };
}

/* ---------- Speakers and time ---------- */

const ROLE_LABEL: Record<string, string> = {
  seller: "Rep",
  prospect: "Prospect",
  other: "Other",
};

/** "Rep" / "Prospect" when the report's call map says so, else "Speaker 1", "Speaker 2"... */
export function speakerNames(
  report: Report,
  segments: Segment[],
): Record<string, string> {
  const order: string[] = [];
  for (const segment of segments)
    if (segment.speakerId && !order.includes(segment.speakerId))
      order.push(segment.speakerId);
  const names: Record<string, string> = {};
  const used = new Map<string, number>();
  for (const [index, id] of order.entries()) {
    const role = report.speakers[id];
    const base = role ? (ROLE_LABEL[role] ?? "Other") : `Speaker ${index + 1}`;
    const seen = used.get(base) ?? 0;
    used.set(base, seen + 1);
    names[id] = seen ? `${base} ${seen + 1}` : base;
  }
  return names;
}

export function clock(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0)
    return "–:––";
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`
    : `${minutes}:${seconds}`;
}

/** The segment playing at `ms`: the last one that started at or before it. */
export function segmentAt(segments: Segment[], ms: number): number {
  let low = 0;
  let high = segments.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if ((segments[middle]?.startMs ?? Infinity) <= ms) {
      found = middle;
      low = middle + 1;
    } else high = middle - 1;
  }
  return found;
}

const DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});
/** Times read in India time, the team's clock, on server and browser alike. */
export const when = (iso: string | null) => {
  if (!iso) return "Unknown time";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "Unknown time" : DATE.format(date);
};
