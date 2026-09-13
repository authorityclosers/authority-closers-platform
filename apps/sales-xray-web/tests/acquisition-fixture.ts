import fixture from "./fixtures/dipak-overview.json";
export const submissionId = "7b6443d3-9b2d-4f97-9e70-5e82e54f8738";
export const recordingId = "fd4b05b1-bfc9-4d28-a379-f3d032faf7af";
export const transcript = fixture.transcript;
const {
  source_sha256,
  transcript_revision,
  source_label,
  review_status,
  report_sections: _sections,
  ...content
} = fixture.report;
void _sections;
export const envelope = {
  schema: "ac.sales-xray.report-envelope/2",
  submission_id: submissionId,
  recording_id: recordingId,
  run_id: "02de89cf-8e5e-4bde-8eb6-c8fcd79ed4de",
  source_sha256,
  transcript_revision,
  source_label,
  report: {
    schema: "ac.sales-xray.report-access/2",
    access: "guest_preview",
    review_status,
    numeric_publication: false,
    content: { ...content, next_action: content.improvements[0] },
    sections: [],
    unlock: null,
  },
};
export const allowance = {
  allowance_seconds: 6000,
  committed_seconds: 0,
  available_seconds: 6000,
};
export const entry = {
  enabled: true,
  site_key: "synthetic-site-key",
  challenge_action: "sales_xray_upload",
  policy_revision: "guest-processing-v1",
  allowance_seconds: 6000,
};
export const policy = {
  schema: "ac.sales-xray.private-upload-consent/1",
  policy_sha256: "b".repeat(64),
  title: "Upload privately",
  description:
    "Synthetic test. Original audio stays private for seven days. No external processing during upload.",
  maximum_file_bytes: 128 * 1024 ** 2,
  maximum_call_seconds: 1800,
  retention_days: 7,
  max_cost_paise: 0,
};
export const progress = {
  submission_id: submissionId,
  recording_id: recordingId,
  source_sha256,
  state: "ready",
  local_state: "completed",
  has_report: false,
  automatic_progression: false,
  stages: [],
};
export const plan = {
  id: "e933e1dd-4cb9-4a7d-b0f9-c179f769e688",
  recording_id: recordingId,
  plan_fingerprint: "a".repeat(64),
  privacy_revision: "sales-xray-processing-plan-v1",
  accepted: false,
  state: "quoted",
  cost_label: "₹0 · approved allowance",
  max_cost_paise: 0,
  max_entitlement_seconds: 0,
  expires_at_epoch: 4102444800,
  stages: ["C2", "C4", "C5"].map((stage) => ({
    stage,
    provider: "synthetic-provider",
    model: "synthetic-model",
    max_requests: 1,
    privacy_revision: "synthetic-privacy-v1",
    privacy_notice: "Synthetic provider only. No data leaves the test process.",
  })),
  current_stage: null,
  report_ready: false,
  report_run_id: null,
  automatic_progression: true,
  failure_code: null,
};
