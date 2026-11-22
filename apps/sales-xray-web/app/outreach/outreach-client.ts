/**
 * The outreach log (v1.95, owner 22 Nov 2026: "every message we send is
 * tracked, so we never feel spammy"): the message limits on Lead rules, the
 * outside senders, and the Outreach view, "what the owner sent". The server
 * is lead_desk/outreach.py; the API is lead-management-api.md §6.
 */

const BASE = "/v1/lead-desk/outreach";

export type TouchChannel =
  | "whatsapp"
  | "sms"
  | "email"
  | "call"
  | "messenger"
  | "instagram"
  | "in_person"
  | "other";

export type OutreachMode = "off" | "show" | "warn" | "block";

export type SendHours = { days: number[]; start: string; end: string };

export type OutreachRules = {
  revision: number;
  enabled: boolean;
  per_day: number;
  per_week: number;
  rest_after: number;
  rest_days: number;
  quiet: SendHours | null;
  hours_in_use: SendHours;
  modes: Record<string, { people: OutreachMode; automations: OutreachMode }>;
  keep_reply_words: boolean;
  never_lead: string[];
  can_edit: boolean;
};

/** What a save sends: the revision and only what changed. */
export type OutreachRulesChange = {
  expected_revision: number;
  enabled?: boolean;
  per_day?: number;
  per_week?: number;
  rest_after?: number;
  rest_days?: number;
  modes?: Record<string, { people: OutreachMode; automations: OutreachMode }>;
};

export type LeadDefaults = {
  create: boolean;
  side: "live" | "cold";
  tags: string[];
  assign: "rules" | "none";
};

export type SenderView = {
  sender_id: string;
  key: string;
  label: string;
  kind: "automation" | "person_tool";
  person_id: string | null;
  person_name: string | null;
  api_key_id: string | null;
  api_key_prefix: string | null;
  channels: TouchChannel[];
  lead_defaults: LeadDefaults;
  guard_mode: "report" | "hold";
  status: "active" | "paused";
  revision: number;
  last_seen_at: string | null;
  touches_week: number;
};

export type NewSender = {
  command_id: string;
  key: string;
  label: string;
  kind: "automation" | "person_tool";
  person_id?: string | null;
  api_key_id?: string | null;
  channels: TouchChannel[];
  guard_mode: "report" | "hold";
  lead_defaults?: LeadDefaults;
};

export type TouchView = {
  touch_id: string;
  lead_id: string;
  channel: TouchChannel;
  content_kind: string;
  initiated: "outreach" | "reply";
  sender_type: "person" | "automation";
  by_name: string;
  person_id: string | null;
  sender_id: string | null;
  sender_label: string | null;
  automation: string | null;
  via: string;
  provider: string | null;
  summary: string | null;
  template_name: string | null;
  attachment: { kind?: string; name?: string; bytes?: number } | null;
  status: string;
  status_at: string | null;
  sent_at: string;
  counted: boolean;
  verdict: "ok" | "warn" | "block";
  after_block: boolean;
  override_by_name: string | null;
  override_reason: string | null;
  replied_at: string | null;
  event_id: string | null;
  /** On the By message view only, when the server names the lead. */
  lead_name?: string | null;
};

export type OutreachLeadRow = {
  lead_id: string;
  name: string;
  added_by_person_id: string | null;
  added_by_name: string | null;
  added_at: string;
  touches: number;
  last_touch_at: string | null;
  replied: boolean;
  received: TouchView[];
};

export type OutreachPage = {
  filter: {
    view: "leads" | "touches";
    by: string | null;
    channel: string | null;
    date_from: string;
    date_to: string;
    replied: "any" | "replied" | "no_reply";
    over: boolean;
    locked_to_self: boolean;
  };
  hero: {
    touches: number;
    leads: number;
    replied: number;
    past_limit: number;
    leads_added: number | null;
    period: string;
    words: string;
    sentence: string;
  };
  leads: OutreachLeadRow[];
  touches: TouchView[];
  next_cursor: string | null;
};

export type OutreachQuery = {
  view?: "leads" | "touches";
  by?: string | null;
  channel?: string | null;
  from?: string | null;
  to?: string | null;
  replied?: "any" | "replied" | "no_reply";
  over?: boolean;
  cursor?: string | null;
  limit?: number;
};

export class OutreachError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "OutreachError";
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
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
      // No body: the status says enough.
    }
    throw new OutreachError(
      response.status === 409
        ? "Someone else saved these first. Your changes are still here: check them and save again."
        : response.status === 403
          ? (detail ?? "Your role can't see this.")
          : (detail ?? "That didn't go through. Try again."),
      response.status,
    );
  }
  return (await response.json()) as T;
}

export const readOutreachRules = (signal?: AbortSignal) =>
  call<OutreachRules>("/rules", { signal });

export const saveOutreachRules = (change: OutreachRulesChange) =>
  call<OutreachRules>("/rules", {
    method: "PUT",
    body: JSON.stringify(change),
  });

export const readSenders = (signal?: AbortSignal) =>
  call<{ senders: SenderView[] }>("/senders", { signal }).then(
    (body) => body.senders,
  );

export const createSender = (sender: NewSender) =>
  call<SenderView>("/senders", {
    method: "POST",
    body: JSON.stringify(sender),
  });

export const pauseSender = (sender: SenderView, paused: boolean) =>
  call<SenderView>(`/senders/${encodeURIComponent(sender.sender_id)}/pause`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: sender.revision, paused }),
  });

/** The query string for GET /outreach (and the page's own address). */
export function outreachSearch(query: OutreachQuery): URLSearchParams {
  const search = new URLSearchParams();
  if (query.view && query.view !== "leads") search.set("view", query.view);
  if (query.by) search.set("by", query.by);
  if (query.channel) search.set("channel", query.channel);
  if (query.from) search.set("from", query.from);
  if (query.to) search.set("to", query.to);
  if (query.replied && query.replied !== "any")
    search.set("replied", query.replied);
  if (query.over) search.set("over", "true");
  if (query.cursor) search.set("cursor", query.cursor);
  if (query.limit) search.set("limit", String(query.limit));
  return search;
}

export const readOutreach = (query: OutreachQuery, signal?: AbortSignal) => {
  const search = outreachSearch(query).toString();
  return call<OutreachPage>(search ? `?${search}` : "", { signal });
};
