/**
 * Settings -> Connected apps: each app's health and a real test of each, from
 * the Lead Desk back end (d8b2cfe6, contract in the shared notes:
 * lead-desk-connected-apps-contract-20261020.md). Owners and admins only; a
 * member's read is refused with 403.
 */

export type AppKey =
  | "meta_leads"
  | "whatsapp"
  | "messenger"
  | "instagram"
  | "google_ads"
  | "phone_calls"
  | "webhook_sources"
  | "ai_replies"
  | "lead_stages";
export type AppState =
  | "ready"
  | "problem"
  | "not_connected"
  | "not_set_up"
  | "off";
export type Link = { method: "GET" | "POST"; path: string };
export type Connection = {
  id: string;
  label: string;
  detail: string | null;
  state: AppState;
  words: string | null;
  disconnect: Link | null;
};
export type TestOffer = {
  kind: string;
  label: string;
  needs: string[];
  confirm: boolean;
};
/** Where the platform's own review of Sales Xray stands (Meta App Review). */
export type Review = {
  state: "pending" | "approved";
  /** The day it was sent, or approved (YYYY-MM-DD). */
  since: string;
  worksNow: string;
  after: string | null;
};
/** Why an app can't do its whole job yet, and the one fix (connected_apps.Blocker). */
export type Blocker = {
  /** The card's one quiet line. */
  short: string;
  reason: string;
  fix: string;
  /** A page in this app where the fix is done, and the link's words. */
  page: string | null;
  action: string | null;
};
export type AppHealth = {
  app: AppKey;
  name: string;
  state: AppState;
  words: string;
  configured: boolean;
  connect: Link | null;
  connections: Connection[];
  lastEvent: { at: string; words: string } | null;
  lastError: { at: string | null; words: string } | null;
  nextPullAt: string | null;
  lastDeliveryAt: string | null;
  /** A page in this app where the card's setup lives (lead stages). */
  page: string | null;
  tests: TestOffer[];
  /** Meta lead ads: the review of Sales Xray, and what works before it ends. */
  review: Review | null;
  blockers: Blocker[];
};
export type StepState = "done" | "waiting" | "failed" | "skipped";
export type TestResult = {
  testId: string | null;
  status: "waiting" | "passed" | "failed";
  words: string;
  steps: { label: string; state: StepState; words: string | null }[];
  /** AI replies' "Try it": the draft it wrote, when it wrote one. */
  draft?: string | null;
};
export type MetaForm = { id: string; name: string; status: string };
/** A Facebook Page shared with Sales Xray (lead_desk/connectors, /meta/status). */
export type MetaPage = {
  pageId: string;
  name: string;
  active: boolean;
  received: number;
  lastPulledAt: string | null;
  /** "all" takes every form on the Page, ones made later too. */
  forms: "all" | string[];
  formsCovered: MetaForm[];
  problem: { kind: string; text: string } | null;
};

export class AppsError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const KEYS = new Set<string>([
  "meta_leads",
  "whatsapp",
  "messenger",
  "instagram",
  "google_ads",
  "phone_calls",
  "webhook_sources",
  "ai_replies",
  "lead_stages",
]);
const STATES = new Set<string>([
  "ready",
  "problem",
  "not_connected",
  "not_set_up",
  "off",
]);
const STEPS = new Set<string>(["done", "waiting", "failed", "skipped"]);
const BASE = "/v1/lead-desk";

type Json = Record<string, unknown>;
const isRecord = (value: unknown): value is Json =>
  !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value : null;
const state = (value: unknown): AppState =>
  typeof value === "string" && STATES.has(value)
    ? (value as AppState)
    : "problem";

// A page of this app only: a path, never another site or a way up.
function ownPage(value: unknown): string | null {
  const path = text(value);
  return path &&
    path.startsWith("/") &&
    !path.startsWith("//") &&
    !path.includes("..")
    ? path
    : null;
}

// Only the back end's own routes are followed: same origin, under /v1/lead-desk.
function link(value: unknown): Link | null {
  if (!isRecord(value)) return null;
  const path = text(value.path);
  if (!path || !path.startsWith(`${BASE}/`) || path.includes("..")) return null;
  return { method: value.method === "POST" ? "POST" : "GET", path };
}

function parseApp(value: unknown): AppHealth | null {
  if (!isRecord(value) || typeof value.app !== "string" || !KEYS.has(value.app))
    return null;
  const event = isRecord(value.lastEvent) ? value.lastEvent : null;
  const error = isRecord(value.lastError) ? value.lastError : null;
  const review = isRecord(value.review) ? value.review : null;
  return {
    app: value.app as AppKey,
    name: text(value.name) ?? value.app,
    state: state(value.state),
    words: text(value.words) ?? "",
    configured: value.configured !== false,
    connect: link(value.connect),
    connections: (Array.isArray(value.connections) ? value.connections : [])
      .filter(isRecord)
      .map((item) => ({
        id: String(item.id ?? ""),
        label: text(item.label) ?? "Connection",
        detail: text(item.detail),
        state: state(item.state ?? "ready"),
        words: text(item.words),
        disconnect: link(item.disconnect),
      })),
    lastEvent:
      event && text(event.at) && text(event.words)
        ? { at: event.at as string, words: event.words as string }
        : null,
    lastError:
      error && text(error.words)
        ? { at: text(error.at), words: error.words as string }
        : null,
    nextPullAt: text(value.nextPullAt),
    lastDeliveryAt: isRecord(value.webhook)
      ? text(value.webhook.lastDeliveryAt)
      : null,
    page: ownPage(value.page),
    tests: (Array.isArray(value.tests) ? value.tests : [])
      .filter(isRecord)
      .filter((item) => text(item.kind) && text(item.label))
      .map((item) => ({
        kind: item.kind as string,
        label: item.label as string,
        needs: Array.isArray(item.needs)
          ? item.needs.filter(
              (need): need is string => typeof need === "string",
            )
          : [],
        confirm: item.confirm === true,
      })),
    review:
      review && text(review.since) && text(review.worksNow)
        ? {
            state: review.state === "approved" ? "approved" : "pending",
            since: review.since as string,
            worksNow: review.worksNow as string,
            after: text(review.after),
          }
        : null,
    blockers: (Array.isArray(value.blockers) ? value.blockers : [])
      .filter(isRecord)
      .filter((item) => text(item.short) && text(item.reason) && text(item.fix))
      .map((item) => {
        const page = ownPage(item.page);
        const action = text(item.action);
        return {
          short: item.short as string,
          reason: item.reason as string,
          fix: item.fix as string,
          page: page && action ? page : null,
          action: page && action ? action : null,
        };
      }),
  };
}

export function parseHealth(
  value: unknown,
): { checkedAt: string | null; apps: AppHealth[] } | null {
  if (!isRecord(value) || !Array.isArray(value.apps)) return null;
  return {
    checkedAt: text(value.checkedAt),
    apps: value.apps
      .map(parseApp)
      .filter((app): app is AppHealth => app !== null),
  };
}

export function parseTest(value: unknown): TestResult | null {
  if (!isRecord(value)) return null;
  const status =
    value.status === "passed" || value.status === "failed"
      ? value.status
      : "waiting";
  return {
    testId: text(value.testId),
    status,
    words: text(value.words) ?? "",
    steps: (Array.isArray(value.steps) ? value.steps : [])
      .filter(isRecord)
      .filter((step) => text(step.label))
      .map((step) => ({
        label: step.label as string,
        state:
          typeof step.state === "string" && STEPS.has(step.state)
            ? (step.state as StepState)
            : "waiting",
        words: text(step.words),
      })),
  };
}

/** AI replies' "Try it" answer, in the shape every other test uses. */
export function parseTry(
  value: unknown,
): (TestResult & { replyId: string | null }) | null {
  if (!isRecord(value)) return null;
  const status = value.status;
  const draft = text(value.draft);
  return {
    testId: null,
    replyId: text(value.replyId),
    status:
      status === "queued"
        ? "waiting"
        : status === "drafted" || status === "handoff"
          ? "passed"
          : "failed",
    words: text(value.words) ?? "",
    steps: [],
    draft,
  };
}

async function send(
  path: string,
  init: RequestInit & { signal?: AbortSignal } = {},
) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
    },
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok)
    throw new AppsError(
      response.status,
      isRecord(body) && typeof body.detail === "string"
        ? body.detail
        : "Something went wrong. Try again in a moment.",
    );
  return body;
}

export async function readHealth(signal?: AbortSignal) {
  const parsed = parseHealth(
    await send(`${BASE}/integrations/health`, { signal }),
  );
  if (!parsed) throw new AppsError(502, "The answer could not be read.");
  return parsed;
}

export async function startTest(app: AppKey, body: Record<string, unknown>) {
  if (app === "ai_replies") return startTry(String(body.message ?? ""));
  const parsed = parseTest(
    await send(`${BASE}/integrations/${app}/test`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  );
  if (!parsed) throw new AppsError(502, "The answer could not be read.");
  return parsed;
}

export async function readTest(testId: string, signal?: AbortSignal) {
  const parsed = parseTest(
    await send(`${BASE}/integrations/tests/${encodeURIComponent(testId)}`, {
      signal,
    }),
  );
  if (!parsed) throw new AppsError(502, "The answer could not be read.");
  return parsed;
}

async function startTry(message: string) {
  const parsed = parseTry(
    await send(`${BASE}/ai-replies/try`, {
      method: "POST",
      body: JSON.stringify({ message, channel: "whatsapp" }),
    }),
  );
  if (!parsed) throw new AppsError(502, "The answer could not be read.");
  // Polled like any other test, under its own id.
  return {
    ...parsed,
    testId:
      parsed.status === "waiting" && parsed.replyId
        ? `try:${parsed.replyId}`
        : null,
  };
}

/** A test still going: its newest state (AI replies' try included). */
export async function followTest(
  testId: string,
  signal?: AbortSignal,
): Promise<TestResult> {
  if (!testId.startsWith("try:")) return readTest(testId, signal);
  const replyId = testId.slice(4);
  const parsed = parseTry(
    await send(`${BASE}/ai-replies/try/${encodeURIComponent(replyId)}`, {
      signal,
    }),
  );
  if (!parsed) throw new AppsError(502, "The answer could not be read.");
  return { ...parsed, testId: parsed.status === "waiting" ? testId : null };
}

export async function readForms(
  pageId: string,
  signal?: AbortSignal,
): Promise<MetaForm[]> {
  const body = await send(
    `${BASE}/meta/pages/${encodeURIComponent(pageId)}/forms`,
    { signal },
  );
  return (Array.isArray(body) ? body : [])
    .map(parseForm)
    .filter((form): form is MetaForm => form !== null);
}

/** "5 min ago", "in 8 min", "just now"; null for no time. */
export function ago(value: string | null): string | null {
  if (!value) return null;
  const at = new Date(value).getTime();
  if (Number.isNaN(at)) return null;
  const seconds = Math.round((Date.now() - at) / 1000);
  const ahead = seconds < 0;
  const size = Math.abs(seconds);
  const words =
    size < 60
      ? "a moment"
      : size < 3600
        ? `${Math.round(size / 60)} min`
        : size < 86_400
          ? `${Math.round(size / 3600)} h`
          : `${Math.round(size / 86_400)} d`;
  if (size < 60) return ahead ? "in a moment" : "just now";
  return ahead ? `in ${words}` : `${words} ago`;
}

function parseForm(value: unknown): MetaForm | null {
  if (!isRecord(value) || !text(value.id) || !text(value.name)) return null;
  return {
    id: value.id as string,
    name: value.name as string,
    status: text(value.status) ?? "",
  };
}

function parsePage(value: unknown): MetaPage | null {
  if (!isRecord(value) || !text(value.pageId) || !text(value.name)) return null;
  const problem = isRecord(value.problem) ? value.problem : null;
  return {
    pageId: value.pageId as string,
    name: value.name as string,
    active: value.active === true,
    received: typeof value.received === "number" ? value.received : 0,
    lastPulledAt: text(value.lastPulledAt),
    forms: Array.isArray(value.forms)
      ? value.forms.filter((id): id is string => typeof id === "string")
      : "all",
    formsCovered: (Array.isArray(value.formsCovered) ? value.formsCovered : [])
      .map(parseForm)
      .filter((form): form is MetaForm => form !== null),
    problem:
      problem && text(problem.text)
        ? {
            kind: String(problem.kind ?? "other"),
            text: problem.text as string,
          }
        : null,
  };
}

/** The Facebook Pages shared with Sales Xray, on or off. */
export async function readMetaPages(signal?: AbortSignal): Promise<MetaPage[]> {
  const body = await send(`${BASE}/meta/status`, { signal });
  return (isRecord(body) && Array.isArray(body.pages) ? body.pages : [])
    .map(parsePage)
    .filter((page): page is MetaPage => page !== null);
}

/** Turn a Page on with the forms picked (or change them); the last week's leads come in now. */
export async function turnOnPage(
  pageId: string,
  forms: "all" | string[],
): Promise<number> {
  const body = await send(`${BASE}/meta/pages/${encodeURIComponent(pageId)}`, {
    method: "POST",
    body: JSON.stringify({ forms }),
  });
  return isRecord(body) && typeof body.imported === "number"
    ? body.imported
    : 0;
}

/** Ask Meta for a Page's new leads now; how many came in. */
export async function checkPage(pageId: string): Promise<number> {
  const body = await send(
    `${BASE}/meta/pages/${encodeURIComponent(pageId)}/pull`,
    { method: "POST" },
  );
  if (!isRecord(body)) return 0;
  const count = (value: unknown) => (typeof value === "number" ? value : 0);
  return count(body.created) + count(body.repeat);
}

export async function disconnect(target: Link) {
  await send(target.path, { method: "POST", body: JSON.stringify({}) });
}
