import {
  parseDetailedOverview,
  type DetailedOverview,
} from "./overview-contract";

export const REPORT_REVIEW_STATUS = "draft_not_dipak_adjudicated" as const;

const SHA256 = /^[0-9a-f]{64}$/;
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const REPORT_STATES = new Set([
  "queued",
  "running",
  "transcribing",
  "analyzing",
  "completed",
  "failed",
  "cancelled",
]);
const DIMENSION_STATES = new Set([
  "observed",
  "insufficient_evidence",
  "not_applicable",
  "conflicted",
  "unknown",
]);
const DOCUMENTS = new Set(["Doc-1", "Doc-2", "Doc-3", "Doc-4", "Doc-5"]);

export type ReportEvidence = {
  segment_id: string;
  quote: string;
  start_ms: number;
  end_ms: number;
};

export type Finding = {
  title: string;
  explanation: string;
  evidence: ReportEvidence[];
};

export type ReportCitation = { doc: string; sections: string[] };
export type ReportDimension = {
  dimension_id: string;
  label: string;
  status: string;
  observation: string;
  citations: ReportCitation[];
};
export type ReportSection = {
  number: number;
  title: string;
  required: string;
  citations: ReportCitation[];
};

export type SalesReport = {
  /** Server projection counts only; withheld findings are never supplied here. */
  preview?: GuestReportPreview;
  overview?: DetailedOverview;
  summary: string;
  strengths: Finding[];
  missed_opportunities: Finding[];
  improvements: Finding[];
  objection_analysis: Finding[];
  closing_analysis: Finding[];
  verdict: string;
  review_status: typeof REPORT_REVIEW_STATUS;
  source_label: string;
  source_sha256: string;
  transcript_revision: string;
  dimensions: ReportDimension[];
  report_sections: ReportSection[];
};

export type RecoveryMetadata = {
  version: number;
  validation_state: "needs_correction" | "revalidated" | "corrected";
  provider_calls: 0;
  human_approved: false;
  official_score: false;
};

const PREVIEW_LIMITS = {
  strengths: 3,
  improvements: 3,
  missed_opportunities: 10,
  objection_analysis: 8,
  closing_analysis: 8,
  golden_moments: 3,
  prospect_interpretations: 3,
  rewatch: 3,
  ethics_notes: 3,
} as const;
export type PreviewSection = keyof typeof PREVIEW_LIMITS;
export type GuestReportPreview = {
  version: "guest-findings-v1";
  sections: Record<
    PreviewSection,
    {
      visible_count: number;
      total_count: number;
      hidden_count: number;
    }
  >;
};

function parsePreview(value: unknown, report: SalesReport): GuestReportPreview {
  const preview = object(value, "report_preview");
  keys(preview, ["version", "sections"], "report_preview");
  if (preview.version !== "guest-findings-v1")
    throw new ReportContractError("report_preview_version_invalid");
  const sections = object(preview.sections, "report_preview_sections");
  keys(sections, Object.keys(PREVIEW_LIMITS), "report_preview_sections");
  const counts = {} as GuestReportPreview["sections"];
  for (const name of Object.keys(PREVIEW_LIMITS) as PreviewSection[]) {
    const count = object(sections[name], "report_preview_count");
    keys(
      count,
      ["visible_count", "total_count", "hidden_count"],
      "report_preview_count",
    );
    const total = integer(
      count.total_count,
      "report_preview_total",
      0,
      PREVIEW_LIMITS[name],
    );
    const visible = integer(
      count.visible_count,
      "report_preview_visible",
      0,
      total,
    );
    const hidden = integer(
      count.hidden_count,
      "report_preview_hidden",
      0,
      total,
    );
    const collection =
      name in report
        ? report[name as keyof SalesReport]
        : report.overview?.[name as keyof DetailedOverview];
    const length = Array.isArray(collection) ? collection.length : 0;
    const expected =
      total < 2 ? total : Math.min(total - 1, Math.ceil((total * 3) / 5));
    if (
      visible !== length ||
      hidden + visible !== total ||
      (name === "golden_moments" ? visible > expected : visible !== expected) ||
      (!(name in report) && !report.overview && total !== 0)
    )
      throw new ReportContractError("report_preview_count_mismatch");
    counts[name] = {
      visible_count: visible,
      total_count: total,
      hidden_count: hidden,
    };
  }
  return { version: "guest-findings-v1", sections: counts };
}

export type Job = {
  id: string;
  state: string;
  message: string;
  report?: SalesReport;
};

export type ReportSourceBinding = {
  sourceSha256: string;
  durationMs: number;
  transcript?: Transcript;
};

export type TranscriptSegment = {
  id: string;
  speaker_id: string | null;
  start_ms: number;
  end_ms: number;
  text: string;
};

export type Transcript = {
  source_sha256: string;
  revision: string;
  timebase_id: string;
  duration_ms: number;
  segments: TranscriptSegment[];
};

export type SavedRecording = {
  id: string;
  state: string;
  source_revision: string;
  source_sha256: string;
  source_bytes: number;
  content_type: string;
  created_at: string;
  latest_run: {
    id: string;
    state: string;
    recipe_revision: string;
    provider_calls: number;
    has_report: boolean;
  } | null;
  has_report: boolean;
};

export type SavedRecordingResponse = { recordings: SavedRecording[] };

export class ReportContractError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(`The report could not be verified (${code}).`);
    this.name = "ReportContractError";
    this.code = code;
  }
}

type JsonObject = Record<string, unknown>;

function object(value: unknown, code: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new ReportContractError(code);
  return value as JsonObject;
}

function keys(value: JsonObject, expected: readonly string[], code: string) {
  const allowed = new Set(expected);
  if (Object.keys(value).some((key) => !allowed.has(key)))
    throw new ReportContractError(`${code}_unknown_field`);
}

function text(value: unknown, code: string, max: number): string {
  if (typeof value !== "string" || !value.trim() || value.length > max)
    throw new ReportContractError(`${code}_invalid`);
  return value;
}

function optionalText(value: unknown, code: string, max: number): string {
  return value === undefined ? "" : text(value, code, max);
}

function integer(
  value: unknown,
  code: string,
  min: number,
  max?: number,
): number {
  if (!Number.isInteger(value) || (value as number) < min)
    throw new ReportContractError(`${code}_invalid`);
  if (max !== undefined && (value as number) > max)
    throw new ReportContractError(`${code}_out_of_range`);
  return value as number;
}

function identifier(value: unknown, code: string): string {
  const result = text(value, code, 128);
  if (!SAFE_ID.test(result)) throw new ReportContractError(`${code}_invalid`);
  return result;
}

function array(
  value: unknown,
  code: string,
  min: number,
  max: number,
): unknown[] {
  if (!Array.isArray(value) || value.length < min || value.length > max)
    throw new ReportContractError(`${code}_invalid`);
  return value;
}

function parseCitation(value: unknown, code: string): ReportCitation {
  const citation = object(value, `${code}_invalid`);
  keys(citation, ["doc", "sections"], code);
  const doc = text(citation.doc, `${code}_doc`, 16);
  if (!DOCUMENTS.has(doc)) throw new ReportContractError(`${code}_doc_invalid`);
  const sections = array(citation.sections, `${code}_sections`, 1, 8).map(
    (section, index) => text(section, `${code}_section_${index}`, 160),
  );
  return { doc, sections };
}

function parseEvidence(
  value: unknown,
  code: string,
  durationMs: number,
  bindingTranscript?: Transcript,
): ReportEvidence {
  const evidence = object(value, `${code}_invalid`);
  keys(evidence, ["segment_id", "quote", "start_ms", "end_ms"], code);
  const segmentId = text(evidence.segment_id, `${code}_segment_id`, 128);
  const quote = text(evidence.quote, `${code}_quote`, 2_000);
  const startMs = integer(evidence.start_ms, `${code}_start_ms`, 0, durationMs);
  const endMs = integer(evidence.end_ms, `${code}_end_ms`, 1, durationMs);
  if (endMs <= startMs) throw new ReportContractError(`${code}_timing_invalid`);
  if (bindingTranscript) {
    const segment = bindingTranscript.segments.find(
      (candidate) => candidate.id === segmentId,
    );
    if (!segment) throw new ReportContractError(`${code}_segment_unknown`);
    if (!segment.text.includes(quote))
      throw new ReportContractError(`${code}_quote_mismatch`);
    if (startMs < segment.start_ms || endMs > segment.end_ms)
      throw new ReportContractError(`${code}_segment_timing_mismatch`);
  }
  return {
    segment_id: segmentId,
    quote,
    start_ms: startMs,
    end_ms: endMs,
  };
}

function parseFinding(
  value: unknown,
  code: string,
  durationMs: number,
  bindingTranscript?: Transcript,
): Finding {
  const finding = object(value, `${code}_invalid`);
  keys(finding, ["title", "explanation", "evidence"], code);
  const evidence = array(finding.evidence, `${code}_evidence`, 1, 8).map(
    (entry, index) =>
      parseEvidence(
        entry,
        `${code}_evidence_${index}`,
        durationMs,
        bindingTranscript,
      ),
  );
  return {
    title: text(finding.title, `${code}_title`, 240),
    explanation: text(finding.explanation, `${code}_explanation`, 4_000),
    evidence,
  };
}

function parseDimensions(value: unknown): ReportDimension[] {
  return array(value, "report_dimensions", 8, 8).map((entry, index) => {
    const dimension = object(entry, `report_dimension_${index}`);
    keys(
      dimension,
      ["dimension_id", "label", "status", "observation", "citations"],
      `report_dimension_${index}`,
    );
    const status = text(
      dimension.status,
      `report_dimension_${index}_status`,
      32,
    );
    if (!DIMENSION_STATES.has(status))
      throw new ReportContractError(`report_dimension_${index}_status_invalid`);
    return {
      dimension_id: text(
        dimension.dimension_id,
        `report_dimension_${index}_id`,
        96,
      ),
      label: text(dimension.label, `report_dimension_${index}_label`, 160),
      status,
      observation: text(
        dimension.observation,
        `report_dimension_${index}_observation`,
        4_000,
      ),
      citations: array(
        dimension.citations,
        `report_dimension_${index}_citations`,
        1,
        8,
      ).map((citation, citationIndex) =>
        parseCitation(
          citation,
          `report_dimension_${index}_citation_${citationIndex}`,
        ),
      ),
    };
  });
}

function parseSections(value: unknown): ReportSection[] {
  return array(value, "report_sections", 9, 9).map((entry, index) => {
    const section = object(entry, `report_section_${index}`);
    keys(
      section,
      ["number", "title", "required", "citations"],
      `report_section_${index}`,
    );
    const number = integer(
      section.number,
      `report_section_${index}_number`,
      1,
      9,
    );
    if (number !== index + 1)
      throw new ReportContractError(`report_section_${index}_number_invalid`);
    return {
      number,
      title: text(section.title, `report_section_${index}_title`, 160),
      required: text(section.required, `report_section_${index}_required`, 800),
      citations: array(
        section.citations,
        `report_section_${index}_citations`,
        1,
        2,
      ).map((citation, citationIndex) =>
        parseCitation(
          citation,
          `report_section_${index}_citation_${citationIndex}`,
        ),
      ),
    };
  });
}

function parseRecoveryMetadata(value: unknown): RecoveryMetadata {
  const recovery = object(value, "report_recovery");
  keys(
    recovery,
    [
      "version",
      "validation_state",
      "provider_calls",
      "human_approved",
      "official_score",
    ],
    "report_recovery",
  );
  const version = integer(
    recovery.version,
    "report_recovery_version",
    1,
    2_147_483_647,
  );
  const validationState = text(
    recovery.validation_state,
    "report_recovery_validation_state",
    32,
  );
  if (
    !["needs_correction", "revalidated", "corrected"].includes(validationState)
  )
    throw new ReportContractError("report_recovery_validation_state_invalid");
  if (recovery.provider_calls !== 0)
    throw new ReportContractError("report_recovery_provider_calls_invalid");
  if (recovery.human_approved !== false)
    throw new ReportContractError("report_recovery_human_approved_invalid");
  if (recovery.official_score !== false)
    throw new ReportContractError("report_recovery_official_score_invalid");
  return {
    version,
    validation_state: validationState as RecoveryMetadata["validation_state"],
    provider_calls: 0,
    human_approved: false,
    official_score: false,
  };
}

function parseReport(
  value: unknown,
  binding: ReportSourceBinding,
  projected = false,
): SalesReport {
  const report = object(value, "report_invalid");
  keys(
    report,
    [
      "summary",
      "strengths",
      "missed_opportunities",
      "improvements",
      "objection_analysis",
      "closing_analysis",
      "verdict",
      "review_status",
      "source_label",
      "source_sha256",
      "transcript_revision",
      "dimensions",
      "report_sections",
      "overview",
    ],
    "report",
  );
  if (!SHA256.test(binding.sourceSha256))
    throw new ReportContractError("source_binding_invalid");
  if (!Number.isInteger(binding.durationMs) || binding.durationMs <= 0)
    throw new ReportContractError("source_duration_invalid");
  const sourceSha256 = text(report.source_sha256, "report_source_sha256", 64);
  if (!SHA256.test(sourceSha256) || sourceSha256 !== binding.sourceSha256)
    throw new ReportContractError("report_source_mismatch");
  const reviewStatus = text(report.review_status, "report_review_status", 64);
  if (reviewStatus !== REPORT_REVIEW_STATUS)
    throw new ReportContractError("report_review_status_invalid");
  const transcriptRevision = text(
    report.transcript_revision,
    "report_transcript_revision",
    256,
  );
  if (binding.transcript && transcriptRevision !== binding.transcript.revision)
    throw new ReportContractError("report_transcript_revision_mismatch");
  const parsed: SalesReport = {
    summary: text(report.summary, "report_summary", 4_000),
    strengths: array(report.strengths, "report_strengths", 0, 3).map(
      (entry, index) =>
        parseFinding(
          entry,
          `report_strength_${index}`,
          binding.durationMs,
          binding.transcript,
        ),
    ),
    missed_opportunities: array(
      report.missed_opportunities,
      "report_missed",
      0,
      10,
    ).map((entry, index) =>
      parseFinding(
        entry,
        `report_missed_${index}`,
        binding.durationMs,
        binding.transcript,
      ),
    ),
    improvements: array(report.improvements, "report_improvements", 0, 3).map(
      (entry, index) =>
        parseFinding(
          entry,
          `report_improvement_${index}`,
          binding.durationMs,
          binding.transcript,
        ),
    ),
    objection_analysis: array(
      report.objection_analysis,
      "report_objections",
      0,
      8,
    ).map((entry, index) =>
      parseFinding(
        entry,
        `report_objection_${index}`,
        binding.durationMs,
        binding.transcript,
      ),
    ),
    closing_analysis: array(
      report.closing_analysis,
      "report_closing",
      0,
      8,
    ).map((entry, index) =>
      parseFinding(
        entry,
        `report_closing_${index}`,
        binding.durationMs,
        binding.transcript,
      ),
    ),
    verdict: text(report.verdict, "report_verdict", 4_000),
    review_status: REPORT_REVIEW_STATUS,
    source_label: text(report.source_label, "report_source_label", 256),
    source_sha256: sourceSha256,
    transcript_revision: transcriptRevision,
    dimensions: parseDimensions(report.dimensions),
    report_sections: projected ? [] : parseSections(report.report_sections),
  };
  if (report.overview !== undefined && report.overview !== null) {
    try {
      parsed.overview = parseDetailedOverview(
        report.overview,
        parsed,
        (value) => {
          const evidence = parseEvidence(
            value,
            "report_overview_evidence",
            binding.durationMs,
            binding.transcript,
          );
          const segment = binding.transcript?.segments.find(
            (item) => item.id === evidence.segment_id,
          );
          if (
            segment &&
            (evidence.start_ms !== segment.start_ms ||
              evidence.end_ms !== segment.end_ms)
          )
            throw new ReportContractError(
              "report_overview_evidence_segment_timing_mismatch",
            );
          return evidence;
        },
      );
    } catch (error) {
      if (error instanceof ReportContractError) throw error;
      throw new ReportContractError("report_overview_invalid");
    }
  }
  return parsed;
}

/** The acquisition projection retains the same literal-evidence validators. */
export function parseAcquisitionReport(
  value: unknown,
  expected: { submissionId: string; recordingId: string },
  transcript: Transcript,
): { report: SalesReport; claimed: boolean; recovery?: RecoveryMetadata } {
  const envelope = object(value, "report_envelope");
  keys(
    envelope,
    [
      "schema",
      "submission_id",
      "recording_id",
      "run_id",
      "source_sha256",
      "transcript_revision",
      "source_label",
      "report",
      "recovery",
    ],
    "report_envelope",
  );
  if (
    envelope.schema !== "ac.sales-xray.report-envelope/2" ||
    envelope.submission_id !== expected.submissionId ||
    envelope.recording_id !== expected.recordingId ||
    envelope.source_sha256 !== transcript.source_sha256 ||
    envelope.transcript_revision !== transcript.revision
  )
    throw new ReportContractError("report_envelope_binding");
  identifier(envelope.run_id, "report_run");
  const recovery =
    envelope.recovery === undefined
      ? undefined
      : parseRecoveryMetadata(envelope.recovery);
  const projection = object(envelope.report, "report_projection");
  keys(
    projection,
    [
      "schema",
      "access",
      "review_status",
      "numeric_publication",
      "content",
      "sections",
      "unlock",
      "preview",
    ],
    "report_projection",
  );
  if (
    projection.schema !== "ac.sales-xray.report-access/2" ||
    !["guest_preview", "claimed_account"].includes(String(projection.access)) ||
    projection.numeric_publication !== false
  )
    throw new ReportContractError("report_projection_invalid");
  const content = object(projection.content, "report_content");
  keys(
    content,
    [
      "summary",
      "strengths",
      "missed_opportunities",
      "dimensions",
      "next_action",
      "improvements",
      "objection_analysis",
      "closing_analysis",
      "verdict",
      "overview",
    ],
    "report_content",
  );
  const { next_action: _nextAction, ...findings } = content;
  void _nextAction;
  const claimed = projection.access === "claimed_account";
  const report = parseReport(
    {
      ...findings,
      review_status: projection.review_status,
      source_label: envelope.source_label,
      source_sha256: envelope.source_sha256,
      transcript_revision: envelope.transcript_revision,
    },
    {
      sourceSha256: transcript.source_sha256,
      durationMs: transcript.duration_ms,
      transcript,
    },
    true,
  );
  // Older envelopes may omit preview. Counts can never redefine the report's
  // evidence rules, and an account projection cannot advertise hidden content.
  if (projection.preview !== undefined && projection.preview !== null) {
    if (claimed)
      throw new ReportContractError("report_preview_account_invalid");
    report.preview = parsePreview(projection.preview, report);
  }
  return recovery === undefined
    ? { claimed, report }
    : { claimed, report, recovery };
}

export function parseJobResponse(
  value: unknown,
  binding?: ReportSourceBinding,
): Job {
  const base = parseJobStatus(value);
  const job = object(value, "job_invalid");
  const report =
    job.report === undefined || job.report === null ? undefined : job.report;
  if (report === undefined) return base;
  if (!binding) throw new ReportContractError("report_source_binding_required");
  return {
    ...base,
    report: parseReport(report, binding),
  };
}

export function parseJobStatus(
  value: unknown,
  expected?: { runId: string; recordingId: string },
): Job {
  const job = object(value, "job_invalid");
  keys(
    job,
    [
      "id",
      "recording_id",
      "recipe_revision",
      "state",
      "message",
      "provider_calls",
      "report",
    ],
    "job",
  );
  const state = text(job.state, "job_state", 32);
  if (!REPORT_STATES.has(state))
    throw new ReportContractError("job_state_invalid");
  if (job.provider_calls !== undefined)
    integer(job.provider_calls, "job_provider_calls", 0, 128);
  const recordingId =
    job.recording_id === undefined
      ? undefined
      : text(job.recording_id, "job_recording_id", 128);
  if (expected) {
    if (text(job.id, "job_id", 128) !== expected.runId)
      throw new ReportContractError("job_id_mismatch");
    if (recordingId !== expected.recordingId)
      throw new ReportContractError("job_recording_id_mismatch");
  }
  if (job.recipe_revision !== undefined)
    text(job.recipe_revision, "job_recipe_revision", 128);
  return {
    id: text(job.id, "job_id", 128),
    state,
    message: optionalText(job.message, "job_message", 2_000),
  };
}

export function encodeConversationId(value: unknown, code = "id"): string {
  const identifierValue = identifier(value, code);
  return encodeURIComponent(identifierValue);
}

export function parseTranscript(
  value: unknown,
  expectedSourceSha256: string,
): Transcript {
  if (!SHA256.test(expectedSourceSha256))
    throw new ReportContractError("transcript_source_binding_invalid");
  const transcript = object(value, "transcript_invalid");
  keys(
    transcript,
    ["source_sha256", "revision", "timebase_id", "duration_ms", "segments"],
    "transcript",
  );
  const sourceSha256 = text(
    transcript.source_sha256,
    "transcript_source_sha256",
    64,
  );
  if (sourceSha256 !== expectedSourceSha256)
    throw new ReportContractError("transcript_source_mismatch");
  const durationMs = integer(
    transcript.duration_ms,
    "transcript_duration_ms",
    1,
    86_400_000,
  );
  const segments = array(
    transcript.segments,
    "transcript_segments",
    0,
    20_000,
  ).map((value, index) => {
    const segment = object(value, `transcript_segment_${index}`);
    keys(
      segment,
      ["id", "speaker_id", "start_ms", "end_ms", "text"],
      `transcript_segment_${index}`,
    );
    const startMs = integer(
      segment.start_ms,
      `transcript_segment_${index}_start_ms`,
      0,
      durationMs,
    );
    const endMs = integer(
      segment.end_ms,
      `transcript_segment_${index}_end_ms`,
      1,
      durationMs,
    );
    if (endMs <= startMs)
      throw new ReportContractError(
        `transcript_segment_${index}_timing_invalid`,
      );
    const speakerId =
      segment.speaker_id === null
        ? null
        : text(
            segment.speaker_id,
            `transcript_segment_${index}_speaker_id`,
            128,
          );
    return {
      id: identifier(segment.id, `transcript_segment_${index}_id`),
      speaker_id: speakerId,
      start_ms: startMs,
      end_ms: endMs,
      text: text(segment.text, `transcript_segment_${index}_text`, 10_000),
    };
  });
  const ids = new Set<string>();
  for (const segment of segments) {
    if (ids.has(segment.id))
      throw new ReportContractError("transcript_segment_duplicate");
    ids.add(segment.id);
  }
  return {
    source_sha256: sourceSha256,
    revision: text(transcript.revision, "transcript_revision", 256),
    timebase_id: text(transcript.timebase_id, "transcript_timebase_id", 128),
    duration_ms: durationMs,
    segments,
  };
}

function parseLatestRun(
  value: unknown,
  code: string,
): SavedRecording["latest_run"] {
  if (value === null) return null;
  const run = object(value, `${code}_invalid`);
  keys(
    run,
    ["id", "state", "recipe_revision", "provider_calls", "has_report"],
    code,
  );
  return {
    id: identifier(run.id, `${code}_id`),
    state: text(run.state, `${code}_state`, 32),
    recipe_revision: text(run.recipe_revision, `${code}_recipe_revision`, 128),
    provider_calls: integer(
      run.provider_calls,
      `${code}_provider_calls`,
      0,
      128,
    ),
    has_report:
      typeof run.has_report === "boolean"
        ? run.has_report
        : (() => {
            throw new ReportContractError(`${code}_has_report_invalid`);
          })(),
  };
}

export function parseSavedRecordings(value: unknown): SavedRecordingResponse {
  const payload = object(value, "recordings_invalid");
  keys(payload, ["recordings"], "recordings");
  const recordings = array(payload.recordings, "recordings", 0, 20).map(
    (value, index) => {
      const recording = object(value, `recording_${index}`);
      keys(
        recording,
        [
          "id",
          "state",
          "source_revision",
          "source_sha256",
          "source_bytes",
          "content_type",
          "created_at",
          "latest_run",
          "has_report",
        ],
        `recording_${index}`,
      );
      const sourceSha256 = text(
        recording.source_sha256,
        `recording_${index}_source_sha256`,
        64,
      );
      if (!SHA256.test(sourceSha256))
        throw new ReportContractError(
          `recording_${index}_source_sha256_invalid`,
        );
      if (typeof recording.has_report !== "boolean")
        throw new ReportContractError(`recording_${index}_has_report_invalid`);
      return {
        id: identifier(recording.id, `recording_${index}_id`),
        state: text(recording.state, `recording_${index}_state`, 32),
        source_revision: text(
          recording.source_revision,
          `recording_${index}_source_revision`,
          128,
        ),
        source_sha256: sourceSha256,
        source_bytes: integer(
          recording.source_bytes,
          `recording_${index}_source_bytes`,
          0,
          128 * 1024 * 1024,
        ),
        content_type: text(
          recording.content_type,
          `recording_${index}_content_type`,
          128,
        ),
        created_at: text(
          recording.created_at,
          `recording_${index}_created_at`,
          128,
        ),
        latest_run: parseLatestRun(
          recording.latest_run,
          `recording_${index}_latest_run`,
        ),
        has_report: recording.has_report,
      };
    },
  );
  return { recordings };
}
