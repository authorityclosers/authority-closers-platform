import type {
  ReportEvidence,
  SalesReport,
  Transcript,
} from "../../../report-contract";
import { REPORT_REVIEW_STATUS } from "../../../report-contract";

/**
 * The binding spec's own fictional example (9 Oct): Amit Sharma, a 25:08 call
 * about a 12-week Business Coaching Program. Invented words for layout and
 * interaction checks only; no recording, customer or provider call exists.
 */
const SELLER = "spk_seller";
const PROSPECT = "spk_prospect";

const t = (minutes: number, seconds: number) => (minutes * 60 + seconds) * 1000;

const LINES: [string, number, number, number, number, string][] = [
  [
    SELLER,
    0,
    4,
    0,
    12,
    "Hi Amit, thanks for making time today. Is this still a good moment to talk for about twenty-five minutes?",
  ],
  [PROSPECT, 0, 13, 0, 19, "Yes, this is fine. I have blocked the time."],
  [
    SELLER,
    0,
    20,
    0,
    41,
    "Great. Before I share anything about the program, I'd like to understand your agency and where you want to take it. Is that okay?",
  ],
  [PROSPECT, 0, 42, 0, 47, "Sure, go ahead."],
  [
    SELLER,
    2,
    31,
    2,
    52,
    "Tell me a little about the agency today. How many people are on the team?",
  ],
  [
    PROSPECT,
    2,
    53,
    3,
    17,
    "We are eight people now. Mostly performance marketing and a bit of content.",
  ],
  [
    SELLER,
    3,
    18,
    3,
    40,
    "That's a good size, and you built it yourself. How do new clients usually come in?",
  ],
  [
    PROSPECT,
    3,
    41,
    4,
    20,
    "Mostly referrals and some inbound. But it is not consistent. Some months are full, some months are dry.",
  ],
  [SELLER, 5, 2, 5, 20, "And where is revenue right now, roughly per month?"],
  [
    PROSPECT,
    5,
    21,
    5,
    40,
    "Between four and five lakh a month, depending on the month.",
  ],
  [SELLER, 6, 20, 6, 34, "Where would you like it to be?"],
  [
    PROSPECT,
    6,
    35,
    6,
    58,
    "Right now we stay around four or five lakh. I want to reach ten lakh consistently.",
  ],
  [
    SELLER,
    6,
    59,
    7,
    14,
    "So roughly doubling, and consistently. What has stopped that from happening so far?",
  ],
  [
    PROSPECT,
    7,
    15,
    7,
    52,
    "Honestly, most of the sales still depend on me. I take almost every important call.",
  ],
  [
    SELLER,
    8,
    20,
    8,
    51,
    "That's common for founders. Does the team handle any sales calls on their own?",
  ],
  [
    PROSPECT,
    8,
    52,
    9,
    17,
    "If I am not personally involved, my team doesn't close properly.",
  ],
  [
    SELLER,
    9,
    18,
    10,
    5,
    "Got it. That's exactly where our coaching helps. We build a sales system and train your team so they can close without you.",
  ],
  [PROSPECT, 10, 6, 10, 30, "Okay. That sounds useful."],
  [
    PROSPECT,
    11,
    18,
    11,
    36,
    "So how exactly will this coaching help my sales team perform without me?",
  ],
  [
    SELLER,
    11,
    37,
    12,
    40,
    "Good question. The program runs for twelve weeks. Every week we work on one part of your sales process, and your team practises it on real calls.",
  ],
  [
    SELLER,
    13,
    6,
    14,
    40,
    "We cover weekly sessions, sales systems, hiring, team training, accountability, SOPs and the wider business strategy, so the whole engine improves together.",
  ],
  [PROSPECT, 14, 41, 14, 45, "Okay."],
  [
    PROSPECT,
    17,
    24,
    17,
    40,
    "If we start this, will you work directly with my sales team also?",
  ],
  [
    SELLER,
    17,
    41,
    18,
    41,
    "Yes. From week three your team joins the sessions, and we review their calls with them.",
  ],
  [
    SELLER,
    18,
    42,
    19,
    20,
    "And that's the point: you get a team that can sell without you on every call, so you can focus on growing the agency.",
  ],
  [PROSPECT, 19, 21, 19, 40, "That would really change things for me."],
  [PROSPECT, 20, 5, 20, 31, "What is the investment for this?"],
  [
    SELLER,
    20,
    32,
    20,
    50,
    "The program investment is two lakh rupees, for the full twelve weeks.",
  ],
  [
    PROSPECT,
    20,
    51,
    21,
    10,
    "Okay. I will need to discuss this with my partner.",
  ],
  [
    PROSPECT,
    21,
    48,
    22,
    13,
    "He handles finance. Anything above one lakh we decide together.",
  ],
  [
    SELLER,
    22,
    14,
    22,
    46,
    "That makes sense. What would your partner need to understand before deciding?",
  ],
  [
    PROSPECT,
    22,
    47,
    23,
    30,
    "Mainly the results, and how much time the team will need to give.",
  ],
  [
    SELLER,
    23,
    50,
    24,
    11,
    "Would it help if I send a short program summary and a case study you can share with him?",
  ],
  [
    PROSPECT,
    24,
    12,
    24,
    40,
    "Yes, send that. Let's speak again on Friday at four, after I talk to him.",
  ],
  [
    SELLER,
    24,
    41,
    25,
    0,
    "Perfect. Friday, four PM. I'll send the summary and the case study today.",
  ],
  [PROSPECT, 25, 1, 25, 8, "Thanks. Talk on Friday."],
];

export const amitTranscript = {
  revision: "fixture-amit-r1",
  timebase_id: "fixture-amit-timebase",
  duration_ms: t(25, 8),
  segments: LINES.map(([speaker, sm, ss, em, es, text], index) => ({
    id: `a${index + 1}`,
    speaker_id: speaker,
    start_ms: t(sm, ss),
    end_ms: t(em, es),
    text,
  })),
} as unknown as Transcript;

const at = (n: number): ReportEvidence => {
  const segment = amitTranscript.segments[n - 1];
  return {
    segment_id: segment.id,
    quote: segment.text,
    start_ms: segment.start_ms,
    end_ms: segment.end_ms,
  };
};

export const AMIT_SPEAKERS = { seller: SELLER, prospect: PROSPECT };

const dimension = (
  dimension_id: string,
  label: string,
  call_state:
    | "strongly_demonstrated"
    | "observed"
    | "needs_attention"
    | "insufficient_evidence"
    | "not_applicable",
  observation: string,
  evidence: ReportEvidence[],
) => ({
  dimension_id,
  label,
  status: "observed",
  observation,
  citations: [],
  evidence,
  call_state,
});

export const amitReport = {
  summary:
    "You understood that Amit wants to grow his agency from around ₹4–5 lakh to ₹10 lakh per month and reduce his own involvement in every sale.",
  summary_evidence: [at(12), at(14)],
  strengths: [
    {
      title: "You connected the problem to a business outcome",
      explanation:
        "Amit said he is involved in almost every important sale. You linked the coaching program to a stronger sales process and less founder dependency.",
      evidence: [at(25)],
    },
    {
      title: "You explored the revenue goal clearly",
      explanation:
        "You confirmed that Amit wants to move from roughly ₹4–5 lakh/month toward ₹10 lakh/month.",
      evidence: [at(12)],
    },
    {
      title: "You handled the partner discussion without pressure",
      explanation:
        "When Amit said he wanted to speak with his partner, you asked what his partner would need to understand before deciding.",
      evidence: [at(31)],
    },
  ],
  missed_opportunities: [
    {
      title: "The team problem could have been explored deeper",
      explanation:
        "Amit said his team does not close without him; the reason was not explored before the solution.",
      evidence: [at(16)],
    },
  ],
  improvements: [
    {
      title: "The root sales problem remained unclear",
      explanation:
        "You established that Amit's team struggles without him, but did not identify why before explaining the program.",
      evidence: [at(16)],
    },
    {
      title: "The presentation became too broad",
      explanation:
        "You explained weekly sessions, sales systems, hiring, training, accountability, SOPs and strategy before confirming which mattered most to Amit.",
      evidence: [at(21)],
    },
    {
      title: "Partner involvement was discovered late",
      explanation:
        "The business partner became important only after the price discussion.",
      evidence: [at(30)],
    },
  ],
  objection_analysis: [
    {
      title: "The decision needs the partner",
      explanation:
        "Amit wants to discuss the ₹2 lakh investment with his partner. The call does not yet show whether this is a price concern, a stakeholder step or a normal decision process.",
      evidence: [at(29)],
    },
  ],
  closing_analysis: [
    {
      title: "A specific follow-up was agreed",
      explanation:
        "The call ended with Friday at 4:00 PM instead of an open-ended “I'll get back to you”.",
      evidence: [at(34)],
    },
  ],
  verdict:
    "A well-connected conversation that moved to the solution before the team problem was diagnosed.",
  review_status: REPORT_REVIEW_STATUS,
  source_label: "Fictional spec example · no recording",
  transcript_revision: "fixture-amit-r1",
  report_sections: [],
  dimensions: [
    dimension(
      "human_connection_trust",
      "Human Connection & Trust",
      "strongly_demonstrated",
      "You kept the conversation respectful and let Amit speak openly about business problems without it feeling like an interrogation.",
      [at(7)],
    ),
    dimension(
      "discovery_deep_understanding",
      "Discovery & Deep Understanding",
      "needs_attention",
      "You understood Amit's revenue, team size and founder dependency, but did not diagnose why sales drop when he is absent.",
      [at(16)],
    ),
    dimension(
      "qualification",
      "Qualification",
      "observed",
      "You confirmed business size, revenue and the growth target. The partner's role in the decision came up late.",
      [at(30)],
    ),
    dimension(
      "problem_impact_desire",
      "Problem, Impact & Desire Clarity",
      "observed",
      "The desired outcome of about ₹10 lakh/month became clear. The cost of staying founder-dependent was not quantified.",
      [at(12), at(16)],
    ),
    dimension(
      "solution_relevance_presentation",
      "Solution Relevance & Presentation",
      "observed",
      "The program was connected to sales systems and team independence, but several elements were presented before the main problem was identified.",
      [at(21)],
    ),
    dimension(
      "certainty_objection_intelligence",
      "Certainty & Objection Intelligence",
      "observed",
      "When Amit mentioned his partner, you explored what the partner needs instead of pushing against it.",
      [at(31)],
    ),
    dimension(
      "closing_decision_management",
      "Closing & Decision Management",
      "strongly_demonstrated",
      "The call did not end with “let me know”. A specific next conversation was agreed for Friday at 4:00 PM.",
      [at(34)],
    ),
    dimension(
      "communication_tonality",
      "Communication & Tonality",
      "observed",
      "Your tone stayed calm and conversational. One part of the program explanation became long, with little input from Amit.",
      [at(21)],
    ),
  ],
  overview: {
    version: "dipak-14-point-v1",
    diagnosis: {
      text: "Amit clearly saw the value of reducing founder dependency, but the exact reason his sales team fails without him remained partly unexplored.",
      evidence: [at(16), at(25)],
    },
    outcome: {
      kind: "follow_up",
      text: "Amit is interested but wants to discuss the ₹2 lakh investment with his business partner before deciding.",
      evidence: [at(29), at(34)],
    },
    business_impact: {
      status: "insufficient_data",
      missing_inputs: [
        "What specifically stops the sales team from closing without Amit?",
        "Is partner approval required, or is it a consultation?",
        "Is the ₹2 lakh investment itself a concern?",
        "By when does Amit want to reach ₹10 lakh/month?",
      ],
    },
    strength_details: [
      {
        finding_index: 0,
        why_it_matters:
          "The solution felt connected to Amit's actual business goal instead of sounding like generic coaching.",
      },
      {
        finding_index: 1,
        why_it_matters:
          "It gave the conversation a clear business outcome to work toward.",
      },
      {
        finding_index: 2,
        why_it_matters:
          "It kept the decision open while uncovering another stakeholder.",
      },
    ],
    improvement_details: [
      {
        finding_index: 0,
        what_happened: {
          text: "You moved toward explaining sales systems and training.",
          evidence: [at(17)],
        },
        why_it_matters:
          "You had to present the coaching program with only a partial diagnosis.",
        replacement_behavior:
          "Ask what specifically goes wrong when Amit is not on the call.",
        business_impact: { status: "insufficient_data", missing_inputs: [] },
      },
      {
        finding_index: 1,
        what_happened: {
          text: "The program explanation covered seven elements.",
          evidence: [at(21)],
        },
        why_it_matters:
          "The presentation became less focused on his highest-priority problem.",
        replacement_behavior: "Confirm the top problem before presenting.",
        business_impact: { status: "insufficient_data", missing_inputs: [] },
      },
      {
        finding_index: 2,
        what_happened: {
          text: "The partner was mentioned only after the price.",
          evidence: [at(30)],
        },
        why_it_matters: "A key decision-maker was not considered earlier.",
        replacement_behavior: "Ask early who else is part of the decision.",
        business_impact: { status: "insufficient_data", missing_inputs: [] },
      },
    ],
    golden_moments: [
      {
        strength_index: 1,
        evidence_index: 0,
        why_effective:
          "This gave you a measurable business goal and a useful anchor for the opportunity.",
      },
      {
        strength_index: 2,
        evidence_index: 0,
        why_effective:
          "It kept the decision discussion open while uncovering another stakeholder.",
      },
    ],
    missed_details: [
      {
        finding_index: 0,
        prospect_signal: {
          text: "If I am not personally involved, my team doesn't close properly.",
          evidence: [at(16)],
        },
        closer_response: {
          text: "Explaining sales systems and training.",
          evidence: [at(17)],
        },
        follow_up:
          "What specifically goes wrong when Amit is not involved: qualification, discovery, presentation, negotiation, closing or management?",
        potential_impact:
          "Without this diagnosis, the solution had to be presented broadly.",
      },
    ],
    prospect_interpretations: [
      {
        source: {
          text: "Okay. I will need to discuss this with my partner.",
          evidence: [at(29)],
        },
        possible_concern:
          "The investment amount may be a concern, but Amit has not said so.",
        interpretation_kind: "inference",
      },
    ],
    rewatch: [
      {
        text: "The program explanation ran long with little input from Amit.",
        purpose: "watch",
        evidence: [at(21)],
      },
    ],
    conversation_change: {
      before: {
        text: "You were understanding Amit's business, revenue goal and his part in every sale.",
        evidence: [at(14)],
      },
      change: {
        text: "Amit asked how the program would help his team sell without him.",
        evidence: [at(19)],
      },
      after: {
        text: "You explained the coaching model, implementation, investment and next steps.",
        evidence: [at(20)],
      },
      possible_effect:
        "From here the conversation moved from understanding the business into explaining the program.",
      interpretation_kind: "inference",
    },
    ethics_notes: [],
    next_call_focus: {
      improvement_index: 0,
      behavior: "Before explaining a solution, diagnose one level deeper.",
      target:
        "Ask what specifically goes wrong when the founder is not involved.",
    },
    practice: {
      improvement_index: 0,
      instructions:
        "When a prospect names a team problem, ask two diagnostic questions before you describe the program.",
      success_condition:
        "You can name the specific stage where the team loses deals.",
    },
    progress: null,
    final_assessment: {
      repeat: "Keep linking the offer to the founder's own goal, in his words.",
      fix_first:
        "Diagnose why the team fails without the founder before presenting.",
      next_focus:
        "On Friday, first understand what came out of the partner discussion before presenting anything new.",
      assessment:
        "You connected the coaching program well to his founder-dependency problem, but moved into explaining the program before fully understanding why his team struggles to close on its own. Amit showed clear interest, asked about implementation and price, and said he needs to discuss the investment with his partner.",
    },
  },
  story: {
    version: "report-story/1",
    phases: [
      { name: "opening", start_ms: 0 },
      { name: "discovery", start_ms: t(2, 30) },
      { name: "pitch", start_ms: t(11, 18) },
      { name: "close", start_ms: t(20, 5) },
      { name: "objection", start_ms: t(20, 51) },
      { name: "close", start_ms: t(23, 50) },
    ],
    outcome: {
      kind: "follow_up",
      next_step_rung: "dated_call",
      next_step_when: "Friday · 4:00 PM",
      evidence: [at(34)],
    },
    next_step: {
      text: "Amit will discuss the investment with his business partner. Follow-up: Friday · 4:00 PM.",
      evidence: [at(34)],
    },
    prospect_commitments: [
      {
        text: "Discuss the program with his partner before Friday.",
        evidence: [at(34)],
        effort_ms: null,
      },
    ],
    seller_commitments: [
      {
        text: "Send the program summary and a relevant case study",
        due_text: "today",
        evidence: [at(35)],
      },
    ],
  },
} as unknown as SalesReport;
