import { fictionalCoaching } from "./coaching/coaching.fixture";
import {
  recordingId,
  submissionId,
  transcript,
} from "../tests/acquisition-fixture";
import type { CallCoachingBinding } from "./report-call-coaching-client";

/** Invented call/guide data only, matching the pinned 1a43d30 API contract. */
export const callCoachingBinding: CallCoachingBinding = {
  callId: submissionId,
  personId: fictionalCoaching.person_id,
  tenantId: fictionalCoaching.tenant_id,
  sessionId: "00000000-0000-0000-0000-000000000008",
  recordingId,
  sourceSha256: transcript.source_sha256,
  transcriptRevision: transcript.revision,
  transcript,
};
export function fictionalCallCoaching() {
  const segment = transcript.segments[0];
  const source = {
    submission_id: submissionId,
    recording_id: recordingId,
    source_sha256: transcript.source_sha256,
    transcript_revision: transcript.revision,
    created_at: "2026-10-10T10:00:00Z",
    call_label: "Fictional call",
    segment_id: segment.id,
    start_ms: segment.start_ms,
    end_ms: segment.end_ms,
    quote: segment.text,
    observation: "A fictional observation.",
    playable: true,
  };
  const mission = {
    ...fictionalCoaching.mission!,
    origin_submission_id: submissionId,
  };
  return {
    schema: "ac.sales-xray.call-coaching/1",
    person_id: callCoachingBinding.personId,
    tenant_id: callCoachingBinding.tenantId,
    session_id: callCoachingBinding.sessionId,
    submission_id: submissionId,
    recording_id: recordingId,
    source_sha256: transcript.source_sha256,
    transcript_revision: transcript.revision,
    report_revision: "b".repeat(64),
    call_label: "Fictional call",
    authority: "provisional",
    entitlement: "coaching",
    entitlement_policy: "AUT-1678-open-access",
    state: "ready",
    basis: "skill_evidence",
    focus: {
      ...fictionalCoaching.focus!,
      status: "provisional",
      label: "Fictional API focus",
      selected_reason: "Selected from this one fictional call.",
    },
    evidence: [source],
    root_cause: { ...fictionalCoaching.root_cause },
    lesson: {
      ...fictionalCoaching.lesson!,
      own_call: source,
      next_call_connection: mission.behavior,
    },
    practice: { ...fictionalCoaching.practice! },
    mission,
    recommended_media: null,
    limitations: ["One fictional call only; no recurring pattern or mastery."],
  };
}
