/**
 * Lead stages API client: /v1/lead-desk/journey (owner, 20 Oct: "every business
 * tracks leads its own way"). A business's own stages, industry profiles, and
 * what each ad platform hears when a lead reaches a stage.
 */

import { LeadsError } from "../leads-client";

export type Kind =
  | "new"
  | "not_connected"
  | "follow_up"
  | "interested"
  | "won"
  | "lost";

export type StageView = {
  key: string;
  label: string;
  kind: Kind;
  kindWords: string;
  milestone: string;
  meaning: string;
  archived: boolean;
  origin: string;
  leads: number;
};

export type JourneyView = {
  version: number;
  industry: string | null;
  savedAt: string | null;
  savedBy: string | null;
  stages: StageView[];
  canEdit: boolean;
  kinds: Record<string, string>;
  meanings: Record<string, string>;
  /** The pipeline these stages belong to ("main" until there are more). */
  pipeline?: string;
};

/** One of the organisation's pipelines (owner, 22 Oct 2026). */
export type PipelineView = {
  key: string;
  name: string;
  position: number;
  /** The first pipeline: it takes every lead the others don't. */
  main: boolean;
  /** The lead sources whose new leads come here (the main one lists none). */
  sources: string[];
  industry: string | null;
  leads: number;
};

export type PipelinesView = {
  pipelines: PipelineView[];
  /** Every lead source a pipeline can take, in the page's words. */
  sources: Record<string, string>;
  canEdit: boolean;
};

export const MAIN_PIPELINE = "main";

export type TemplateView = {
  id: string;
  name: string;
  blurb: string;
  icon: string;
  stages: { label: string; kind: Kind; milestone: string }[];
};

export type Guess = {
  milestone: string;
  meaning: string;
  kind: Kind;
  kindWords: string;
};

export type MatchView = {
  stageKey: string;
  stageLabel: string;
  kind: Kind;
  milestone: string;
  suggested: string | null;
  saved: string | null;
  state: "on" | "off" | "new";
  words: string | null;
};

export type AdEvent = {
  id: string;
  provider: string;
  leadId: string;
  leadName: string;
  stageLabel: string;
  eventName: string;
  status: "pending" | "delivered" | "rejected" | "dead_letter" | "dropped";
  attempts: number;
  eventTime: string;
  deliveredAt: string | null;
  error: string | null;
  test: boolean;
};

export type ProviderView = {
  id: string;
  name: string;
  brand: string;
  naming: "stage" | "action" | "standard";
  learns: string;
  reaches: string;
  destinationWords: string;
  /** Where the manager pastes the destination (no list from the platform). */
  manualDestination?: string | null;
  /** Where Connect starts for this platform. */
  connectPath?: string | null;
  available: boolean;
  configured: boolean;
  connected: boolean;
  destination: { id: string; name: string } | null;
  on: boolean;
  testCode: string | null;
  since: string | null;
  matches: MatchView[];
  /** A platform's own events, for platforms that don't take free names. */
  options?: { id: string; words: string }[];
  needsCheck: number;
  confirmedAt: string | null;
  counts: Record<string, number>;
  lastDeliveredAt: string | null;
  waitingOn: string | null;
};

export type AdsView = {
  version: number;
  providers: ProviderView[];
  recent: AdEvent[];
  settling: number;
  sendsAt: string | null;
};

/** A stage as the page edits it: new ones have no key until they are saved. */
export type Draft = {
  key?: string;
  label: string;
  kind?: Kind;
  milestone?: string;
  archived: boolean;
  /** The page's own id for the row (a saved stage's key, or a fresh one). */
  id: string;
  leads: number;
  kindWords?: string;
  meaning?: string;
  /** Where a stage came from when it was added from a connected app. */
  origin?: string;
  ref?: string;
};

export type Suggestion = {
  ref: string;
  label: string;
  source: string;
  workflow: string;
  milestone: string;
  meaning: string;
  kind: Kind;
  kindWords: string;
};

const API = "/v1/lead-desk";

export async function call<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no body */
    }
    throw new LeadsError(
      detail ?? "That didn't work. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

/** `?pipeline=` for every pipeline but the main one, whose address stays as it was. */
export const inPipeline = (pipeline?: string) =>
  pipeline && pipeline !== MAIN_PIPELINE
    ? `?pipeline=${encodeURIComponent(pipeline)}`
    : "";

/**
 * The pipelines answer as pages use it. A body without a pipelines list (an error
 * page, an older API, a fixture that doesn't answer) reads as none, so a screen shows
 * its usual state instead of breaking (Redmi QA, 23 Oct 2026: Lead stages crashed on
 * `pipelines.find`).
 */
export function pipelinesView(raw: unknown): PipelinesView {
  const view = (
    raw && typeof raw === "object" ? raw : {}
  ) as Partial<PipelinesView>;
  return {
    ...view,
    pipelines: Array.isArray(view.pipelines)
      ? view.pipelines
          .filter(
            (item): item is PipelineView =>
              !!item &&
              typeof item.key === "string" &&
              typeof item.name === "string",
          )
          .map((item) => ({
            ...item,
            sources: Array.isArray(item.sources) ? item.sources : [],
          }))
      : [],
    sources:
      view.sources && typeof view.sources === "object" ? view.sources : {},
    canEdit: view.canEdit === true,
  };
}

/** The ad platforms answer, its lists always lists (as pipelinesView). */
export function adsView(raw: unknown): AdsView {
  const view = (raw && typeof raw === "object" ? raw : {}) as Partial<AdsView>;
  return {
    ...view,
    version: typeof view.version === "number" ? view.version : 0,
    providers: Array.isArray(view.providers) ? view.providers : [],
    recent: Array.isArray(view.recent) ? view.recent : [],
    settling: typeof view.settling === "number" ? view.settling : 0,
    sendsAt: typeof view.sendsAt === "string" ? view.sendsAt : null,
  };
}

const callPipelines = (path: string, init?: RequestInit) =>
  call<unknown>(path, init).then(pipelinesView);
const callAds = (path: string, init?: RequestInit) =>
  call<unknown>(path, init).then(adsView);

export const readJourney = (pipeline?: string) =>
  call<JourneyView>(`/journey${inPipeline(pipeline)}`);
export const readTemplates = () => call<TemplateView[]>("/journey/templates");
export const readAds = () => callAds("/journey/ads");
export const readSuggestions = (pipeline?: string) =>
  call<Suggestion[]>(`/journey/suggestions${inPipeline(pipeline)}`);

export const readPipelines = () => callPipelines("/pipelines");

export const createPipeline = (pipeline: {
  name: string;
  template: string;
  sources: string[];
}) =>
  callPipelines("/pipelines", {
    method: "POST",
    body: JSON.stringify(pipeline),
  });

export const changePipeline = (
  key: string,
  change: { name?: string; sources?: string[] },
) =>
  callPipelines(`/pipelines/${encodeURIComponent(key)}`, {
    method: "PATCH",
    body: JSON.stringify(change),
  });

export const saveJourney = (
  expectedVersion: number,
  drafts: Draft[],
  pipeline?: string,
) =>
  call<JourneyView>(`/journey${inPipeline(pipeline)}`, {
    method: "PUT",
    body: JSON.stringify({
      expectedVersion,
      stages: drafts.map((draft) => ({
        ...(draft.key ? { key: draft.key } : {}),
        label: draft.label.trim(),
        ...(draft.kind ? { kind: draft.kind } : {}),
        ...(draft.milestone ? { milestone: draft.milestone } : {}),
        archived: draft.archived,
        ...(!draft.key && draft.origin ? { origin: draft.origin } : {}),
        ...(!draft.key && draft.ref ? { ref: draft.ref } : {}),
      })),
    }),
  });

export const applyTemplate = (
  expectedVersion: number,
  template: string,
  pipeline?: string,
) =>
  call<JourneyView>(`/journey/template${inPipeline(pipeline)}`, {
    method: "POST",
    body: JSON.stringify({ expectedVersion, template }),
  });

export const guess = (label: string) =>
  call<Guess>("/journey/guess", {
    method: "POST",
    body: JSON.stringify({ label }),
  });

export const saveDestination = (
  provider: string,
  body: {
    destinationId: string;
    destinationName: string;
    on: boolean;
    testCode?: string | null;
  },
) =>
  callAds(`/journey/ads/${provider}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const confirmMatches = (
  provider: string,
  expectedVersion: number,
  events: Record<string, string | null>,
) =>
  callAds(`/journey/ads/${provider}/matches`, {
    method: "PUT",
    body: JSON.stringify({ expectedVersion, events }),
  });

export type Quality = {
  score: number;
  events: number;
  keys: Record<string, number>;
};

/** Only a real score counts; anything else means "no quality to show". */
export function toQuality(found: unknown): Quality | null {
  if (!found || typeof found !== "object") return null;
  const { score, events, keys } = found as Partial<Quality>;
  if (typeof score !== "number" || !Number.isFinite(score)) return null;
  return {
    score,
    events: typeof events === "number" ? events : 0,
    keys: keys && typeof keys === "object" ? keys : {},
  };
}

export const readQuality = async (provider: string) =>
  toQuality(await call<unknown>(`/journey/ads/${provider}/quality`));

/** Meta's match quality in a line a business owner reads. */
export function qualityLine(provider: string, quality: Quality): string {
  const share = (key: string) => quality.keys[key];
  const parts = [`${provider} matches ${quality.score.toFixed(1)} out of 10`];
  const shown: [string, string][] = [
    ["email", "emails"],
    ["phone", "phone numbers"],
  ];
  for (const [key, words] of shown) {
    const value = share(key);
    if (value === undefined) continue;
    parts.push(
      value >= 95
        ? `${words} on every event`
        : value <= 0
          ? `no ${words} yet`
          : `${words} on ${value}% of events`,
    );
  }
  return parts.join(" · ");
}

export const retryEvent = (id: string) =>
  callAds(`/journey/ads/events/${encodeURIComponent(id)}/retry`, {
    method: "POST",
  });

/* ---------- pure helpers (tested) ---------- */

export const KIND_ORDER: Kind[] = [
  "new",
  "follow_up",
  "interested",
  "won",
  "lost",
  "not_connected",
];

/** The kinds a manager picks for a stage they add (New and Couldn't reach are one each). */
export const ADDABLE: Kind[] = ["follow_up", "interested", "won", "lost"];

export function drafts(view: JourneyView): Draft[] {
  return view.stages.map((stage) => ({
    key: stage.key,
    id: stage.key,
    label: stage.label,
    kind: stage.kind,
    milestone: stage.milestone,
    archived: stage.archived,
    leads: stage.leads,
    kindWords: stage.kindWords,
    meaning: stage.meaning,
  }));
}

/** The stages on the way to a sale, in order, then the two beside it. */
export function split(list: Draft[]) {
  const live = list.filter((item) => !item.archived);
  return {
    path: live.filter(
      (item) => item.kind !== "lost" && item.kind !== "not_connected",
    ),
    beside: live.filter(
      (item) => item.kind === "lost" || item.kind === "not_connected",
    ),
    archived: list.filter((item) => item.archived),
  };
}

/** Moves a stage one place up or down among the stages on the way to a sale.
 *  New stays first. */
export function move(list: Draft[], id: string, by: -1 | 1): Draft[] {
  const { path } = split(list);
  const at = path.findIndex((item) => item.id === id);
  const to = at + by;
  if (at < 0 || to < 1 || to >= path.length || path[at].kind === "new")
    return list;
  const order = path.map((item) => item.id);
  [order[at], order[to]] = [order[to], order[at]];
  return reorder(list, order);
}

/** Puts the stages on the way to a sale in this order; the rest keep theirs. */
export function reorder(list: Draft[], order: string[]): Draft[] {
  const { path } = split(list);
  const byId = new Map(path.map((item) => [item.id, item]));
  const ordered = order
    .map((id) => byId.get(id))
    .filter((item): item is Draft => !!item);
  if (ordered.length !== path.length || ordered[0]?.kind !== "new") return list;
  const rest = list.filter((item) => !byId.has(item.id));
  return [...ordered, ...rest];
}

/** Has anything changed since the saved list? */
export function changed(saved: JourneyView, list: Draft[]): boolean {
  const before = drafts(saved);
  if (before.length !== list.length) return true;
  return list.some((item, index) => {
    const old = before[index];
    return (
      old.id !== item.id ||
      old.label !== item.label.trim() ||
      old.kind !== item.kind ||
      old.milestone !== item.milestone ||
      old.archived !== item.archived
    );
  });
}

/** What the page says is wrong before saving, or null. */
export function problem(list: Draft[]): string | null {
  const live = list.filter((item) => !item.archived);
  if (live.some((item) => !item.label.trim())) return "Give each stage a name.";
  if (live.some((item) => item.label.trim().length > 40))
    return "Keep stage names to 40 letters or fewer.";
  const names = live.map((item) => item.label.trim().toLocaleLowerCase());
  if (new Set(names).size !== names.length)
    return "Two stages have the same name. Give each its own.";
  if (!live.some((item) => item.kind === "won"))
    return "Keep at least one Won stage, so you can see your sales.";
  if (!live.some((item) => item.kind === "lost"))
    return "Keep at least one Lost stage.";
  if (live.length > 16)
    return "Keep it to 16 stages or fewer. Fewer is easier for sellers.";
  return null;
}

let fresh = 0;
export const newId = () => `new-${Date.now().toString(36)}-${(fresh += 1)}`;

/** One line on what went to a platform lately. */
export function sentLine(provider: ProviderView, ads: AdsView): string {
  if (!provider.destination)
    return `No ${provider.destinationWords} chosen yet`;
  if (!provider.on) return `Switched off · ${provider.destination.name}`;
  const sent = provider.counts.delivered ?? 0;
  const parts = [
    `Sending to ${provider.destination.name}`,
    `${sent} stage${sent === 1 ? "" : "s"} sent this week`,
  ];
  const pending = provider.counts.pending ?? 0;
  if (pending > 0) parts.push(`${pending} waiting to send`);
  if (ads.settling > 0) {
    const minutes = ads.sendsAt
      ? Math.ceil((Date.parse(ads.sendsAt) - Date.now()) / 60_000)
      : 0;
    parts.push(
      `${ads.settling} going ${minutes > 1 ? `in about ${minutes} min` : "within a minute"}`,
    );
  }
  return parts.join(" · ");
}

export const STATUS_WORDS: Record<AdEvent["status"], string> = {
  pending: "Waiting",
  delivered: "Sent",
  rejected: "Refused",
  dead_letter: "Gave up",
  dropped: "Not sent",
};
