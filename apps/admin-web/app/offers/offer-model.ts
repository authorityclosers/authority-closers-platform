/**
 * The Offer Studio's data: offers built from catalogue features with
 * Hormozi's value equation, a value stack, bonuses, guarantee, scarcity and
 * urgency, naming, positioning, ideal customer, brand voice, internal price
 * tiers and an ideation board. Pure functions only; offer-store.ts keeps it.
 *
 * Prices here are internal (Admin only). Sales X-Ray never shows a price.
 */
import { CATALOGUE, type Feature } from "../catalogue/catalogue-data";

export const STUDIO_VERSION = 1;

export type Driver = Readonly<{ text: string; score: number }>;

export type StackItem = Readonly<{
  featureId: string;
  /** What the buyer would feel it is worth, in rupees; 0 when not set. */
  worth: number;
  /** The buyer's words for it in this offer (empty: the feature's own name). */
  label: string;
}>;

export type Obstacle = Readonly<{
  id: string;
  problem: string;
  solution: string;
  featureId: string;
}>;

export type Bonus = Readonly<{
  id: string;
  name: string;
  worth: number;
  solves: string;
}>;

export type GuaranteeKind =
  | "none"
  | "unconditional"
  | "conditional"
  | "anti"
  | "implied";

export type Tier = Readonly<{
  id: string;
  name: string;
  monthly: number;
  yearly: number;
  seats: string;
  minutes: string;
  featureIds: readonly string[];
  highlight: boolean;
  note: string;
}>;

export type IdeaColumn = "idea" | "try" | "keep" | "drop";

export type Idea = Readonly<{
  id: string;
  text: string;
  column: IdeaColumn;
  votes: number;
}>;

export type Offer = Readonly<{
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  stack: readonly StackItem[];
  value: Readonly<{
    dream: Driver;
    likelihood: Driver;
    time: Driver;
    effort: Driver;
  }>;
  obstacles: readonly Obstacle[];
  bonuses: readonly Bonus[];
  guarantee: Readonly<{ kind: GuaranteeKind; text: string }>;
  scarcity: string;
  urgency: string;
  naming: Readonly<{
    magnet: string;
    avatar: string;
    goal: string;
    interval: string;
    container: string;
    chosen: string;
  }>;
  positioning: Readonly<{
    forWho: string;
    need: string;
    category: string;
    benefit: string;
    unlike: string;
    because: string;
  }>;
  icp: Readonly<{
    who: string;
    size: string;
    buyer: string;
    pains: string;
    triggers: string;
    objections: string;
    where: string;
  }>;
  voice: Readonly<{
    tones: readonly string[];
    say: string;
    never: string;
    tagline: string;
    pitch: string;
  }>;
  tiers: readonly Tier[];
  ideas: readonly Idea[];
}>;

export type Studio = Readonly<{
  version: number;
  offers: readonly Offer[];
  activeId: string | null;
}>;

export const EMPTY_STUDIO: Studio = {
  version: STUDIO_VERSION,
  offers: [],
  activeId: null,
};

export const GUARANTEES: Record<
  GuaranteeKind,
  { label: string; hint: string }
> = {
  none: { label: "No guarantee", hint: "Say nothing about risk." },
  unconditional: {
    label: "Unconditional",
    hint: "Money back, no questions, within a window.",
  },
  conditional: {
    label: "Conditional",
    hint: "Money back or more help if they do the work and miss the result.",
  },
  anti: {
    label: "Anti-guarantee",
    hint: "All sales final, and say why (setup work, access given).",
  },
  implied: {
    label: "Implied (performance)",
    hint: "Paid on results: per call analysed, share of revenue, pay after.",
  },
};

export const TONES = [
  "Confident",
  "Plain-spoken",
  "Warm",
  "Direct",
  "Expert",
  "Playful",
  "Calm",
  "Bold",
  "Indian English",
  "Hinglish-friendly",
];

export const IDEA_COLUMNS: Record<IdeaColumn, string> = {
  idea: "Ideas",
  try: "Try next",
  keep: "Keep",
  drop: "Drop",
};

/** Hormozi-style prompts for the ideation board; {avatar} and {goal} come from the offer. */
export const IDEA_PROMPTS = [
  "What would make this a no-brainer for {avatar} this week?",
  "Which obstacle stops {avatar} from {goal}, and which feature removes it?",
  "What can we do for them so the result comes faster (time delay down)?",
  "What can we take off their plate so it feels effortless (effort down)?",
  "What proof would make {avatar} believe it works for them (likelihood up)?",
  "Which bonus costs us little but they would pay for on its own?",
  "What guarantee could we offer that we'd honour without fear?",
  "What real limit could make this scarce (seats, cohort, setup slots)?",
  "What deadline is honest: a cohort start, a season, a price change?",
  "Which feature could be its own front-end offer to start the relationship?",
  "How would we name this so {avatar} says 'that's for me'?",
  "What would we charge if it were ten times better, and what makes it so?",
];

let counter = 0;
export function newId(prefix: string): string {
  counter += 1;
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10);
  return `${prefix}-${random}${counter}`;
}

const driver = (score: number): Driver => ({ text: "", score });

export function blankOffer(
  name = "Untitled offer",
  now = new Date().toISOString(),
): Offer {
  return {
    id: newId("offer"),
    name,
    createdAt: now,
    updatedAt: now,
    stack: [],
    value: {
      dream: driver(5),
      likelihood: driver(5),
      time: driver(5),
      effort: driver(5),
    },
    obstacles: [],
    bonuses: [],
    guarantee: { kind: "none", text: "" },
    scarcity: "",
    urgency: "",
    naming: {
      magnet: "",
      avatar: "",
      goal: "",
      interval: "",
      container: "",
      chosen: "",
    },
    positioning: {
      forWho: "",
      need: "",
      category: "",
      benefit: "",
      unlike: "",
      because: "",
    },
    icp: {
      who: "",
      size: "",
      buyer: "",
      pains: "",
      triggers: "",
      objections: "",
      where: "",
    },
    voice: { tones: [], say: "", never: "", tagline: "", pitch: "" },
    tiers: [],
    ideas: [],
  };
}

/** Starting bundles: only feature picks, never claims or prices. */
export const TEMPLATES: readonly Readonly<{
  id: string;
  name: string;
  line: string;
  features: readonly string[];
}>[] = [
  { id: "blank", name: "Blank", line: "Start from nothing", features: [] },
  {
    id: "team-calls",
    name: "Sales X-Ray for teams",
    line: "Calls, Reports, coaching and insight for a sales team",
    features: [
      "dialler-recordings",
      "calls-library",
      "the-report",
      "brain-4",
      "prospect-profile",
      "my-coaching",
      "team-coaching",
      "team-insights",
      "organisations",
    ],
  },
  {
    id: "lead-engine",
    name: "Lead engine",
    line: "Ads to leads to calls to chats, in one CRM",
    features: [
      "meta-lead-ads",
      "google-ads",
      "leads-stage-tabs",
      "lead-pipelines",
      "start-calling",
      "after-call-sheet",
      "chats-inbox",
      "whatsapp",
      "sales-home",
    ],
  },
  {
    id: "solo-seller",
    name: "Solo seller on Android",
    line: "One seller's phone that dials, records and follows up",
    features: [
      "android-app",
      "start-calling",
      "dialler-recordings",
      "after-call-sheet",
      "ready-messages",
      "the-report",
      "my-coaching",
    ],
  },
  {
    id: "academy",
    name: "Academy and coaching",
    line: "Programs, practice and real-call review for learners",
    features: [
      "programs",
      "practice",
      "certificates",
      "academy-sales-xray",
      "coach-studio",
    ],
  },
];

export function fromTemplate(
  templateId: string,
  catalogue = CATALOGUE,
  now = new Date().toISOString(),
): Offer {
  const template = TEMPLATES.find((t) => t.id === templateId) ?? TEMPLATES[0]!;
  const known = new Set(catalogue.features.map((f) => f.id));
  return {
    ...blankOffer(
      templateId === "blank" ? "Untitled offer" : template.name,
      now,
    ),
    stack: template.features
      .filter((id) => known.has(id))
      .map((featureId) => ({ featureId, worth: 0, label: "" })),
  };
}

/** Value = (dream outcome × perceived likelihood) ÷ (time delay × effort and sacrifice). */
export function valueScore(value: Offer["value"]): number {
  const clamp = (n: number) => Math.min(10, Math.max(1, Math.round(n) || 1));
  return (
    (clamp(value.dream.score) * clamp(value.likelihood.score)) /
    (clamp(value.time.score) * clamp(value.effort.score))
  );
}

export function valueVerdict(score: number): {
  label: string;
  tone: "good" | "accent" | "warn" | "bad";
} {
  if (score >= 6) return { label: "Grand slam", tone: "good" };
  if (score >= 2) return { label: "Strong", tone: "accent" };
  if (score >= 1) return { label: "Fair", tone: "warn" };
  return { label: "Weak", tone: "bad" };
}

/** Where 0..1 a score sits on a log scale from 1/100 to 100. */
export function valuePosition(score: number): number {
  const log = Math.log10(Math.max(0.01, Math.min(100, score)));
  return (log + 2) / 4;
}

export function featureById(
  id: string,
  catalogue = CATALOGUE,
): Feature | undefined {
  return catalogue.features.find((f) => f.id === id);
}

export function itemLabel(item: StackItem, catalogue = CATALOGUE): string {
  return (
    item.label.trim() ||
    featureById(item.featureId, catalogue)?.name ||
    item.featureId
  );
}

/** The value stack's total: every item's worth plus every bonus's worth. */
export function stackTotal(
  offer: Offer,
  featureIds?: readonly string[],
): number {
  const included = featureIds ? new Set(featureIds) : null;
  const items = offer.stack
    .filter((item) => !included || included.has(item.featureId))
    .reduce((sum, item) => sum + (item.worth || 0), 0);
  return items + offer.bonuses.reduce((sum, b) => sum + (b.worth || 0), 0);
}

/** How many times the stack's worth a tier's yearly price (or 12 × monthly) is; null without a price. */
export function valueMultiple(offer: Offer, tier: Tier): number | null {
  const yearly = tier.yearly || tier.monthly * 12;
  if (!yearly) return null;
  return stackTotal(offer, tier.featureIds) / yearly;
}

export function rupees(amount: number): string {
  if (!amount) return "—";
  return `₹${Math.round(amount).toLocaleString("en-IN")}`;
}

/** The MAGIC name, from its parts, when no name was chosen. */
export function suggestedName(naming: Offer["naming"]): string {
  return [
    naming.magnet,
    naming.avatar,
    naming.goal,
    naming.interval,
    naming.container,
  ]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" ");
}

export function positioningStatement(
  p: Offer["positioning"],
  name: string,
): string {
  if (!p.forWho && !p.benefit) return "";
  const first = [
    `For ${p.forWho || "…"}`,
    p.need ? ` who ${p.need}` : "",
    `, ${name} is ${p.category ? `a ${p.category}` : "the answer"}`,
    p.benefit ? ` that ${p.benefit}` : "",
    ".",
  ].join("");
  const second = p.unlike
    ? ` Unlike ${p.unlike}${p.because ? `, it ${p.because}` : ""}.`
    : "";
  return first + second;
}

export function fillPrompt(prompt: string, offer: Offer): string {
  const avatar =
    offer.naming.avatar.trim() || offer.icp.who.trim() || "the buyer";
  const goal = offer.naming.goal.trim() || "getting the result";
  return prompt.replaceAll("{avatar}", avatar).replaceAll("{goal}", goal);
}

/* ---------- Import and export ---------- */

const str = (value: unknown, max = 2000): string =>
  typeof value === "string" ? value.slice(0, max) : "";
const num = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.min(value, 1e10)
    : 0;
const obj = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

function readDriver(value: unknown): Driver {
  const d = obj(value);
  const score = num(d.score);
  return { text: str(d.text), score: score >= 1 && score <= 10 ? score : 5 };
}

/** Rebuilds an offer from untrusted JSON: unknown keys dropped, every field typed and bounded. */
export function normalizeOffer(
  value: unknown,
  now = new Date().toISOString(),
): Offer {
  const o = obj(value);
  const base = blankOffer(str(o.name, 200) || "Untitled offer", now);
  const v = obj(o.value);
  const naming = obj(o.naming);
  const positioning = obj(o.positioning);
  const icp = obj(o.icp);
  const voice = obj(o.voice);
  const guarantee = obj(o.guarantee);
  const kind = str(guarantee.kind) as GuaranteeKind;
  const pick = <K extends string>(
    source: Record<string, unknown>,
    keys: readonly K[],
  ) =>
    Object.fromEntries(keys.map((k) => [k, str(source[k])])) as Record<
      K,
      string
    >;
  const column = (c: unknown): IdeaColumn =>
    c === "try" || c === "keep" || c === "drop" ? c : "idea";
  return {
    ...base,
    id: str(o.id, 80) || base.id,
    createdAt: str(o.createdAt, 40) || now,
    updatedAt: str(o.updatedAt, 40) || now,
    stack: arr(o.stack)
      .map(obj)
      .filter((s) => str(s.featureId))
      .slice(0, 200)
      .map((s) => ({
        featureId: str(s.featureId, 80),
        worth: num(s.worth),
        label: str(s.label, 200),
      })),
    value: {
      dream: readDriver(v.dream),
      likelihood: readDriver(v.likelihood),
      time: readDriver(v.time),
      effort: readDriver(v.effort),
    },
    obstacles: arr(o.obstacles)
      .map(obj)
      .slice(0, 200)
      .map((x) => ({
        id: str(x.id, 80) || newId("obstacle"),
        problem: str(x.problem),
        solution: str(x.solution),
        featureId: str(x.featureId, 80),
      })),
    bonuses: arr(o.bonuses)
      .map(obj)
      .slice(0, 100)
      .map((b) => ({
        id: str(b.id, 80) || newId("bonus"),
        name: str(b.name, 200),
        worth: num(b.worth),
        solves: str(b.solves),
      })),
    guarantee: {
      kind: kind in GUARANTEES ? kind : "none",
      text: str(guarantee.text),
    },
    scarcity: str(o.scarcity),
    urgency: str(o.urgency),
    naming: pick(naming, [
      "magnet",
      "avatar",
      "goal",
      "interval",
      "container",
      "chosen",
    ]),
    positioning: pick(positioning, [
      "forWho",
      "need",
      "category",
      "benefit",
      "unlike",
      "because",
    ]),
    icp: pick(icp, [
      "who",
      "size",
      "buyer",
      "pains",
      "triggers",
      "objections",
      "where",
    ]),
    voice: {
      tones: arr(voice.tones)
        .map((t) => str(t, 40))
        .filter(Boolean)
        .slice(0, 12),
      say: str(voice.say),
      never: str(voice.never),
      tagline: str(voice.tagline, 300),
      pitch: str(voice.pitch),
    },
    tiers: arr(o.tiers)
      .map(obj)
      .slice(0, 12)
      .map((t) => ({
        id: str(t.id, 80) || newId("tier"),
        name: str(t.name, 120),
        monthly: num(t.monthly),
        yearly: num(t.yearly),
        seats: str(t.seats, 80),
        minutes: str(t.minutes, 80),
        featureIds: arr(t.featureIds)
          .map((f) => str(f, 80))
          .filter(Boolean)
          .slice(0, 200),
        highlight: t.highlight === true,
        note: str(t.note, 500),
      })),
    ideas: arr(o.ideas)
      .map(obj)
      .filter((i) => str(i.text))
      .slice(0, 500)
      .map((i) => ({
        id: str(i.id, 80) || newId("idea"),
        text: str(i.text, 1000),
        column: column(i.column),
        votes: Math.min(99, Math.floor(num(i.votes))),
      })),
  };
}

/** A studio from untrusted JSON (a file, an old browser copy); throws on something that isn't one. */
export function normalizeStudio(value: unknown): Studio {
  const s = obj(value);
  const offers = Array.isArray(s.offers)
    ? s.offers
    : s.stack || s.value
      ? [s] // a single exported offer
      : null;
  if (!offers) throw new Error("This file has no offers in it.");
  const seen = new Set<string>();
  const normalized = offers.slice(0, 200).map((o) => {
    let offer = normalizeOffer(o);
    if (seen.has(offer.id)) offer = { ...offer, id: newId("offer") };
    seen.add(offer.id);
    return offer;
  });
  const activeId = str(s.activeId, 80);
  return {
    version: STUDIO_VERSION,
    offers: normalized,
    activeId: normalized.some((o) => o.id === activeId)
      ? activeId
      : (normalized[0]?.id ?? null),
  };
}

/** Imported offers join the studio; one with an id already here comes in as a copy. */
export function mergeStudios(current: Studio, incoming: Studio): Studio {
  const ids = new Set(current.offers.map((o) => o.id));
  const added = incoming.offers.map((o) =>
    ids.has(o.id)
      ? { ...o, id: newId("offer"), name: `${o.name} (imported)` }
      : o,
  );
  return {
    version: STUDIO_VERSION,
    offers: [...current.offers, ...added],
    activeId: added[0]?.id ?? current.activeId,
  };
}

/* ---------- One-pager ---------- */

export function onePagerMarkdown(
  offer: Offer,
  { prices }: { prices: boolean },
  catalogue = CATALOGUE,
): string {
  const lines: string[] = [];
  const name = offer.naming.chosen.trim() || offer.name;
  lines.push(`# ${name}`);
  if (offer.voice.tagline) lines.push("", `_${offer.voice.tagline}_`);
  const statement = positioningStatement(offer.positioning, name);
  if (statement) lines.push("", statement);
  if (offer.value.dream.text)
    lines.push("", `**The result:** ${offer.value.dream.text}`);
  if (offer.icp.who) lines.push("", `**Made for:** ${offer.icp.who}`);
  if (offer.stack.length) {
    lines.push("", "## What you get");
    for (const item of offer.stack) {
      const feature = featureById(item.featureId, catalogue);
      const worth =
        prices && item.worth ? ` (worth ${rupees(item.worth)})` : "";
      lines.push(
        `- **${itemLabel(item, catalogue)}**${worth}: ${feature?.value ?? ""}`,
      );
    }
  }
  if (offer.bonuses.length) {
    lines.push("", "## Bonuses");
    for (const bonus of offer.bonuses) {
      const worth =
        prices && bonus.worth ? ` (worth ${rupees(bonus.worth)})` : "";
      lines.push(
        `- **${bonus.name}**${worth}${bonus.solves ? `: ${bonus.solves}` : ""}`,
      );
    }
  }
  if (prices && stackTotal(offer))
    lines.push("", `**Total value:** ${rupees(stackTotal(offer))}`);
  if (offer.guarantee.kind !== "none" || offer.guarantee.text)
    lines.push(
      "",
      `## Our guarantee`,
      "",
      offer.guarantee.text || GUARANTEES[offer.guarantee.kind].label,
    );
  if (prices && offer.tiers.length) {
    lines.push("", "## Plans", "");
    for (const tier of offer.tiers) {
      const price = [
        tier.monthly ? `${rupees(tier.monthly)}/month` : "",
        tier.yearly ? `${rupees(tier.yearly)}/year` : "",
      ]
        .filter(Boolean)
        .join(" or ");
      const extras = [
        tier.seats && `${tier.seats} seats`,
        tier.minutes && `${tier.minutes} minutes`,
      ]
        .filter(Boolean)
        .join(", ");
      lines.push(
        `- **${tier.name || "Plan"}**${tier.highlight ? " (most popular)" : ""}: ${price || "price on request"}${extras ? `; ${extras}` : ""}`,
      );
    }
  }
  if (offer.scarcity || offer.urgency) {
    lines.push("");
    if (offer.scarcity) lines.push(`**Limited:** ${offer.scarcity}`);
    if (offer.urgency) lines.push(`**Why now:** ${offer.urgency}`);
  }
  return `${lines.join("\n")}\n`;
}
