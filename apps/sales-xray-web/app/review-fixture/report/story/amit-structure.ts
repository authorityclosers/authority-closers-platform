import { exampleView } from "../../../xray-report/example";
import { scoreBand } from "../../../xray-report/model";
import { amitTranscript } from "./amit-call";

/**
 * The API's `report.structure` (report-structure/1) for the fictional Amit
 * call, as it arrives once an AI pointer review is saved: scores marked as an
 * AI draft, evidence by real fixture segment ids. Exercises the same reader a
 * real call uses (`?example=api`); every word and number is fictional.
 */

const segments = amitTranscript.segments;
const evidence = (index: number) => {
  const segment = segments[index % segments.length];
  return {
    segment_id: segment.id,
    quote: segment.text,
    start_ms: segment.start_ms,
    end_ms: segment.end_ms,
  };
};

const BAND = {
  excellent: "Excellent",
  good: "Good",
  average: "Average",
  needs_improvement: "Needs Improvement",
} as const;

const example = exampleView("decision_pending");
const scores = example.pointers
  .map((pointer) => pointer.score)
  .filter((score): score is number => score !== null);
const overall = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length);

export const AMIT_STRUCTURE = {
  version: "report-structure/1",
  review_status: "ai_draft_not_dipak_reviewed",
  overview: {
    summary:
      "You spoke with Amit about growing his agency to ₹10 lakh a month without him closing every sale. He liked the program but wants to talk to his business partner first.",
    evidence: [evidence(2), evidence(9)],
    score: overall,
    score_label: BAND[scoreBand(overall)],
    score_line:
      "A warm, well-run call; the price came before Amit's sales problem was fully understood.",
    score_status: "ai_draft",
    biggest_strength: {
      text: "You linked the program to Amit's goal of a business that sells without him.",
      evidence: [evidence(14)],
      source: "pillars.strongest_part",
    },
    biggest_improvement: {
      text: "You explained the program before finding out why his team cannot close.",
      evidence: [evidence(6)],
      source: "pillars.biggest_concern",
    },
    call_statistics: { status: "unavailable" },
  },
  pointers: example.pointers.map((pointer, index) => ({
    id: pointer.id,
    number: pointer.number,
    label: pointer.name,
    status: pointer.status,
    score: pointer.score,
    score_status: "ai_draft",
    rating: pointer.score === null ? null : BAND[scoreBand(pointer.score)],
    coverage: "ai_pointer_review",
    what_happened: pointer.whatHappened,
    why_it_matters: pointer.whyItMatters,
    evidence:
      pointer.score === null
        ? []
        : [evidence(index * 2), evidence(index * 2 + 1)],
    how_to_improve: pointer.howToImprove,
    training_video: pointer.training
      ? { title: pointer.training.title, url: null, minutes: null }
      : null,
    observations: [],
    related_dimensions: [],
    related_findings: [],
  })),
  call_outcome_details: {
    stages: [
      "Initial Contact",
      "Discovery",
      "Solution Presentation",
      "Negotiation",
    ],
    reasons: [
      "Amit sees the value of not closing every sale himself.",
      "He wants his business partner's view on the ₹2 lakh investment.",
    ],
    objections: [
      { text: "The investment needs his partner's agreement.", handled: false },
      { text: "He asked how fast his team would see results.", handled: true },
    ],
    next_steps: [
      {
        text: "Send the program summary and a case study.",
        owner: "you",
        when: "Today",
      },
      {
        text: "Amit talks to his partner.",
        owner: "prospect",
        when: "Before Friday",
      },
      { text: "Follow-up call.", owner: "you", when: "Friday 4 PM" },
    ],
    notes: ["Amit's team of 8 depends on him for most sales."],
    suggested_action:
      "Before Friday, send one example of an agency that grew without the owner closing.",
  },
};
