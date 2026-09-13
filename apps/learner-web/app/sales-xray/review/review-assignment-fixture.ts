// Synthetic contract fixture; no customer recording or identity.
export const ids = {
  tenant: "10000000-0000-4000-8000-000000000001",
  recording: "20000000-0000-4000-8000-000000000002",
  run: "30000000-0000-4000-8000-000000000003",
  assignment: "40000000-0000-4000-8000-000000000004",
  checkpoint: "50000000-0000-4000-8000-000000000005",
  reviewer: "60000000-0000-4000-8000-000000000006",
  submission: "90000000-0000-4000-8000-000000000009",
};
export function assignmentResponse() {
  const source = {
    tenant_id: ids.tenant,
    recording_id: ids.recording,
    source_sha256: "a".repeat(64),
    source_revision: 1,
  };
  return {
    assignment: {
      schema: "ac.sales-xray.review-assignment/1",
      id: ids.assignment,
      tenant_id: ids.tenant,
      run_id: ids.run,
      run_generation: 3,
      recipe_revision: "audioatlas-48000-v1",
      source: {
        ...source,
        permission_id: "70000000-0000-4000-8000-000000000007",
        provenance_ref: "ref:synthetic-review-fixture",
      },
      checkpoint: {
        ...source,
        id: ids.checkpoint,
        stage: "C2",
        revision: "b".repeat(64),
        cache_key: "c".repeat(64),
        manifest_sha256: "d".repeat(64),
        payload_sha256: "e".repeat(64),
      },
      reviewer_person_id: ids.reviewer,
      allowed_lenses: ["sales", "technical", "ux"],
      state: "assigned",
      created_at_epoch: 1789257600,
      expires_at_epoch: 4102444800,
      created_by_person_id: ids.reviewer,
    },
    report: {
      source_label: "Synthetic conversation review",
      source_sha256: source.source_sha256,
      summary: "The caller and reviewer clarified the next step.",
      verdict: "Confirm the follow-up date.",
      review_status: "draft_not_dipak_adjudicated",
      strengths: [
        {
          title: "Clear next step",
          explanation: "The speaker proposed a follow-up.",
          evidence: [
            {
              segment_id: "segment-1",
              quote: "Let us clarify the next step.",
              start_ms: 42000,
              end_ms: 68000,
            },
          ],
        },
      ],
      missed_opportunities: [],
      improvements: [],
      objection_analysis: [],
      closing_analysis: [],
      dimensions: [],
      report_sections: [],
    },
    transcript: { revision: "a".repeat(64), segments: [] },
    evidence_spans: [
      {
        checkpoint_id: ids.checkpoint,
        span_id: "segment-1",
        id: "segment-1",
        speaker_id: "seller",
        start_ms: 42000,
        end_ms: 68000,
        text: "Let us clarify the next step.",
      },
    ],
    audio_source_url: `/v1/conversation/review-assignments/${ids.assignment}/source`,
  };
}
export function submissionResponse(body: Record<string, unknown> = {}) {
  return {
    schema: "ac.sales-xray.review-feedback/1",
    id: ids.submission,
    assignment_id: ids.assignment,
    tenant_id: ids.tenant,
    run_id: ids.run,
    reviewer_person_id: ids.reviewer,
    author_person_id: ids.reviewer,
    lane: body.lens === "technical" || body.lens === "ux" ? "signal" : "sales",
    lens: "sales",
    idempotency_key: "review-key-1",
    evidence_refs: [{ checkpoint_id: ids.checkpoint, span_id: "segment-1" }],
    confidence: "high",
    feedback: "The next step is grounded in the cited span.",
    proposed_correction: null,
    created_at_epoch: 1789257600,
    ...body,
  };
}
