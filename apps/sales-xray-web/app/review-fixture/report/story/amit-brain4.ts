import { amitTranscript } from "./amit-call";

/**
 * A fictional Brain 4.0 read of the fictional Amit call (`?example=coach`), shaped
 * like the API's `report.structure.brain4`, so the AI coaching score renders on dev and in
 * wb-ci screenshots. Every rating and word is made up; nothing here is Brain 4.0's
 * answer to a real call.
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

const SKILLS: [string, string, number | null, string][] = [
  [
    "Starting the Call",
    "how_you_talk",
    4,
    "You opened warmly and gave Amit room to talk.",
  ],
  [
    "Setting the Plan",
    "how_you_talk",
    3,
    "You said you would ask a few questions, but not why.",
  ],
  [
    "Tone, Pace & Pauses",
    "how_you_talk",
    null,
    "Needs the audio measures to judge.",
  ],
  [
    "Listening Well",
    "how_you_talk",
    4,
    "You came back to his partner concern later in the call.",
  ],
  [
    "Asking the Right Questions",
    "how_you_talk",
    4,
    "Your follow-ups went from revenue to what blocks it.",
  ],
  [
    "Building Connection",
    "how_you_talk",
    4,
    "Amit shared his worry about closing every sale himself.",
  ],
  [
    "Being Professional",
    "how_you_talk",
    5,
    "You kept every claim to what the program does.",
  ],
  [
    "Finding the Decision-Makers",
    "understanding_the_buyer",
    2,
    "You learnt about the partner only at the end.",
  ],
  [
    "Understanding Problems & Goals",
    "understanding_the_buyer",
    4,
    "You confirmed the ₹10 lakh goal and the closing bottleneck.",
  ],
  [
    "Understanding What They're Doing Now",
    "understanding_the_buyer",
    3,
    "You asked about his team but not how sales are run today.",
  ],
  [
    "Understanding the Real Impact",
    "understanding_the_buyer",
    3,
    "The cost of staying as he is was not put into numbers.",
  ],
  [
    "Understanding How They Will Decide",
    "understanding_the_buyer",
    2,
    "How he and his partner decide was never asked.",
  ],
  [
    "Matching the Right Solution",
    "moving_the_sale_forward",
    4,
    "You tied the program to his closing bottleneck.",
  ],
  [
    "Explaining the Solution Clearly",
    "moving_the_sale_forward",
    4,
    "The explanation was short and in his words.",
  ],
  [
    "Talking About Price & Budget",
    "moving_the_sale_forward",
    3,
    "You gave the price before checking his budget.",
  ],
  [
    "Handling Objections",
    "moving_the_sale_forward",
    3,
    "You accepted 'I'll ask my partner' without exploring it.",
  ],
  [
    "Asking for the Decision",
    "moving_the_sale_forward",
    3,
    "You asked for a decision once, softly.",
  ],
  [
    "Setting Clear Next Steps",
    "moving_the_sale_forward",
    4,
    "A call with both partners is booked for Friday.",
  ],
];

const CATEGORIES: [string, string][] = [
  ["how_you_talk", "How You Talk"],
  ["understanding_the_buyer", "How Well You Understand the Buyer"],
  ["moving_the_sale_forward", "How Well You Move the Sale Forward"],
];

const dimensions = SKILLS.map(([label, category, rating, observed], index) => ({
  id: `D${String(index + 1).padStart(2, "0")}`,
  number: index + 1,
  label,
  category,
  applicability: rating === null ? "not_enough_evidence" : "applicable",
  rating,
  shown_rating: rating,
  confidence: rating === null ? "low" : index % 3 === 0 ? "high" : "medium",
  evidence: rating === null ? [] : [evidence(index * 3 + 2)],
  observed,
  coaching:
    rating === null || rating >= 5
      ? null
      : "On your next relevant call, ask one more question before moving on.",
  ethics_gate: index === 6 ? "PASS" : null,
  adjustments: [],
}));

export const AMIT_BRAIN4 = {
  version: "brain4-review/1",
  rubric_revision: "brain4-compact/1",
  status: "beta",
  call_type: "follow_up",
  rated: dimensions.filter((d) => d.rating !== null).length,
  dimensions,
  calibration: { revision: "brain4-identity/1", basis: "none", label: "beta" },
  rollup: {
    method: "category_mean",
    categories: CATEGORIES.map(([id, label]) => {
      const rated = dimensions.filter(
        (d) => d.category === id && d.rating !== null,
      );
      return {
        id,
        label,
        rated: rated.length,
        of: dimensions.filter((d) => d.category === id).length,
        score: rated.length
          ? rated.reduce((sum, d) => sum + (d.rating ?? 0), 0) / rated.length
          : null,
      };
    }),
  },
};
