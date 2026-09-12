import type {
  AdminLearnerLookup,
  AdminLearnerDiagnosis,
  AdminSession,
} from "../app/lib/admin-api";

export const personId = "11111111-1111-4111-8111-111111111111";
export const tenantId = "22222222-2222-4222-8222-222222222222";
export const activityId = "33333333-3333-4333-8333-333333333333";
export const otherId = "44444444-4444-4444-8444-444444444444";
export const account: AdminSession = {
  personId: otherId,
  tenantId,
  sessionId: "55555555-5555-4555-8555-555555555555",
  email: "support@example.test",
  displayName: "Support operator",
  emailVerifiedAt: "2026-09-13T00:00:00Z",
  membershipRole: "support",
  permissions: ["admin_surface", "learner_diagnose"],
  studioCapabilities: [],
};
export const candidate = {
  person_id: personId,
  display_name: "Synthetic Learner",
  username: "synthetic_learner",
  masked_email: "s***@example.test",
  membership_status: "active",
  membership_role: "learner",
} as const;
export const lookup: AdminLearnerLookup = {
  tenant_id: tenantId,
  redaction_version: "admin-learner-v1",
  candidates: [candidate],
  truncated: false,
};
export const diagnosis: AdminLearnerDiagnosis = {
  ...candidate,
  tenant_id: tenantId,
  purpose: "learner_support",
  redaction_version: "admin-learner-v1",
  as_of: "2026-09-13T00:00:00Z",
  truncated: false,
  enrollments: [
    {
      enrollment_id: "66666666-6666-4666-8666-666666666666",
      program_id: "77777777-7777-4777-8777-777777777777",
      program_title: "Practice course",
      program_version_id: "88888888-8888-4888-8888-888888888888",
      version_number: 2,
      enrollment_status: "active",
      entitlement_status: "active",
      truncated: false,
      drafts_truncated: false,
      evidence_truncated: false,
      progress: {
        projection_version: "progress-v1",
        denominator: 5,
        completed_count: 1,
        percentage: 20,
        next_activity_id: activityId,
        activity_states_truncated: false,
        activity_states: [
          {
            activity_id: activityId,
            title: "Prepare your opening",
            kind: "reflection",
            state: "in_progress",
            required: true,
            reason: "draft_saved",
            missing_activity_ids: [],
            missing_module_ids: [],
          },
        ],
      },
      drafts: [
        {
          activity_id: activityId,
          present: true,
          revision: 3,
          saved_at: "2026-09-13T00:00:00Z",
        },
      ],
      evidence: [
        {
          activity_id: activityId,
          evidence_type: "reflection",
          submission_status: "submitted",
          captured_at: "2026-09-12T23:59:00Z",
          submitted_at: "2026-09-13T00:00:00Z",
        },
      ],
    },
  ],
};
