import type { ProspectCall, ProspectSummary } from "../../prospects-client";
import type { ProfileField } from "../../prospect-profile-contract";
import { amitTranscript, AMIT_SPEAKERS } from "../report/story/amit-call";

/** The spec's fictional Amit Sharma, linked to the fictional 25:08 call. */
export const AMIT_CALL_ID = "00000000-0000-4000-8000-000000000077";

const heard = (text: string, segment: number): ProfileField => {
  const source = amitTranscript.segments[segment - 1];
  return {
    state: "known",
    value: { kind: "text", text },
    basis: "heard_in_call",
    locked: false,
    set_at: "2026-10-09T10:30:00Z",
    evidence: {
      submission_id: AMIT_CALL_ID,
      segment_id: source.id,
      quote: source.text,
      start_ms: source.start_ms,
      end_ms: source.end_ms,
    },
  };
};

export const amitProspect: ProspectSummary = {
  prospect_id: "11111111-1111-4111-8111-777777777777",
  owner_person_id: "22222222-2222-4222-8222-222222222222",
  name: "Amit Sharma",
  revision: 4,
  origin: "person",
  confirmed_at: "2026-10-09T10:40:00Z",
  stage: null,
  tags: ["Agency owner"],
  photo_url: null,
  contact: null,
  fields: [],
  buyer_intent: null,
  next_step: null,
  last_promise: null,
  call_count: 1,
  last_call: "2026-10-09T10:00:00Z",
  can_edit: true,
  profile_fields: {
    name: {
      state: "known",
      value: { kind: "text", text: "Amit Sharma" },
      basis: "person",
      locked: true,
      set_at: "2026-10-09T10:40:00Z",
    },
    role: {
      state: "known",
      value: { kind: "text", text: "Founder" },
      basis: "person",
      locked: true,
      set_at: "2026-10-09T10:40:00Z",
    },
    business: {
      state: "known",
      value: { kind: "text", text: "XYZ Digital" },
      basis: "person",
      locked: true,
      set_at: "2026-10-09T10:40:00Z",
    },
    industry: heard("Digital marketing agency", 6),
    team_size: heard("8 people", 6),
    turnover: heard("₹4–5 lakh/month", 10),
    main_pain: heard("Sales depend too much on Amit", 14),
    decision_maker: heard("Amit, with his business partner", 30),
    budget: { state: "unknown", reason: "not_mentioned" },
    timeline: { state: "unknown", reason: "not_asked" },
  },
};

export const amitCalls: ProspectCall[] = [
  {
    submission_id: AMIT_CALL_ID,
    recording_id: "00000000-0000-4000-8000-000000000078",
    created_at: "2026-10-09T10:00:00Z",
    duration_seconds: Math.round(amitTranscript.duration_ms / 1000),
    display_name: "Discovery call",
    state: "completed",
    has_report: true,
    score: null,
    call_url: `/analysis/calls/${AMIT_CALL_ID}`,
    report_url: `/analysis/calls/${AMIT_CALL_ID}`,
    snapshot: null,
  },
];

export { AMIT_SPEAKERS };
