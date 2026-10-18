import { amitTranscript } from "../report/story/amit-call";

/**
 * A saved AI review's prospect_profile for the spec's fictional Amit call,
 * as the server projects it (Prospect's Information v2, 19 Oct).
 */
const [s1, s2, s3] = amitTranscript.segments;
const ref = (segment: { id: string; text: string }) => ({
  segment_id: segment.id,
  quote: segment.text.slice(0, 30),
});

export const AMIT_PROFILE = {
  version: "prospect-profile/1",
  basis: "ai_pointer_review",
  name: { value: "Amit", evidence: [ref(s1)] },
  role: { value: "Founder", evidence: [ref(s2)] },
  company: { value: "XYZ Digital", evidence: [ref(s2)] },
  revenue: { value: "₹4–5 lakh a month", evidence: [ref(s3)] },
  team_size: { value: "8 people", evidence: [ref(s3)] },
  industry: { value: "Digital marketing", evidence: [] },
  biggest_problem: { value: "Sales depend on Amit.", evidence: [ref(s3)] },
  wants: { value: "Reach ₹10 lakh a month.", evidence: [ref(s3)] },
  stopping: { value: "Needs his partner's OK.", evidence: [ref(s3)] },
  personal_context: { value: null, evidence: [] },
  follow_up: {
    when: "Friday 4 PM",
    about: "Partner discussion",
    evidence: [ref(s3)],
  },
  insights: [
    {
      kind: "investment",
      text: "Considering a ₹2 lakh investment.",
      evidence: [ref(s3)],
    },
    { kind: "goal", text: "No evidence, so dropped.", evidence: [] },
    { kind: "made_up", text: "Unknown kind, dropped.", evidence: [ref(s3)] },
  ],
  quality: { score: 8, reason: "Clear need and budget." },
  fit: { value: "strong", reason: "Agency with a sales team." },
  urgency: { value: "medium", reason: "Three months." },
};
