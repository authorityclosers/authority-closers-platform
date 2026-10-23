/**
 * Bug reports from Sales X-Ray testers (owner, 23 Oct 2026): the list's
 * filters (kept in the address), labels and normalizers for
 * GET /v1/admin/bugs and GET /v1/admin/bugs/{id}. Pure.
 */
import { read } from "../lib/read";

export const STATUSES = [
  "new",
  "triaged",
  "in_progress",
  "fixed",
  "verified",
  "closed",
] as const;
export type Status = (typeof STATUSES)[number];
export const SEVERITIES = ["blocker", "high", "medium", "low"] as const;
export type Severity = (typeof SEVERITIES)[number];
export const AREAS = [
  "home",
  "leads",
  "calls",
  "report",
  "chats",
  "coaching",
  "settings",
  "sign_in",
  "other",
] as const;
export type Area = (typeof AREAS)[number];

export const STATUS_LABEL: Record<Status, string> = {
  new: "New",
  triaged: "Triaged",
  in_progress: "In progress",
  fixed: "Fixed",
  verified: "Verified",
  closed: "Closed",
};
export const SEVERITY_LABEL: Record<Severity, string> = {
  blocker: "Blocker",
  high: "High",
  medium: "Medium",
  low: "Low",
};
export const AREA_LABEL: Record<Area, string> = {
  home: "Home",
  leads: "Leads",
  calls: "Calls",
  report: "Report",
  chats: "Chats",
  coaching: "Coaching",
  settings: "Settings",
  sign_in: "Sign-in",
  other: "Other",
};

type Tone = "neutral" | "accent" | "info" | "good" | "warn" | "bad";
export const STATUS_TONE: Record<Status, Tone> = {
  new: "info",
  triaged: "accent",
  in_progress: "warn",
  fixed: "good",
  verified: "good",
  closed: "neutral",
};
export const SEVERITY_TONE: Record<Severity, Tone> = {
  blocker: "bad",
  high: "warn",
  medium: "info",
  low: "neutral",
};

export const BOARD_URL = "https://paperclip.authorityclosers.com/AUT/issues/";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CARD = /^[A-Z]{2,8}-\d{1,7}$/;

const isStatus = (value: unknown): value is Status =>
  STATUSES.includes(value as Status);
const isSeverity = (value: unknown): value is Severity =>
  SEVERITIES.includes(value as Severity);
const isArea = (value: unknown): value is Area => AREAS.includes(value as Area);

/** The list's view: open bugs by default, then each status, then all. */
export type View = "open" | Status | "all";
export type BugFilters = {
  view: View;
  severity?: Severity | "none";
  area?: Area;
  organisation?: string;
  offset?: number;
};

type Params = Record<string, string | string[] | undefined>;
const one = (value: string | string[] | undefined) =>
  Array.isArray(value) ? value[0] : value;

export function bugFilters(params: Params): BugFilters {
  const status = one(params.status);
  const filters: BugFilters = {
    view: status === "all" || isStatus(status) ? status : "open",
  };
  const severity = one(params.severity);
  if (severity === "none" || isSeverity(severity)) filters.severity = severity;
  const area = one(params.area);
  if (isArea(area)) filters.area = area;
  const organisation = one(params.organisation);
  if (organisation && UUID.test(organisation))
    filters.organisation = organisation.toLowerCase();
  const offset = Number(one(params.offset));
  if (Number.isInteger(offset) && offset > 0 && offset <= 100_000)
    filters.offset = offset;
  return filters;
}

/** The address query for a view, in a stable order; `omit` drops keys. */
export function bugQuery(
  filters: BugFilters,
  omit: (keyof BugFilters)[] = [],
): string {
  const query = new URLSearchParams();
  if (filters.view !== "open" && !omit.includes("view"))
    query.set("status", filters.view);
  for (const key of ["severity", "area", "organisation", "offset"] as const) {
    const value = filters[key];
    if (value !== undefined && !omit.includes(key))
      query.set(key, String(value));
  }
  return query.toString();
}

export function bugsApiPath(filters: BugFilters): string {
  const query = new URLSearchParams();
  if (filters.view !== "all") query.set("status", filters.view);
  for (const key of ["severity", "area", "organisation", "offset"] as const) {
    const value = filters[key];
    if (value !== undefined) query.set(key, String(value));
  }
  const text = query.toString();
  return `/v1/admin/bugs${text ? `?${text}` : ""}`;
}

export type BugSummary = {
  id: string;
  number: number;
  createdAt: string | null;
  words: string;
  blocksWork: boolean;
  status: Status;
  severity: Severity | null;
  area: Area;
  route: string;
  boardCard: string | null;
  organisation: { id: string; name: string } | null;
  person: { name: string | null; email: string | null };
  hasScreenshot: boolean;
  app: Record<string, string | number | boolean>;
  device: Record<string, string | number | boolean>;
  errorCount: number;
};

export type BugEvent = {
  id: string;
  kind: string;
  status: Status | null;
  severity: Severity | null;
  area: Area | null;
  note: string | null;
  boardCard: string | null;
  actor: "reporter" | "staff" | "board";
  actorName: string | null;
  createdAt: string | null;
};

export type ClientError = {
  kind: string;
  at: string | null;
  message: string | null;
  source: string | null;
  reference: string | null;
  status: number | null;
  method: string | null;
  path: string | null;
};

export type BugDetail = BugSummary & {
  server: Record<string, string | number | boolean>;
  workspaceRole: string | null;
  userAgent: string;
  screenshot: { source: string; bytes: number } | null;
  errors: ClientError[];
  history: BugEvent[];
};

export type BugPage = {
  items: BugSummary[];
  counts: Record<Status, number>;
  nextOffset: number | null;
  organisations: { id: string; name: string; count: number }[];
};

function flat(value: unknown): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  for (const [key, item] of Object.entries(read.object(value))) {
    if (
      typeof item === "string" ||
      typeof item === "boolean" ||
      (typeof item === "number" && Number.isFinite(item))
    )
      out[key] = item;
  }
  return out;
}

export function normalizeSummary(raw: unknown): BugSummary {
  const row = read.object(raw);
  const organisation = read.object(row.organisation);
  const person = read.object(row.person);
  return {
    id: read.string(row.bug_id),
    number: read.number(row.number),
    createdAt: read.optionalString(row.created_at),
    words: read.string(row.words),
    blocksWork: read.boolean(row.blocks_work),
    status: isStatus(row.status) ? row.status : "new",
    severity: isSeverity(row.severity) ? row.severity : null,
    area: isArea(row.area) ? row.area : "other",
    route: read.string(row.route, "/"),
    boardCard:
      typeof row.board_card === "string" && CARD.test(row.board_card)
        ? row.board_card
        : null,
    organisation: read.optionalString(organisation.id)
      ? {
          id: read.string(organisation.id),
          name: read.string(organisation.name, "Workspace"),
        }
      : null,
    person: {
      name: read.optionalString(person.name),
      email: read.optionalString(person.email),
    },
    hasScreenshot: read.boolean(row.has_screenshot),
    app: flat(row.app),
    device: flat(row.device),
    errorCount: read.number(row.error_count),
  };
}

export function normalizePage(raw: unknown): BugPage {
  const body = read.object(raw);
  const counts = read.object(body.counts);
  return {
    items: read.array(body.items).map(normalizeSummary),
    counts: Object.fromEntries(
      STATUSES.map((status) => [status, read.number(counts[status])]),
    ) as Record<Status, number>,
    nextOffset: read.optionalNumber(body.next_offset),
    organisations: read.array(body.organisations).map((item) => {
      const row = read.object(item);
      return {
        id: read.string(row.id),
        name: read.string(row.name, "Workspace"),
        count: read.number(row.count),
      };
    }),
  };
}

export function normalizeDetail(raw: unknown): BugDetail {
  const body = read.object(raw);
  const context = read.object(body.context);
  const screenshot = read.object(body.screenshot);
  return {
    ...normalizeSummary(body),
    app: flat(context.app),
    device: flat(context.device),
    server: flat(context.server),
    workspaceRole: read.optionalString(read.object(context.workspace).role),
    userAgent: read.string(body.user_agent),
    screenshot: read.optionalString(screenshot.content_type)
      ? {
          source: read.string(screenshot.source),
          bytes: read.number(screenshot.bytes),
        }
      : null,
    errors: read.array(body.client_errors).map((item) => {
      const row = read.object(item);
      return {
        kind: read.string(row.kind, "error"),
        at: read.optionalString(row.at),
        message: read.optionalString(row.message),
        source: read.optionalString(row.source),
        reference: read.optionalString(row.reference),
        status: read.optionalNumber(row.status),
        method: read.optionalString(row.method),
        path: read.optionalString(row.path),
      };
    }),
    history: read.array(body.history).map((item) => {
      const row = read.object(item);
      const actor = row.actor;
      return {
        id: read.string(row.event_id),
        kind: read.string(row.kind),
        status: isStatus(row.status) ? row.status : null,
        severity: isSeverity(row.severity) ? row.severity : null,
        area: isArea(row.area) ? row.area : null,
        note: read.optionalString(row.note),
        boardCard:
          typeof row.board_card === "string" && CARD.test(row.board_card)
            ? row.board_card
            : null,
        actor: actor === "staff" || actor === "board" ? actor : "reporter",
        actorName:
          read.optionalString(row.actor_name) ??
          read.optionalString(row.actor_email),
        createdAt: read.optionalString(row.created_at),
      };
    }),
  };
}

/** One line for the history: what changed, in words. */
export function eventText(event: BugEvent): string {
  switch (event.kind) {
    case "status":
      return event.status ? `Status: ${STATUS_LABEL[event.status]}` : "Status";
    case "severity":
      return event.severity
        ? `Severity: ${SEVERITY_LABEL[event.severity]}`
        : "Severity";
    case "area":
      return event.area ? `Area: ${AREA_LABEL[event.area]}` : "Area";
    case "board":
      return `Work-board card ${event.boardCard ?? ""}`.trim();
    default:
      return event.note ?? "Note";
  }
}

/** "Android 14 · Chrome 141 · 390x844" */
export function deviceLine(device: BugSummary["device"]): string {
  return ["os", "browser", "model", "viewport"]
    .map((key) => device[key])
    .filter((value) => typeof value === "string" && value)
    .join(" · ");
}

/** "Android app 0.3.88 · web 1a2b3c4d5e6f" */
export function appLine(app: BugSummary["app"]): string {
  const parts: string[] = [];
  if (app.channel === "android") parts.push("Android app");
  else parts.push("Web");
  if (typeof app.native_version === "string") parts.push(app.native_version);
  if (typeof app.release === "string")
    parts.push(`web ${app.release.slice(0, 12)}`);
  return parts.join(" · ");
}
