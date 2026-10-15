import { REPORT_SKILLS } from "../../../report-pillars";
import type { Transcript, SalesReport } from "../../../report-contract";
import { parseReportContent, type ContentNote } from "../../../report-content";
import { syntheticReport } from "../synthetic-report";

// Fictional turns only. No recording, account or provider exists.
export const contentTranscript: Transcript = {
  source_sha256: syntheticReport.source_sha256,
  revision: syntheticReport.transcript_revision,
  timebase_id: "fictional-ms",
  duration_ms: 6000,
  segments: [
    ["seller", "This call is to arrange a meeting."],
    ["buyer", "I can discuss the details next week."],
    ["seller", "Which details would you like to discuss?"],
    ["buyer", "I need to check the delivery date."],
    ["seller", "Can we meet Friday at 4 PM? I will send the agenda."],
    ["buyer", "Yes, Friday at 4 PM. I will bring the details."],
  ].map(([speaker_id, text], i) => ({
    id: `fictional-${i}`,
    speaker_id,
    text,
    start_ms: i * 1000,
    end_ms: i * 1000 + 900,
  })),
};
const note = (i: number, text: string): ContentNote => {
  const s = contentTranscript.segments[i];
  return {
    text,
    actor_id: s.speaker_id!,
    evidence: [
      {
        segment_id: s.id,
        quote: s.text,
        start_ms: s.start_ms,
        end_ms: s.end_ms,
      },
    ],
  };
};
export const contentFixture = parseReportContent(
  {
    version: "report-content/1",
    roles: { seller: "seller", buyer: "prospect" },
    purpose: { ...note(0, "A meeting-setting call."), kind: "setter" },
    outcome: { ...note(5, "Both agreed to meet."), status: "Meeting Booked" },
    summary_sentences: [
      note(0, "The seller explained the purpose of the call."),
      note(3, "The delivery date remained open."),
      note(5, "Both agreed to meet Friday at 4 PM."),
    ],
    influence: note(3, "The delivery date came up."),
    strongest: note(4, "The seller proposed a specific time."),
    concern: note(2, "The question did not establish a delivery date."),
    next_step: note(5, "The buyer will bring details to the meeting."),
    phases: [note(0, "Opening"), note(2, "Details"), note(4, "Next step")],
    turning_point: {
      before: note(3, "The buyer asked about delivery."),
      turn: note(4, "The seller proposed a meeting."),
      after: note(5, "The buyer agreed."),
    },
    worked: [
      {
        title: "The seller proposed a time",
        observation: note(4, "The seller proposed Friday at 4 PM."),
        effect: null,
      },
    ],
    didnt: [],
    moments: [
      {
        title: "The delivery date came up",
        observation: note(3, "The buyer asked about delivery."),
        effect: null,
        kind: "Decision Moment",
      },
    ],
    missed_chances: [],
    position: note(5, "The buyer will attend the meeting."),
    blocker: note(3, "The delivery date is still open."),
    prospect_commitments: [note(5, "The buyer will bring details.")],
    seller_commitments: [note(4, "The seller will send the agenda.")],
    next_event: {
      observation: note(5, "A meeting was agreed."),
      date_text: "Friday",
      time_text: "4 PM",
      agreement_evidence: [note(4, "").evidence[0], note(5, "").evidence[0]],
    },
    commitment_quality: "Clear",
    unknowns: [note(3, "The delivery date has not been established.")],
    action: note(3, "Confirm the delivery date at the meeting."),
  },
  contentTranscript,
);
export const contentReport: SalesReport = {
  ...syntheticReport,
  story: undefined,
  overview: undefined,
  strengths: [],
  improvements: [],
  missed_opportunities: [],
  objection_analysis: [],
  closing_analysis: [],
  report_content: contentFixture,
  summary: contentFixture.summary_sentences.map((n) => n.text).join(" "),
  dimensions: REPORT_SKILLS.map(([dimension_id, label], i) => ({
    dimension_id,
    label,
    citations: [{ doc: "Doc-1", sections: ["Fictional source section"] }],
    status: i === 1 ? "not_applicable" : "observed",
    observation:
      i === 1
        ? "A closing decision was not part of this setter call."
        : "The seller proposed a meeting time.",
    call_state: i === 1 ? "not_applicable" : "observed",
    evidence: i === 1 ? [] : note(4, "").evidence,
  })),
};
