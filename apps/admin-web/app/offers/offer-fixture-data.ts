/** A fictional offer for the dev-only review page and tests; numbers and words are invented. */
import { fromTemplate, newId, type Offer } from "./offer-model";

export function fixtureOffer(): Offer {
  const base = fromTemplate("team-calls", undefined, "2026-10-23T00:00:00Z");
  const worth = [24000, 18000, 30000, 36000, 12000, 15000, 20000, 25000, 6000];
  return {
    ...base,
    name: "Fictional team offer",
    stack: base.stack.map((item, index) => ({
      ...item,
      worth: worth[index] ?? 5000,
    })),
    value: {
      dream: { text: "Every seller sells like the team's best one", score: 9 },
      likelihood: { text: "A Report on the first call they make", score: 7 },
      time: { text: "First coaching within minutes of a call", score: 2 },
      effort: {
        text: "Nothing to upload: the phone files every call",
        score: 2,
      },
    },
    obstacles: [
      {
        id: newId("obstacle"),
        problem: "Sellers won't upload their calls",
        solution: "The phone records and files every call by itself",
        featureId: "dialler-recordings",
      },
      {
        id: newId("obstacle"),
        problem: "Managers have no time to listen",
        solution: "Each call comes back as a one-screen Report",
        featureId: "the-report",
      },
    ],
    bonuses: [
      {
        id: newId("bonus"),
        name: "Lead stages set up with you",
        worth: 15000,
        solves: "Day-one setup feels like work",
      },
    ],
    guarantee: {
      kind: "conditional",
      text: "Fictional: if the team gets no Report in 14 days, setup is on us.",
    },
    scarcity: "Fictional: 10 onboarding slots a month",
    urgency: "Fictional: founding price until the next cohort",
    naming: {
      magnet: "Founding",
      avatar: "Sales Team",
      goal: "Close-More",
      interval: "30-Day",
      container: "System",
      chosen: "Founding Sales Team Close-More System",
    },
    positioning: {
      forWho: "owners of small sales teams",
      need: "can't hear what happens on their calls",
      category: "sales CRM that listens to every call",
      benefit: "turns each call into coaching and the next step",
      unlike: "dialers that only count calls",
      because: "knows what was said and what to do about it",
    },
    icp: {
      who: "Fictional: service businesses with phone sales",
      size: "5-50 sellers",
      buyer: "Owner or sales head",
      pains: "Leads go cold; no idea why deals are lost",
      triggers: "A bad month; a new sales hire",
      objections: "Sellers won't use it (answer: nothing to do)",
      where: "Owner communities, referrals",
    },
    voice: {
      tones: ["Confident", "Plain-spoken", "Warm"],
      say: "Calls, closes, coaching",
      never: "AI magic, guaranteed revenue",
      tagline: "Hear every call. Coach every seller.",
      pitch: "Fictional pitch for review only.",
    },
    tiers: [
      {
        id: newId("tier"),
        name: "Starter",
        monthly: 4999,
        yearly: 49990,
        seats: "Up to 3",
        minutes: "1,000 a month",
        featureIds: base.stack.slice(0, 5).map((s) => s.featureId),
        highlight: false,
        note: "Fictional",
      },
      {
        id: newId("tier"),
        name: "Team",
        monthly: 14999,
        yearly: 149990,
        seats: "Up to 15",
        minutes: "5,000 a month",
        featureIds: base.stack.map((s) => s.featureId),
        highlight: true,
        note: "Fictional",
      },
    ],
    ideas: [
      {
        id: newId("idea"),
        text: "Free first-week call audit",
        column: "try",
        votes: 3,
      },
      {
        id: newId("idea"),
        text: "Cohort onboarding every month",
        column: "keep",
        votes: 2,
      },
      { id: newId("idea"), text: "Per-call pricing", column: "idea", votes: 1 },
    ],
  };
}
