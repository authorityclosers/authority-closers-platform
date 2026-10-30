/**
 * Economics (owner, 23 Oct 2026: an app that earns money according to how much we spend
 * from all points): GET /v1/admin/economics. What each plan earns after GST and the payment
 * fee, what its minutes cost on each analysis route, margins at 25%, 50% and 100% use,
 * break-even against the fixed costs, top-ups and the free trial. Pure.
 */
import { read } from "../lib/read";
import type { Tone } from "../ui/kit";

export type EconRoute = {
  id: string;
  label: string;
  source: string;
  perAudioMinute: number;
  perPlanMinute: number;
};

export type MarginCell = {
  use: number;
  cost: number;
  margin: number;
  share: number | null;
};

export type BreakEven = {
  contribution: number;
  running: number | null;
  total: number | null;
};

export type Offer = {
  id: string;
  plan: string;
  label: string;
  unit: string;
  channel: string;
  minutes: number;
  gross: number;
  exGst: number;
  fee: number;
  net: number;
  margins: Record<string, MarginCell[]>;
  breakEven: Record<string, BreakEven>;
  ceiling: number;
  netPerMinute: number;
  /** False for a plan priced but not on sale yet (coming soon), modelled all the same. */
  onSale: boolean;
};

export type TopUpRow = {
  plan: string;
  key: string;
  minutes: number;
  gross: number;
  net: number;
  netPerMinute: number;
  marginShare: Record<string, number | null>;
};

export type FixedItem = {
  key: string;
  label: string;
  rupees: number;
  kind: string;
  source: string;
};

/** One cost in the register, as the API reads it back with its month (owner, 30 Oct 2026). */
export type CostItem = {
  key: string;
  vendor: string;
  label: string;
  category: string;
  centre: string;
  cadence: string;
  rupees: number;
  currency: string;
  original: number | null;
  started: string | null;
  ended: string | null;
  lifeMonths: number | null;
  allocation: Record<string, unknown>;
  source: string;
  evidence: string;
  note: string;
  monthly: number;
  active: boolean;
  monthsLeft: number | null;
  basis: string;
  split: Record<string, number>;
};

export type ProductLine = {
  key: string;
  label: string;
  moneyIn: number;
  costs: number;
  profit: number;
  margin: number | null;
  breakEvenPersonal: number | null;
  breakEvenSeats: number | null;
};

/** AC's real month from the cost register: by category, cost centre and product. */
export type RealCosts = {
  month: string;
  total: number;
  byCategory: { key: string; label: string; rupees: number }[];
  byCentre: { key: string; label: string; rupees: number }[];
  items: CostItem[];
  products: ProductLine[];
  overall: {
    moneyIn: number;
    costs: number;
    profit: number;
    breakEvenPersonal: number | null;
    breakEvenSeats: number | null;
  };
  platformWork: string;
  keys: {
    generatedAt: string | null;
    windowDays: number | null;
    tools: Record<string, Record<string, number>>;
    cpu: Record<string, number> | null;
  };
  aiCalls: { customerMonth: number; testMonth: number };
};

export type Economics = {
  environment: string;
  days: number;
  /** The cost register's month; null until the first cost is entered. */
  costs: RealCosts | null;
  /** Live-mode recurring revenue a month, less GST and the payment fee. */
  moneyIn: { netMonth: number; payingAccounts: number } | null;
  routes: EconRoute[];
  offers: Offer[];
  topUps: TopUpRow[];
  fixed: {
    items: FixedItem[];
    running: number;
    building: number;
    total: number;
  };
  breakEvenRoute: string;
  targetMargin: number;
  priceFloor: number;
  trial: {
    minutes: number;
    cost: number | null;
    conversion: number;
    perPayingUser: number | null;
  };
  measured: {
    available: boolean;
    calls: number;
    audioMinutes: number;
    billedMinutes: number;
    rupees: number;
    uncharged: { calls: number; audioMinutes: number; month: number } | null;
  };
  warnings: { offer: string; route: string; kind: string }[];
  settingsRevision: number | null;
  /** The saved settings document (or the defaults), sent back whole when edited. */
  settingsConfig: Record<string, unknown> | null;
  problems: string[];
};

const cell = (raw: unknown): MarginCell => {
  const row = read.object(raw);
  return {
    use: read.number(row.use),
    cost: read.number(row.cost),
    margin: read.number(row.margin),
    share: read.optionalNumber(row.share),
  };
};

const recordOf = <T>(raw: unknown, map: (value: unknown) => T) =>
  Object.fromEntries(
    Object.entries(read.object(raw)).map(([key, value]) => [key, map(value)]),
  );

const configOf = (raw: unknown) =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : null;

const optionalString = (raw: unknown) =>
  typeof raw === "string" && raw ? raw : null;

const named = (raw: unknown) =>
  read.array(raw).map((item) => {
    const row = read.object(item);
    return {
      key: read.string(row.key),
      label: read.string(row.label, read.string(row.key)),
      rupees: read.number(row.rupees),
    };
  });

export function normalizeCosts(raw: unknown): RealCosts | null {
  const body = configOf(raw);
  if (!body) return null;
  const overall = read.object(body.overall);
  const keys = read.object(body.keys);
  const calls = read.object(body.ai_calls);
  const cpu = configOf(keys.cpu);
  return {
    month: read.string(body.month),
    total: read.number(body.total),
    byCategory: named(body.by_category),
    byCentre: named(body.by_centre),
    items: read.array(body.items).map((item) => {
      const row = read.object(item);
      return {
        key: read.string(row.key),
        vendor: read.string(row.vendor),
        label: read.string(row.label),
        category: read.string(row.category, "other"),
        centre: read.string(row.centre, "company"),
        cadence: read.string(row.cadence, "monthly"),
        rupees: read.number(row.rupees),
        currency: read.string(row.currency, "INR"),
        original: read.optionalNumber(row.original),
        started: optionalString(row.started),
        ended: optionalString(row.ended),
        lifeMonths: read.optionalNumber(row.life_months),
        allocation: configOf(row.allocation) ?? { rule: "direct" },
        source: read.string(row.source, "estimate"),
        evidence: read.string(row.evidence),
        note: read.string(row.note),
        monthly: read.number(row.monthly),
        active: read.boolean(row.active),
        monthsLeft: read.optionalNumber(row.months_left),
        basis: read.string(row.basis),
        split: recordOf(row.split, (value) => read.number(value)),
      };
    }),
    products: read.array(body.products).map((item) => {
      const row = read.object(item);
      return {
        key: read.string(row.key),
        label: read.string(row.label, read.string(row.key)),
        moneyIn: read.number(row.money_in),
        costs: read.number(row.costs),
        profit: read.number(row.profit),
        margin: read.optionalNumber(row.margin),
        breakEvenPersonal: read.optionalNumber(row.break_even_personal),
        breakEvenSeats: read.optionalNumber(row.break_even_seats),
      };
    }),
    overall: {
      moneyIn: read.number(overall.money_in),
      costs: read.number(overall.costs),
      profit: read.number(overall.profit),
      breakEvenPersonal: read.optionalNumber(overall.break_even_personal),
      breakEvenSeats: read.optionalNumber(overall.break_even_seats),
    },
    platformWork: read.string(body.platform_work, "pro_rata"),
    keys: {
      generatedAt: optionalString(keys.generated_at),
      windowDays: read.optionalNumber(keys.window_days),
      tools: recordOf(keys.tools, (value) =>
        recordOf(value, (share) => read.number(share)),
      ),
      cpu: cpu ? recordOf(cpu, (value) => read.number(value)) : null,
    },
    aiCalls: {
      customerMonth: read.number(calls.customer_month),
      testMonth: read.number(calls.test_month),
    },
  };
}

/** Words for the register's codes (costs.py). */
export const CATEGORY_WORDS: Record<string, string> = {
  servers: "Servers and cloud",
  ai_subscriptions: "AI subscriptions for the agents",
  ai_product: "AI for the product",
  ai_other: "Other AI APIs",
  tools: "Software and tools",
  workspace: "Workspace, email and domains",
  store_fees: "Store and platform fees",
  devices: "Devices and studio",
  marketing: "Marketing",
  people: "People (one monthly total)",
  professional: "Professional fees",
  financing: "Debt and interest (one total)",
  other: "Other",
};
export const CENTRE_WORDS: Record<string, string> = {
  sales_xray: "Sales X-Ray",
  company: "AC company-wide",
  agents: "Agents and AI tooling",
  people: "People",
};
export const PRODUCT_WORDS: Record<string, string> = {
  sales_xray: "Sales X-Ray",
  learner: "Learner app",
  other_companies: "Other companies",
  company: "AC company",
};
export const CADENCE_WORDS: Record<string, string> = {
  monthly: "Monthly",
  quarterly: "Quarterly",
  yearly: "Yearly",
  one_time: "One-time",
  usage: "Usage (a month)",
};
export const RULE_WORDS: Record<string, string> = {
  direct: "All to one product",
  token_burn: "By agent work",
  cpu_share: "By server time",
  revenue_share: "By money in",
  fixed: "Stated shares",
};

/** "Monthly", "Yearly ₹1,200", "One-time ₹24,000 over 24 months". */
export function cadenceLine(item: CostItem): string {
  const charged =
    item.currency !== "INR" && item.original !== null
      ? `${item.currency} ${item.original.toLocaleString("en-IN")} (${rupees(item.rupees)})`
      : rupees(item.rupees);
  if (item.cadence === "one_time")
    return `One-time ${charged} over ${item.lifeMonths ?? 24} months`;
  return `${CADENCE_WORDS[item.cadence] ?? item.cadence} ${charged}`;
}

export function normalizeEconomics(raw: unknown): Economics {
  const body = read.object(raw);
  const fixed = read.object(body.fixed);
  const trial = read.object(body.trial);
  const measured = read.object(body.measured);
  const uncharged =
    typeof measured.uncharged === "object" && measured.uncharged !== null
      ? read.object(measured.uncharged)
      : null;
  const moneyIn = configOf(body.money_in);
  return {
    environment: read.string(body.environment, "production"),
    days: read.number(body.days, 30),
    costs: normalizeCosts(body.costs),
    moneyIn: moneyIn
      ? {
          netMonth: read.number(moneyIn.net_month),
          payingAccounts: read.number(moneyIn.paying_accounts),
        }
      : null,
    routes: read.array(body.routes).map((item) => {
      const row = read.object(item);
      return {
        id: read.string(row.id),
        label: read.string(row.label, read.string(row.id)),
        source: read.string(row.source),
        perAudioMinute: read.number(row.per_audio_minute),
        perPlanMinute: read.number(row.per_plan_minute),
      };
    }),
    offers: read.array(body.offers).map((item) => {
      const row = read.object(item);
      return {
        id: read.string(row.id),
        plan: read.string(row.plan),
        label: read.string(row.label, read.string(row.id)),
        unit: read.string(row.unit, "plan"),
        channel: read.string(row.channel, "web"),
        minutes: read.number(row.minutes),
        gross: read.number(row.gross),
        exGst: read.number(row.ex_gst),
        fee: read.number(row.fee),
        net: read.number(row.net),
        margins: recordOf(row.margins, (value) => read.array(value).map(cell)),
        breakEven: recordOf(row.break_even, (value) => {
          const pair = read.object(value);
          return {
            contribution: read.number(pair.contribution),
            running: read.optionalNumber(pair.running),
            total: read.optionalNumber(pair.total),
          };
        }),
        ceiling: read.number(row.ceiling_per_plan_minute),
        netPerMinute: read.number(row.net_per_minute),
        onSale: row.on_sale !== false,
      };
    }),
    topUps: read.array(body.top_ups).map((item) => {
      const row = read.object(item);
      return {
        plan: read.string(row.plan),
        key: read.string(row.key),
        minutes: read.number(row.minutes),
        gross: read.number(row.gross),
        net: read.number(row.net),
        netPerMinute: read.number(row.net_per_minute),
        marginShare: recordOf(row.margin_share, (value) =>
          read.optionalNumber(value),
        ),
      };
    }),
    fixed: {
      items: read.array(fixed.items).map((item) => {
        const row = read.object(item);
        return {
          key: read.string(row.key),
          label: read.string(row.label, read.string(row.key)),
          rupees: read.number(row.rupees),
          kind: read.string(row.kind, "running"),
          source: read.string(row.source, "estimate"),
        };
      }),
      running: read.number(fixed.running),
      building: read.number(fixed.building),
      total: read.number(fixed.total),
    },
    breakEvenRoute: read.string(body.break_even_route),
    targetMargin: read.number(body.target_margin, 0.5),
    priceFloor: read.number(body.price_floor_per_minute, 0.71),
    trial: {
      minutes: read.number(trial.minutes),
      cost: read.optionalNumber(trial.cost),
      conversion: read.number(trial.conversion),
      perPayingUser: read.optionalNumber(trial.per_paying_user),
    },
    measured: {
      available: read.boolean(measured.available),
      calls: read.number(measured.calls),
      audioMinutes: read.number(measured.audio_minutes),
      billedMinutes: read.number(measured.billed_minutes),
      rupees: read.number(measured.rupees),
      uncharged: uncharged
        ? {
            calls: read.number(uncharged.calls),
            audioMinutes: read.number(uncharged.audio_minutes),
            month: read.number(uncharged.month),
          }
        : null,
    },
    warnings: read.array(body.warnings).map((item) => {
      const row = read.object(item);
      return {
        offer: read.string(row.offer),
        route: read.string(row.route),
        kind: read.string(row.kind),
      };
    }),
    settingsRevision: read.optionalNumber(read.object(body.settings).revision),
    settingsConfig: configOf(read.object(body.settings).config),
    problems: read
      .array(body.problems)
      .map((item) => read.string(read.object(item).problem))
      .filter(Boolean),
  };
}

const WHOLE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
const EXACT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** "₹1,376" for amounts, "₹0.85" for rates. */
export const rupees = (value: number | null) =>
  value === null ? "–" : WHOLE.format(Math.round(value));
export const rate = (value: number | null) =>
  value === null ? "–" : EXACT.format(value);
export const share = (value: number | null) =>
  value === null ? "–" : `${Math.round(value * 100)}%`;

/** Good at or above the target margin, warn below it, bad at a loss. */
export function marginTone(value: number | null, target: number): Tone {
  if (value === null) return "neutral";
  if (value < 0) return "bad";
  return value >= target ? "good" : "warn";
}

export const ENVIRONMENTS = [
  { key: "production", label: "Production" },
  { key: "staging", label: "Staging" },
  { key: "development", label: "Dev" },
] as const;

export const WINDOWS = [
  { key: "30", label: "30 days" },
  { key: "7", label: "7 days" },
  { key: "14", label: "14 days" },
] as const;

export function economicsQuery(env?: string, days?: string) {
  const environment =
    ENVIRONMENTS.find((item) => item.key === env)?.key ?? "production";
  const window = WINDOWS.find((item) => item.key === days)?.key ?? "30";
  return {
    environment,
    days: window,
    path: `/v1/admin/economics?env=${environment}&days=${window}`,
  };
}

/** Short names for table headings; the full label stays in the routes table. */
export const ROUTE_SHORT: Record<string, string> = {
  measured: "Measured",
  "today-brain4-read": "Today",
  "today-brain4-read-flex": "On Flex",
  "v2-flex-report-on-demand": "v2, Flex, report on demand",
  "v2-report-on-demand": "v2, report on demand",
  "v2-luna-flex-report-on-demand": "Luna, Flex",
};

export const routeName = (id: string) => ROUTE_SHORT[id] ?? id;

export const WARNING_WORDS: Record<string, string> = {
  loss_at_full_use: "loses money at full use",
  below_target_margin: "is below the target margin at full use",
  below_price_floor: "brings less than the price floor for each minute sold",
};
