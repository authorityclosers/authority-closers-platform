import type { ReportEvidence } from "../../../report-contract";
import type { ReportPillars } from "../../../report-pillars-contract";
import { amitTranscript } from "./amit-call";

/** Line n of the fictional Amit call (a1 … a36), quoted in full. */
const at = (n: number): ReportEvidence => {
  const segment = amitTranscript.segments[n - 1];
  return {
    segment_id: segment.id,
    quote: segment.text,
    start_ms: segment.start_ms,
    end_ms: segment.end_ms,
  };
};
const note = (text: string, ...lines: number[]) => ({
  text,
  evidence: lines.map(at),
});
const t = (minutes: number, seconds: number) => (minutes * 60 + seconds) * 1000;

/**
 * Dipak's own example (spec 9 Oct, section 1) as the analysis would write it
 * for the fictional Amit Sharma call: every sentence is the document's, every
 * play link a line of the fixture. Sample content only; never hard-coded.
 */
export const AMIT_PILLARS: ReportPillars = {
  version: "report-pillars/1",
  outcome: {
    status: "Decision Pending",
    line: "Amit is interested in the coaching program but wants to discuss the ₹2 lakh investment with his business partner before deciding.",
    evidence: [at(29)],
  },
  summary:
    "You understood that Amit wants to grow his agency from around ₹4–5 lakh to ₹10 lakh per month and reduce his own involvement in every sale. You connected the coaching program well to his founder-dependency problem, but moved into explaining the program before fully understanding why his sales team is struggling to close independently. Amit showed clear interest, asked about implementation and price, and said he needs to discuss the investment with his business partner. A follow-up call was fixed for Friday at 4:00 PM.",
  biggest_influence: note(
    "The prospect clearly saw the value of reducing founder dependency, but the exact reason his sales team fails without him remained partly unexplored.",
    16,
  ),
  strongest_part: {
    ...note(
      "You connected the program to Amit's goal of building a business that can sell without depending entirely on him.",
      25,
    ),
    short: "Value connected to founder dependency",
  },
  biggest_concern: {
    ...note(
      "You started explaining the coaching solution before understanding whether Amit's sales problem comes from lead quality, team skill, process, management or something else.",
      17,
    ),
    short: "Root sales problem only partly diagnosed",
  },
  next_step: {
    ...note("Amit will discuss the investment with his business partner.", 34),
    when: "Friday · 4:00 PM",
  },
  timeline: [
    { label: "Opening", start_ms: 0 },
    { label: "Business Context", start_ms: t(2, 30) },
    { label: "Problems & Goals", start_ms: t(7, 15) },
    { label: "Program Discussion", start_ms: t(11, 18) },
    { label: "Price & Decision", start_ms: t(18, 45) },
    { label: "Partner Objection", start_ms: t(22, 10) },
    { label: "Next Step", start_ms: t(23, 50) },
  ],
  key_change: {
    text: "From this point, the conversation moved from understanding the business into explaining the coaching program.",
    evidence: [at(19)],
    before: {
      label: "Discovery",
      text: "You were understanding Amit's business, revenue goals and dependence on himself for sales.",
    },
    after: {
      label: "Presentation + Decision",
      text: "You explained the coaching model, implementation, investment and next steps.",
    },
  },
  worked: [
    {
      title: "You connected the problem to a business outcome",
      what: "Amit said he is involved in almost every important sale. You linked the coaching program to creating a stronger sales process and reducing founder dependency.",
      evidence: [at(25)],
      why_it_helped:
        "The solution felt connected to Amit's actual business goal instead of sounding like generic business coaching.",
    },
    {
      title: "You explored the revenue goal clearly",
      what: "You confirmed that Amit wants to move from roughly ₹4–5 lakh/month toward ₹10 lakh/month.",
      evidence: [at(12)],
      why_it_helped:
        "It gave the conversation a clear business outcome to work toward.",
    },
    {
      title: "You handled the partner discussion without pressure",
      what: "When Amit said he wanted to speak with his partner, you did not immediately challenge or pressure him. Instead, you asked what his partner would need to understand before deciding.",
      evidence: [at(31)],
      why_it_helped:
        "It kept the decision discussion open while uncovering another stakeholder.",
    },
  ],
  didnt: [
    {
      title: "The root sales problem remained unclear",
      what: "You established that Amit's team struggles without him, but did not fully identify why.",
      evidence: [at(16)],
      what_it_affected:
        "You had to present the coaching program with only a partial diagnosis.",
      possible_areas: [
        "poor discovery",
        "weak closing",
        "bad lead quality",
        "no sales process",
        "weak management",
        "lack of accountability",
      ],
    },
    {
      title: "The presentation became too broad",
      what: "You explained weekly sessions, sales systems, hiring, team training, accountability, SOPs and business strategy before confirming which one mattered most to Amit.",
      evidence: [at(21)],
      what_it_affected:
        "The presentation became less focused on his highest-priority problem.",
      possible_areas: [],
    },
    {
      title: "Partner involvement was discovered late",
      what: "The business partner became important only after the price discussion.",
      evidence: [at(30)],
      what_it_affected:
        "A key decision-maker was not considered earlier in the call.",
      possible_areas: [],
    },
  ],
  moments: [
    {
      kind: "Strong Moment",
      title: "Amit shared his real growth target",
      evidence: [at(12)],
      why: "This gave you a measurable business goal and a useful anchor for understanding the opportunity.",
      moved_toward: null,
      what_was_missed: null,
      price_stated: null,
      prospect_response: null,
    },
    {
      kind: "Important Miss",
      title: "The team problem could have been explored deeper",
      evidence: [at(16)],
      why: "Without this diagnosis, the solution had to be presented broadly.",
      moved_toward: "Explaining sales systems and training.",
      what_was_missed:
        "What specifically goes wrong when Amit is not involved — qualification, discovery, presentation, negotiation, closing or management?",
      price_stated: null,
      prospect_response: null,
    },
    {
      kind: "Buying Signal",
      title: "Amit asked about implementation",
      evidence: [at(23)],
      why: "This was a useful buying and implementation signal: Amit was considering what implementation could look like.",
      moved_toward: null,
      what_was_missed: null,
      price_stated: null,
      prospect_response: null,
    },
    {
      kind: "Price Moment",
      title: "₹2 lakh investment discussed",
      evidence: [at(28)],
      why: "This introduced a new decision dependency.",
      moved_toward: null,
      what_was_missed: null,
      price_stated: { text: "₹2,00,000", evidence: [at(28)] },
      prospect_response: note(
        "Okay. I will need to discuss this with my partner.",
        29,
      ),
    },
    {
      kind: "Decision Moment",
      title: "A clear follow-up was booked",
      evidence: [at(34)],
      why: "The conversation ended with a specific next event instead of an open-ended “I'll get back to you.”",
      moved_toward: null,
      what_was_missed: null,
      price_stated: null,
      prospect_response: null,
    },
    {
      kind: "Objection",
      title: "Partner discussion",
      evidence: [at(31)],
      why: "You asked what the partner would need to understand instead of pushing against the objection.",
      moved_toward: null,
      what_was_missed: null,
      price_stated: null,
      prospect_response: null,
    },
    {
      kind: "Turning Point",
      title: "The call changed here",
      evidence: [at(19)],
      why: "From here the conversation moved from understanding the business into explaining the program.",
      moved_toward: null,
      what_was_missed: null,
      price_stated: null,
      prospect_response: null,
    },
  ],
  most_important_moment: 5,
  deeper: {
    became_clear: [
      "Amit owns an 8-person agency.",
      "Current revenue is approximately ₹4–5 lakh/month.",
      "Growth goal is ₹10 lakh/month.",
      "Sales depend heavily on Amit.",
    ],
    still_unclear: [
      "why salespeople fail without Amit",
      "sales conversion numbers",
      "exact lead quality",
      "partner's role",
      "timeframe for ₹10 lakh goal",
    ],
    opening_missed: note(
      "Amit's statement “Without me, my team doesn't close” deserved deeper diagnosis.",
      16,
    ),
    relevant: ["sales systems", "team coaching", "reducing founder dependency"],
    less_relevant:
      "Broader business strategy modules were explained before Amit expressed a need for them.",
    value_connection: "Partially established",
    price: note("₹2,00,000 discussed.", 28),
    prospect_response: note("Needs discussion with business partner.", 29),
    likely_status: [
      "real stakeholder dependency",
      "financial concern",
      "uncertainty",
      "normal decision process",
    ],
    listening: "Generally good.",
    communication_note: note(
      "During the program explanation, prospect participation reduced.",
      21,
    ),
  },
  deal: {
    position: note(
      "Amit understands the program and showed interest in implementation, but has not committed to purchasing yet.",
      23,
    ),
    blocker: {
      ...note(
        "Amit wants to discuss the investment with his business partner before deciding.",
        29,
      ),
      basis: "said",
    },
    prospect_commitments: [
      note("Discuss the program with his partner before Friday.", 34),
    ],
    seller_commitments: [
      note(
        "Send the program summary and relevant case study after the call.",
        35,
      ),
    ],
    next_event: {
      ...note("Follow-up call", 34),
      when: "Friday · 4:00 PM",
    },
    commitment_quality: "Clear",
    still_unclear: [
      "What does Amit's partner think about the investment?",
      "Is partner approval required or simply consultation?",
      "What specifically prevents Amit's sales team from performing independently?",
      "Is ₹2 lakh itself a concern?",
    ],
    deal_action:
      "On Friday, first understand what came out of the partner discussion before presenting more information.",
    coaching_mission:
      "Before explaining a solution, diagnose one level deeper.",
    coaching_mission_for: 0,
  },
};
