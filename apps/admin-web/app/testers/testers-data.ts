/**
 * Admin -> Testers (owner, 13 Nov 2026): the Sales X-Ray Play tester list.
 * GET /v1/admin/testers gives everyone with their stage; this file reads it
 * defensively (a missing field never crashes the page), names the stages and
 * filters the list by the tab the team picked.
 */
import type { Tone } from "@/app/ui/kit";

export const STAGES = [
  "applied",
  "approved",
  "in_group",
  "emailed",
  "installed",
  "active",
  "declined",
] as const;
export type Stage = (typeof STAGES)[number];

export const STAGE_LABEL: Record<Stage, string> = {
  applied: "Waiting for review",
  approved: "Approved",
  in_group: "In the group",
  emailed: "Emailed",
  installed: "Installed",
  active: "Active",
  declined: "Declined",
};

export const STAGE_TONE: Record<Stage, Tone> = {
  applied: "warn",
  approved: "info",
  in_group: "info",
  emailed: "accent",
  installed: "neutral",
  active: "good",
  declined: "bad",
};

export const ROLE_LABEL: Record<string, string> = {
  owner: "Business owner",
  manager: "Sales manager",
  seller: "Salesperson",
  other: "Other",
};

export type EmailStatus = "queued" | "sent" | "failed";

export type Tester = Readonly<{
  id: string;
  email: string;
  name: string | null;
  source: "applied" | "listed";
  stage: Stage;
  phoneModel: string | null;
  role: string | null;
  business: string | null;
  appliedAt: string | null;
  decision: "approved" | "declined" | null;
  inGroupAt: string | null;
  emailedAt: string | null;
  emailedVia: "app" | "gmail" | null;
  emailStatus: EmailStatus | null;
  hasAccount: boolean;
  appSessions: number;
  firstAppAt: string | null;
  lastAppAt: string | null;
  appVersion: string | null;
  webLastAt: string | null;
  bugs: number;
  note: string | null;
}>;

export type TesterPage = Readonly<{
  items: Tester[];
  counts: Record<Stage, number>;
  feedback: number;
  active: number;
  playNeeds: number;
  activeDays: number;
  groupEmail: string;
  groupUrl: string;
}>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const GROUP_URL =
  "https://groups.google.com/a/authorityclosers.com/g/salesxray-testers/members";

const record = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
const text = (value: unknown, max = 500): string | null =>
  typeof value === "string" && value.trim() ? value.trim().slice(0, max) : null;
const count = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.floor(value)
    : 0;
const isStage = (value: unknown): value is Stage =>
  typeof value === "string" && (STAGES as readonly string[]).includes(value);

export function normalizeTester(raw: unknown): Tester | null {
  const item = record(raw);
  const id = text(item.id, 36);
  const email = text(item.email, 320);
  if (!id || !UUID.test(id) || !email || !isStage(item.stage)) return null;
  const status = item.email_status;
  const via = item.emailed_via;
  return {
    id,
    email,
    name: text(item.name, 120),
    source: item.source === "listed" ? "listed" : "applied",
    stage: item.stage,
    phoneModel: text(item.phone_model, 80),
    role: text(item.role, 16),
    business: text(item.business, 120),
    appliedAt: text(item.applied_at, 40),
    decision:
      item.decision === "approved" || item.decision === "declined"
        ? item.decision
        : null,
    inGroupAt: text(item.in_group_at, 40),
    emailedAt: text(item.emailed_at, 40),
    emailedVia: via === "app" || via === "gmail" ? via : null,
    emailStatus:
      status === "queued" || status === "sent" || status === "failed"
        ? status
        : null,
    hasAccount: item.has_account === true,
    appSessions: count(item.app_sessions),
    firstAppAt: text(item.first_app_at, 40),
    lastAppAt: text(item.last_app_at, 40),
    appVersion: text(item.app_version, 24),
    webLastAt: text(item.web_last_at, 40),
    bugs: count(item.bugs),
    note: text(item.note, 500),
  };
}

export function normalizeTesters(raw: unknown): TesterPage {
  const body = record(raw);
  const counts = record(body.counts);
  const group = record(body.group);
  const url = text(group.members_url, 300);
  return {
    items: (Array.isArray(body.items) ? body.items : [])
      .map(normalizeTester)
      .filter((item): item is Tester => item !== null),
    counts: Object.fromEntries(
      STAGES.map((stage) => [stage, count(counts[stage])]),
    ) as Record<Stage, number>,
    feedback: count(body.feedback),
    active: count(body.active),
    playNeeds: count(body.play_needs) || 12,
    activeDays: count(body.active_days) || 7,
    groupEmail:
      text(group.email, 320) ?? "salesxray-testers@authorityclosers.com",
    // Only Google's own group page, never a link from the response elsewhere.
    groupUrl: url?.startsWith("https://groups.google.com/") ? url : GROUP_URL,
  };
}

/** The tabs: each stage, the people who reported bugs, and everyone. */
export const VIEWS = ["all", ...STAGES, "feedback"] as const;
export type View = (typeof VIEWS)[number];

export function testerView(value: string | string[] | undefined): View {
  const asked = Array.isArray(value) ? value[0] : value;
  return (VIEWS as readonly string[]).includes(asked ?? "")
    ? (asked as View)
    : "all";
}

export function inView(items: readonly Tester[], view: View): Tester[] {
  if (view === "all") return [...items];
  if (view === "feedback") return items.filter((item) => item.bugs > 0);
  return items.filter((item) => item.stage === view);
}

/** What the team does next for this tester, if anything. */
export type NextStep =
  | "review"
  | "add_to_group"
  | "send_email"
  | "send_again"
  | "reconsider"
  | null;

export function nextStep(tester: Tester): NextStep {
  switch (tester.stage) {
    case "applied":
      return "review";
    case "approved":
      return "add_to_group";
    case "in_group":
      return "send_email";
    case "emailed":
      return "send_again";
    case "declined":
      return "reconsider";
    default:
      return null;
  }
}

/** "Redmi 13 · Salesperson · Solar panels", from what they told us. */
export function aboutLine(tester: Tester): string {
  return [
    tester.phoneModel,
    tester.role ? (ROLE_LABEL[tester.role] ?? null) : null,
    tester.business,
  ]
    .filter(Boolean)
    .join(" · ");
}

export const EXPORT_PATH = "/v1/admin/testers/export.csv";
