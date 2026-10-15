import type { Line } from "../report-story-model";
import {
  POINTERS,
  type OutcomeKind,
  type Pointer,
  type PointerStatus,
  type XrayView,
} from "./model";

/**
 * The 15 Oct doc's illustrative example, word for word where the doc has
 * words. Fictional people and numbers; shown only on the review fixture with
 * an "Illustrative example" mark, never on a real call.
 */

const line = (text: string): Line => ({ text, sources: [] });

type Feedback = Pick<
  Pointer,
  "whatHappened" | "whyItMatters" | "evidence" | "howToImprove" | "training"
>;

const you = (at: string, text: string) => quote("you", at, text);
const prospect = (at: string, text: string) => quote("prospect", at, text);
function quote(who: "you" | "prospect", at: string, text: string) {
  const [minutes, seconds] = at.split(":").map(Number);
  return {
    who,
    name: null,
    at_ms: (minutes * 60 + seconds) * 1000,
    text,
    source: null,
  };
}

/** Image10, the doc's expanded pointer. */
const NEEDS: Feedback = {
  whatHappened:
    "You asked a few questions about their sales targets, but did not go deep enough to understand their key challenges. The prospect mentioned issues with lead quality, but the conversation quickly moved to your solution without fully exploring the impact of this problem.",
  whyItMatters:
    "Without a deep understanding of their real challenges, it becomes difficult to position your solution effectively and create urgency. Discovery helps you connect your solution to what truly matters to the prospect.",
  evidence: [
    prospect("04:12", "Yes, we do get low quality leads sometimes..."),
    you(
      "04:35",
      "Our program can help you get better leads and close more sales.",
    ),
  ],
  howToImprove: [
    "Ask more open-ended questions to understand the root cause of their challenges.",
    "Explore the impact of the problem on their business (revenue, time, resources).",
    "Use follow-up questions like “Can you tell me more about that?” or “How does that affect your team?”",
  ],
  training: {
    title: "Asking Powerful Discovery Questions",
    minutes: 5,
    href: null,
  },
};

/** Short illustrative feedback for the other evaluated pointers (image9's lines). */
const FEEDBACK: Record<string, Feedback> = {
  call_opening: {
    whatHappened:
      "You introduced yourself, your company, and the purpose of the call clearly.",
    whyItMatters:
      "A clear, confident start earns the prospect's attention for the rest of the call.",
    evidence: [
      you("00:08", "Hi Siddhant, this is Swamini from Authority Closers."),
    ],
    howToImprove: [
      "Add one line on what the prospect gets from the next 20 minutes.",
    ],
    training: { title: "Opening a Sales Call", minutes: 4, href: null },
  },
  tone_energy: {
    whatHappened:
      "You maintained a positive and confident tone throughout the call.",
    whyItMatters:
      "Energy is contagious: a calm, upbeat tone keeps the prospect engaged.",
    evidence: [
      you("02:40", "That's a great question, let me walk you through it."),
    ],
    howToImprove: ["Slow down slightly when you explain the program."],
    training: { title: "Voice and Tonality", minutes: 6, href: null },
  },
  active_listening: {
    whatHappened:
      "You cut in a few times while the prospect was still explaining their situation.",
    whyItMatters:
      "When prospects feel heard they share more, and you learn what really matters to them.",
    evidence: [
      prospect("06:02", "What I really struggle with is…"),
      you("06:04", "Right, and that's exactly where we help."),
    ],
    howToImprove: [
      "Let the prospect finish, then pause for a second before you answer.",
      "Repeat back what you heard in their own words.",
    ],
    training: { title: "Listening to Understand", minutes: 5, href: null },
  },
  open_ended_questions: {
    whatHappened:
      "You used open questions to get the prospect talking about their goals.",
    whyItMatters:
      "Open questions uncover needs that yes/no questions never reach.",
    evidence: [
      you("03:15", "What does a good month look like for you right now?"),
    ],
    howToImprove: ["Follow each open question with one deeper “why”."],
    training: {
      title: "Asking Powerful Discovery Questions",
      minutes: 5,
      href: null,
    },
  },
  prospect_role: {
    whatHappened:
      "You clarified the prospect's role and decision-making authority.",
    whyItMatters: "Knowing who decides tells you who else must be convinced.",
    evidence: [
      prospect("05:20", "I run the team, but my partner signs off on spends."),
    ],
    howToImprove: [
      "Ask how their partner usually decides on investments like this.",
    ],
    training: { title: "Mapping the Decision", minutes: 4, href: null },
  },
  needs_challenges: NEEDS,
  decision_process: {
    whatHappened:
      "You explored their decision-making process, stakeholders, and timeline.",
    whyItMatters:
      "A clear path to a decision makes the next step easy to agree on.",
    evidence: [
      prospect("15:10", "We usually decide within a week of the proposal."),
    ],
    howToImprove: [
      "Confirm the date they will decide before you end the call.",
    ],
    training: { title: "Mapping the Decision", minutes: 4, href: null },
  },
  solution_value: {
    whatHappened:
      "You connected your solution to their specific needs and challenges.",
    whyItMatters:
      "Value lands when it answers the problem the prospect described.",
    evidence: [
      you("11:30", "This module fixes the follow-up gap you mentioned."),
    ],
    howToImprove: [
      "Use the prospect's own words when you link a feature to a need.",
    ],
    training: { title: "Presenting with Purpose", minutes: 6, href: null },
  },
  concerns_check: {
    whatHappened:
      "You asked if they had any other concerns before moving forward.",
    whyItMatters: "Hidden concerns stall deals after the call ends.",
    evidence: [
      you("17:45", "Is there anything that would stop you from moving ahead?"),
    ],
    howToImprove: ["Ask once more after you summarise the next steps."],
    training: { title: "Surfacing Hidden Objections", minutes: 5, href: null },
  },
  next_steps: {
    whatHappened: "You clearly defined and agreed on the next steps.",
    whyItMatters: "A dated next step keeps the deal moving.",
    evidence: [
      you("18:50", "Shall we speak again on Sunday between 4 and 5 PM?"),
    ],
    howToImprove: [
      "Send a short written recap of the agreed steps the same day.",
    ],
    training: { title: "Closing for the Next Step", minutes: 4, href: null },
  },
  question_talk_ratio: {
    whatHappened:
      "You spoke for most of the call and asked fewer questions than needed.",
    whyItMatters: "Prospects buy when they talk themselves into the need.",
    evidence: [
      you("09:00", "So let me explain the full program structure first…"),
    ],
    howToImprove: [
      "Aim to ask a question at least every two minutes.",
      "Stop after each explanation and check how it lands.",
    ],
    training: { title: "Talk Less, Sell More", minutes: 5, href: null },
  },
  professionalism: {
    whatHappened:
      "You maintained a professional and respectful tone throughout the call.",
    whyItMatters: "Respect builds the trust a buying decision needs.",
    evidence: [you("19:10", "Thank you for your time, Siddhant.")],
    howToImprove: ["Keep it up."],
    training: null,
  },
  building_rapport: {
    whatHappened:
      "You made a genuine effort to build rapport and create a comfortable conversation.",
    whyItMatters: "Prospects open up to people they feel comfortable with.",
    evidence: [you("01:05", "How has your week been so far?")],
    howToImprove: [
      "Link the small talk to something they said about their work.",
    ],
    training: { title: "Building Trust Early", minutes: 4, href: null },
  },
  presenting_solution: {
    whatHappened:
      "You connected your solution to their specific needs and challenges.",
    whyItMatters: "A tailored presentation feels like help, not a pitch.",
    evidence: [
      you(
        "10:20",
        "Given your lead-quality issue, here is how we would start.",
      ),
    ],
    howToImprove: ["Show one example from a business like theirs."],
    training: { title: "Presenting with Purpose", minutes: 6, href: null },
  },
  creating_value: {
    whatHappened:
      "You clearly communicated the value and benefits of your solution.",
    whyItMatters: "Clear value makes the price feel smaller.",
    evidence: [
      you(
        "12:40",
        "Most advisors double their closed policies in three months.",
      ),
    ],
    howToImprove: ["Put a number on the value for this prospect."],
    training: { title: "Selling the Outcome", minutes: 5, href: null },
  },
  overall_communication: {
    whatHappened:
      "Your communication was clear, structured, and easy to follow.",
    whyItMatters: "A clear call is easy to remember and easy to say yes to.",
    evidence: [you("19:00", "To sum up, we agreed three things today.")],
    howToImprove: ["Summarise the call in three points before you close."],
    training: null,
  },
};

/** Image6's status and score per pointer; the four image9-only pointers use image9's. */
const RESULTS: Record<string, [PointerStatus, number | null]> = {
  call_opening: ["good", 85],
  purpose_agenda: ["not_observed", null],
  tone_energy: ["good", 82],
  active_listening: ["needs_improvement", 48],
  open_ended_questions: ["good", 78],
  enough_questions: ["insufficient_evidence", null],
  prospect_role: ["good", 80],
  needs_challenges: ["needs_improvement", 45],
  current_solution: ["not_observed", null],
  business_impact: ["not_applicable", null],
  decision_process: ["good", 75],
  stakeholders: ["not_observed", null],
  objections: ["not_applicable", null],
  solution_value: ["good", 78],
  pricing: ["not_observed", null],
  competition: ["insufficient_evidence", null],
  concerns_check: ["good", 77],
  next_steps: ["good", 83],
  call_control: ["not_observed", null],
  question_talk_ratio: ["needs_improvement", 52],
  handling_silence: ["not_applicable", null],
  professionalism: ["good", 84],
  closing_attitude: ["not_observed", null],
  building_rapport: ["good", 80],
  presenting_solution: ["good", 78],
  creating_value: ["good", 80],
  overall_communication: ["good", 80],
};

const EMPTY: Feedback = {
  whatHappened: null,
  whyItMatters: null,
  evidence: [],
  howToImprove: [],
  training: null,
};

const EXAMPLE_POINTERS: Pointer[] = POINTERS.map((pointer, index) => {
  const [status, score] = RESULTS[pointer.id];
  return {
    ...pointer,
    number: index + 1,
    status,
    score,
    ...(FEEDBACK[pointer.id] ?? EMPTY),
  };
});

const OVERVIEW: XrayView["overview"] = {
  summary: line(
    "Swamini spoke with Siddhant Pawar, an LIC insurance advisor, to understand his sales goals and current challenges. They discussed his target customers, product positioning, and common objections he faces. Siddhant showed interest in learning more about our program. A follow-up discussion has been scheduled for Sunday between 4:00 and 5:00 PM.",
  ),
  score: {
    value: 78,
    label: "Good",
    line: "The call was handled well overall, with clear strengths and a few key areas to improve.",
  },
  stats: {
    duration: { value: "19:30", sub: "19 min 30 sec" },
    talk: { value: "74 : 26", sub: "Salesperson : Prospect" },
    questions: { value: "25 : 10", sub: "Salesperson : Prospect" },
    longest: { value: "01:53", sub: "1 min 53 sec" },
  },
  strength: line(
    "You built rapport well and asked relevant questions to understand the prospect's requirements before presenting your solution.",
  ),
  improvement: line(
    "You moved to the pitch before fully quantifying the prospect's problem and its business impact. Explore the cost of inaction before presenting your solution.",
  ),
};

const STAGES = [
  "Initial Contact",
  "Discovery",
  "Solution Presentation",
  "Negotiation",
];

/** Images 2 (won), 4 (lost), 1 (follow-up set) and 11 (decision pending). */
const OUTCOMES: Record<OutcomeKind, XrayView["outcome"]> = {
  won: {
    kind: "won",
    label: null,
    origin: "person",
    detail: line(
      "The prospect showed strong interest and agreed to move forward with the proposed solution.",
    ),
    value: { amount: "₹12,50,000", note: "(Annual Contract Value)" },
    date: "15 Oct 2024",
    stages: STAGES,
    reasons: [
      line(
        "Clearly understood the prospect's key challenges (low lead quality).",
      ),
      line("Solution aligned well with their business goals."),
      line(
        "Addressed budget concerns with clear ROI and flexible payment options.",
      ),
      line("Built strong trust and confidence throughout the call."),
    ],
    objections: [
      line("“It's too expensive.” – Explained ROI and shared case studies."),
      line(
        "“We need to discuss with the team.” – Scheduled internal discussion and provided additional resources.",
      ),
    ],
    nextSteps: [
      {
        text: "Send contract and detailed proposal",
        date: "16 Oct 2024",
        owner: "you",
        source: null,
      },
      {
        text: "Receive signed contract",
        date: "18 Oct 2024",
        owner: "prospect",
        source: null,
      },
      {
        text: "Process initial payment",
        date: "20 Oct 2024",
        owner: "you",
        source: null,
      },
    ],
    notes: [
      line(
        "The prospect was very positive about our methodology and client success stories.",
      ),
      line("They want to involve their technical team during onboarding."),
    ],
    suggested:
      "Prepare onboarding resources and share a timeline for implementation.",
  },
  lost: {
    kind: "lost",
    label: null,
    origin: "person",
    detail: line(
      "The prospect decided not to move forward with the proposed solution at this time.",
    ),
    value: { amount: "₹8,00,000", note: "(Annual Contract Value)" },
    date: "17 Oct 2024",
    stages: STAGES,
    reasons: [
      line("Chose an in-house solution for now."),
      line("Budget constraints for this quarter."),
      line("Looking for a lower-priced alternative in the market."),
    ],
    objections: [
      line("“It's too expensive for our current budget.”"),
      line("“We want to explore internal resources first.”"),
    ],
    nextSteps: [],
    notes: [
      line(
        "The prospect appreciated the value but decided to delay the investment.",
      ),
      line("They may reconsider next year when their budget cycle resets."),
      line(
        "Keep them warm by sharing relevant insights and occasional updates.",
      ),
    ],
    suggested:
      "Consider reconnecting in 3–6 months to check if their priorities or budget have changed.",
  },
  follow_up: {
    kind: "follow_up",
    label: null,
    origin: "person",
    detail: line(
      "The prospect showed interest. A follow-up call has been scheduled to continue the discussion.",
    ),
    value: { amount: "₹12,50,000", note: "(Estimated from the conversation)" },
    date: "22 Oct 2024",
    stages: STAGES,
    reasons: [
      line("Showed strong interest in the solution."),
      line("Needs to discuss internally with their team."),
      line("Wants more information on pricing and implementation."),
      line("Requested a detailed proposal."),
    ],
    objections: [
      line("Need to validate ROI with the leadership team."),
      line("Questions about implementation timeline."),
      line("Concerns about budget approval process."),
    ],
    nextSteps: [
      {
        text: "Share detailed proposal and pricing",
        date: "16 Oct 2024",
        owner: "you",
        source: null,
      },
      {
        text: "Prospect to discuss with internal team",
        date: "20 Oct 2024",
        owner: "prospect",
        source: null,
      },
      {
        text: "Follow-up call to address final questions",
        date: "22 Oct 2024",
        owner: "you",
        source: null,
      },
    ],
    notes: [
      line("The prospect was positive about our approach and case studies."),
      line(
        "They shared that 2–3 stakeholders will be involved in the decision.",
      ),
      line("They requested a comparative proposal with both options."),
    ],
    suggested: "Prepare the detailed proposal and send before the next call.",
  },
  decision_pending: {
    kind: "decision_pending",
    label: null,
    origin: "person",
    detail: line(
      "The prospect is evaluating the proposal internally and will share their decision.",
    ),
    value: { amount: "₹18,00,000", note: "(Estimated from the conversation)" },
    date: "30 Oct 2024",
    stages: STAGES,
    reasons: [
      line("Prospect sees strong value in the solution."),
      line("Needs internal approval from the leadership team."),
      line("Wants to evaluate pricing with other options."),
      line("Requested additional information and case studies."),
    ],
    objections: [
      line("Would like to review ROI with their finance team."),
      line("Concerns about implementation timeline."),
      line("Comparing with 1–2 other vendors."),
      line("Wants more details on onboarding and support."),
    ],
    nextSteps: [
      {
        text: "Send additional case studies",
        date: "16 Oct 2024",
        owner: "you",
        source: null,
      },
      {
        text: "Prospect to review with leadership team",
        date: "30 Oct 2024",
        owner: "prospect",
        source: null,
      },
      {
        text: "Follow up for final decision",
        date: "31 Oct 2024",
        owner: "you",
        source: null,
      },
    ],
    notes: [
      line("The prospect was impressed with our solution and approach."),
      line("Final decision depends on internal budget approval."),
      line("They may revert earlier if approval comes through sooner."),
    ],
    suggested:
      "Share the requested documents and schedule a follow-up after 30 Oct 2024 to get their decision.",
  },
};

export const EXAMPLE_KINDS = Object.keys(OUTCOMES) as OutcomeKind[];

export function exampleView(kind: OutcomeKind = "follow_up"): XrayView {
  return {
    illustrative: true,
    guest: false,
    overview: OVERVIEW,
    pointers: EXAMPLE_POINTERS,
    outcome: OUTCOMES[kind],
  };
}
