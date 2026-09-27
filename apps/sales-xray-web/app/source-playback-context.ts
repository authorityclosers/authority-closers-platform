import type {
  ReportEvidence,
  SalesReport,
  Transcript,
  TranscriptSegment,
} from "./report-contract";

export type SourcePlaybackRange = Pick<ReportEvidence, "start_ms" | "end_ms">;

/**
 * A presentation-only playback request. `evidence` remains the unchanged
 * saved report quote; neighboring transcript segments are context, not proof.
 */
export type ContextualSourcePlayback = {
  source_sha256: string;
  transcript_revision: string;
  evidence: ReportEvidence;
  evidence_speaker_id: string | null;
  context_before: TranscriptSegment | null;
  context_after: TranscriptSegment | null;
  playback_range: SourcePlaybackRange;
};

/** Keep source speaker IDs out of the context view without assigning roles. */
export function formatContextSpeakerLabel(
  transcript: Transcript,
  speakerId: string | null,
): string {
  if (speakerId === null) return "Unlabelled speaker";
  const orderedSpeakerIds: string[] = [];
  const seenSpeakerIds = new Set<string>();
  for (const segment of transcript.segments) {
    if (
      segment.speaker_id !== null &&
      !seenSpeakerIds.has(segment.speaker_id)
    ) {
      seenSpeakerIds.add(segment.speaker_id);
      orderedSpeakerIds.push(segment.speaker_id);
    }
  }
  const index = orderedSpeakerIds.indexOf(speakerId);
  return index === -1 ? "Speaker" : `Speaker ${index + 1}`;
}

function sameEvidence(left: ReportEvidence, right: ReportEvidence): boolean {
  return (
    left.segment_id === right.segment_id &&
    left.quote === right.quote &&
    left.start_ms === right.start_ms &&
    left.end_ms === right.end_ms
  );
}

function sameSegment(
  left: TranscriptSegment | null,
  right: TranscriptSegment | null,
): boolean {
  return (
    left === right ||
    (left !== null &&
      right !== null &&
      left.id === right.id &&
      left.speaker_id === right.speaker_id &&
      left.start_ms === right.start_ms &&
      left.end_ms === right.end_ms &&
      left.text === right.text)
  );
}

function isCurrentRewatchEvidence(
  report: SalesReport,
  evidence: ReportEvidence,
): boolean {
  const baseFindings = [
    ...report.improvements,
    ...report.missed_opportunities,
    ...report.strengths,
  ];
  return (
    baseFindings.some((finding) =>
      finding.evidence.some((item) => sameEvidence(item, evidence)),
    ) ||
    Boolean(
      report.overview?.rewatch.some((moment) =>
        moment.evidence.some((item) => sameEvidence(item, evidence)),
      ),
    )
  );
}

/** Build context only from the exact validated report/transcript pair. */
export function buildContextualSourcePlayback(
  report: SalesReport,
  transcript: Transcript,
  evidence: ReportEvidence,
): ContextualSourcePlayback | null {
  if (
    report.source_sha256 !== transcript.source_sha256 ||
    report.transcript_revision !== transcript.revision ||
    !isCurrentRewatchEvidence(report, evidence)
  )
    return null;

  const evidenceIndex = transcript.segments.findIndex(
    (segment) => segment.id === evidence.segment_id,
  );
  if (evidenceIndex < 0) return null;
  const evidenceSegment = transcript.segments[evidenceIndex];
  if (
    !evidenceSegment.text.includes(evidence.quote) ||
    evidence.start_ms < evidenceSegment.start_ms ||
    evidence.end_ms > evidenceSegment.end_ms ||
    evidence.end_ms <= evidence.start_ms
  )
    return null;

  const previous = transcript.segments[evidenceIndex - 1] ?? null;
  const next = transcript.segments[evidenceIndex + 1] ?? null;
  // At most one immediate canonical segment per side. Reject a neighbor if
  // its position or interval is inconsistent with the evidence segment.
  const contextBefore =
    previous &&
    previous.end_ms <= evidenceSegment.start_ms &&
    previous.start_ms < evidence.start_ms
      ? previous
      : null;
  const contextAfter =
    next &&
    next.start_ms >= evidenceSegment.end_ms &&
    next.end_ms > evidence.end_ms
      ? next
      : null;

  return {
    source_sha256: transcript.source_sha256,
    transcript_revision: transcript.revision,
    evidence: { ...evidence },
    evidence_speaker_id: evidenceSegment.speaker_id,
    context_before: contextBefore,
    context_after: contextAfter,
    playback_range: {
      start_ms: contextBefore?.start_ms ?? evidence.start_ms,
      end_ms: contextAfter?.end_ms ?? evidence.end_ms,
    },
  };
}

/** Re-derive a UI selection against current props before seeking the player. */
export function revalidateContextualSourcePlayback(
  selection: ContextualSourcePlayback,
  report: SalesReport,
  transcript: Transcript,
): ContextualSourcePlayback | null {
  if (
    selection.source_sha256 !== report.source_sha256 ||
    selection.source_sha256 !== transcript.source_sha256 ||
    selection.transcript_revision !== report.transcript_revision ||
    selection.transcript_revision !== transcript.revision
  )
    return null;

  const current = buildContextualSourcePlayback(
    report,
    transcript,
    selection.evidence,
  );
  if (
    !current ||
    current.evidence_speaker_id !== selection.evidence_speaker_id ||
    !sameEvidence(current.evidence, selection.evidence) ||
    !sameSegment(current.context_before, selection.context_before) ||
    !sameSegment(current.context_after, selection.context_after) ||
    current.playback_range.start_ms !== selection.playback_range.start_ms ||
    current.playback_range.end_ms !== selection.playback_range.end_ms
  )
    return null;
  return current;
}
