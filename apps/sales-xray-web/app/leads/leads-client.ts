/**
 * Sales Xray CRM (code name Lead Desk) API client: /v1/lead-desk.
 *
 * Reads check the few fields the screens depend on and ignore any others, so
 * a new API field never breaks the page. Writes carry a command id so a retry
 * after a dropped connection never records the same thing twice.
 */

export const LEADS_PATH = "/leads";
const API = "/v1/lead-desk";

export type WhyKind =
  | "due"
  | "new"
  | "retry"
  | "later"
  | "open"
  | "closed"
  | "waiting";

export type LeadRow = {
  lead_id: string;
  revision: number;
  name: string;
  company: string | null;
  city: string | null;
  language: string | null;
  interest: string | null;
  phone_last4: string | null;
  stage: Stage;
  stage_label: string;
  source: string;
  source_label: string;
  owner_person_id: string | null;
  owner_name: string | null;
  why: string;
  why_kind: WhyKind;
  next_action_at: string | null;
  created_at: string;
  attempts: number;
  calls: number;
  last_result: string | null;
  last_result_label: string | null;
  test_data: boolean;
};

export type Stage =
  | "new"
  | "not_connected"
  | "follow_up"
  | "interested"
  | "won"
  | "lost";

export type Desk = {
  me: { person_id: string; name: string; role: string; can_manage: boolean };
  numbers: {
    calls: number;
    connected: number;
    talk_seconds: number;
    follow_ups_done: number;
    new_assigned: number;
  };
  counts: {
    open: number;
    new: number;
    follow_up_due: number;
    not_connected: number;
    later_today: number;
    unassigned: number | null;
  };
  queue: LeadRow[];
  call_mode: "simulated" | "phone";
  sandbox: boolean;
  generated_at: string;
};

export type LeadEvent = {
  kind:
    | "captured"
    | "repeat"
    | "assigned"
    | "reassigned"
    | "call"
    | "result"
    | "note"
    | "edited";
  at: string;
  actor_name: string | null;
  stage: string | null;
  stage_label: string | null;
  reason: string | null;
  reason_label: string | null;
  connected: boolean | null;
  note: string | null;
  next_action_at: string | null;
  owner_name: string | null;
  previous_owner_name: string | null;
  allocation_reason: string | null;
  source_label: string | null;
  submission_id: string | null;
  simulated: boolean | null;
  duration_seconds: number | null;
};

export type LeadDetail = {
  lead: LeadRow;
  phone: string | null;
  email: string | null;
  owner_reason: string | null;
  next_action_note: string | null;
  fields: { label: string; value: string }[];
  source_fields: { label: string; value: string }[];
  events: LeadEvent[];
  can_edit: boolean;
  can_assign: boolean;
  reps: {
    person_id: string;
    name: string;
    open_leads: number;
    available: boolean;
  }[];
  call_mode: "simulated" | "phone";
  first_call_minutes?: number | null;
};

export type LeadPage = {
  leads: LeadRow[];
  total: number;
  next_offset: number | null;
};

export type RepView = {
  person_id: string;
  name: string;
  role: string;
  revision: number;
  available: boolean;
  max_open: number;
  languages: string[];
  areas: string[];
  interests: string[];
  open_leads: number;
  due_now: number;
  calls_today: number;
  connected_today: number;
  first_call_minutes?: number | null;
};

export type Team = {
  reps: RepView[];
  settings: {
    revision: number;
    auto_reassign: boolean;
    reassign_minutes: number;
    default_country: string;
  };
  by_stage: Record<string, number>;
  by_source: Record<string, number>;
  unassigned: number;
  waiting_first_call: number;
  first_call_minutes?: number | null;
};

export type ImportPreview = {
  file_name: string;
  headers: string[];
  rows: Record<string, string>[];
  total_rows: number;
  truncated: boolean;
  mapping: Record<string, string>;
  with_phone: number;
  repeats_in_file: number;
};

export type ImportResult = {
  created: number;
  repeats: number;
  skipped: number;
  assigned: number;
  waiting: number;
};

export type SourceView = {
  source_id: string;
  kind: "webhook" | "sheet" | "meta";
  label: string;
  active: boolean;
  received: number;
  last_received_at: string | null;
  endpoint: string | null;
  sheet_url: string | null;
  token: string | null;
};

export type Sources = {
  sources: SourceView[];
  meta: "not_configured" | "ready";
};

export const NOT_CONNECTED_REASONS: { key: string; label: string }[] = [
  { key: "did_not_pick", label: "Did not pick" },
  { key: "busy", label: "Busy in another call" },
  { key: "disconnected", label: "Disconnected the call" },
  { key: "switched_off", label: "Switched off" },
  { key: "out_of_coverage", label: "Out of coverage / network issue" },
  { key: "not_connected", label: "Call could not be completed" },
  { key: "other", label: "Other reason" },
  { key: "invalid_number", label: "Invalid number" },
  { key: "incoming_not_available", label: "Incoming calls not available" },
  { key: "not_in_use", label: "Number not in use" },
];

export const CONNECTED_STAGES: {
  key: Stage;
  label: string;
  closes: boolean;
}[] = [
  { key: "follow_up", label: "Follow-up", closes: false },
  { key: "interested", label: "Interested", closes: false },
  { key: "won", label: "Won", closes: true },
  { key: "lost", label: "Lost", closes: true },
];

export const STAGE_FILTERS: { key: string; label: string }[] = [
  { key: "open", label: "Open" },
  { key: "new", label: "New" },
  { key: "not_connected", label: "Not connected" },
  { key: "follow_up", label: "Follow-up" },
  { key: "interested", label: "Interested" },
  { key: "won", label: "Won" },
  { key: "lost", label: "Lost" },
];

export const FIELD_LABELS: Record<string, string> = {
  name: "Name",
  phone: "Phone",
  email: "Email",
  company: "Company",
  city: "City",
  language: "Language",
  interest: "Interested in",
};

export class LeadsError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "LeadsError";
  }
}

const FALLBACK: Record<number, string> = {
  401: "Sign in to see your leads.",
  403: "Leads work inside an organisation workspace.",
  404: "That lead isn't on your desk any more.",
  409: "This lead changed. Check it and try again.",
  413: "That's too large to send.",
  422: "Check the details and try again.",
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      ...init,
      headers: { accept: "application/json", ...(init.headers ?? {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new LeadsError("Sales Xray isn't answering. Try again.", 0);
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no body */
    }
    throw new LeadsError(
      detail ?? FALLBACK[response.status] ?? "Something went wrong. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const commandId = () => crypto.randomUUID();

function isDesk(value: unknown): value is Desk {
  const desk = value as Desk;
  return (
    !!desk &&
    Array.isArray(desk.queue) &&
    typeof desk.me?.person_id === "string" &&
    typeof desk.counts?.open === "number" &&
    typeof desk.numbers?.calls === "number"
  );
}

export async function readDesk(signal?: AbortSignal): Promise<Desk> {
  const desk = await request<unknown>("", { signal });
  if (!isDesk(desk))
    throw new LeadsError("Your leads didn't load. Try again.", 0);
  return desk;
}

export function readNext(skip?: string, signal?: AbortSignal) {
  return request<LeadDetail | null>(
    skip ? `/next?skip=${encodeURIComponent(skip)}` : "/next",
    { signal },
  );
}

export function readLeads(
  {
    scope,
    stage,
    search,
    offset = 0,
  }: {
    scope: "mine" | "team" | "unassigned";
    stage?: string | null;
    search?: string;
    offset?: number;
  },
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ scope });
  if (stage) params.set("stage", stage);
  if (search?.trim()) params.set("search", search.trim().slice(0, 80));
  if (offset) params.set("offset", String(offset));
  return request<LeadPage>(`/leads?${params}`, { signal });
}

export function readLead(leadId: string, signal?: AbortSignal) {
  return request<LeadDetail>(`/leads/${encodeURIComponent(leadId)}`, {
    signal,
  });
}

export type NewLead = {
  source: "manual" | "referral";
  name: string;
  phone?: string;
  email?: string;
  company?: string;
  city?: string;
  language?: string;
  interest?: string;
  referred_by?: string;
  note?: string;
  assign: "rules" | "me" | "person";
  person_id?: string;
};

export function addLead(lead: NewLead, command = commandId()) {
  const body = Object.fromEntries(
    Object.entries(lead).filter(([, value]) => value !== "" && value != null),
  );
  return request<LeadDetail>(
    "/leads",
    json("POST", { command_id: command, ...body }),
  );
}

export type Disposition = {
  connected: boolean;
  reason?: string;
  stage?: Stage;
  follow_up_at?: string;
  remark?: string;
  deal_value?: string;
};

export function dispose(
  lead: Pick<LeadRow, "lead_id" | "revision">,
  disposition: Disposition,
  command = commandId(),
) {
  const body = Object.fromEntries(
    Object.entries(disposition).filter(
      ([, value]) => value !== "" && value != null,
    ),
  );
  return request<LeadDetail>(
    `/leads/${encodeURIComponent(lead.lead_id)}/dispose`,
    json("POST", {
      command_id: command,
      expected_revision: lead.revision,
      ...body,
    }),
  );
}

export function reassign(
  lead: Pick<LeadRow, "lead_id" | "revision">,
  personId: string | null,
  command = commandId(),
) {
  return request<LeadDetail>(
    `/leads/${encodeURIComponent(lead.lead_id)}/assign`,
    json("POST", {
      command_id: command,
      expected_revision: lead.revision,
      person_id: personId,
    }),
  );
}

export function readTeam(signal?: AbortSignal) {
  return request<Team>("/team", { signal });
}

export function saveRep(
  rep: Pick<RepView, "person_id" | "revision">,
  rules: {
    available: boolean;
    max_open: number;
    languages: string[];
    areas: string[];
    interests: string[];
  },
) {
  return request<Team>(
    `/team/${encodeURIComponent(rep.person_id)}`,
    json("PUT", { expected_revision: rep.revision, ...rules }),
  );
}

export function saveSettings(
  revision: number,
  settings: { auto_reassign: boolean; reassign_minutes: number },
) {
  return request<Team>(
    "/settings",
    json("PUT", { expected_revision: revision, ...settings }),
  );
}

export function runSweep() {
  return request<{ moved: number }>("/sweep", { method: "POST" });
}

export async function previewImport(file: File) {
  return request<ImportPreview>("/imports/preview", {
    method: "POST",
    headers: {
      "content-type": file.type || "application/octet-stream",
      "x-file-name": file.name.replace(/[^\w .()-]+/g, "").slice(0, 200),
    },
    body: file,
  });
}

export function commitImport(
  preview: ImportPreview,
  mapping: Record<string, string>,
  assign: "rules" | "me",
  command = commandId(),
) {
  return request<ImportResult>(
    "/imports",
    json("POST", {
      command_id: command,
      file_name: preview.file_name,
      mapping,
      rows: preview.rows,
      assign,
    }),
  );
}

export function readSources(signal?: AbortSignal) {
  return request<Sources>("/sources", { signal });
}

export function addSource(source: {
  kind: "webhook" | "sheet";
  label: string;
  sheet_url?: string;
}) {
  return request<SourceView>("/sources", json("POST", source));
}

export function rotateSource(sourceId: string) {
  return request<SourceView>(
    `/sources/${encodeURIComponent(sourceId)}/rotate`,
    { method: "POST" },
  );
}

export function setSourceActive(sourceId: string, active: boolean) {
  return request<SourceView>(
    `/sources/${encodeURIComponent(sourceId)}/active`,
    json("POST", { active }),
  );
}

export function syncSource(sourceId: string) {
  return request<ImportResult>(
    `/sources/${encodeURIComponent(sourceId)}/sync`,
    { method: "POST" },
  );
}

export function seedTestLeads(count: number, command = commandId()) {
  return request<ImportResult>(
    "/sandbox/seed",
    json("POST", { command_id: command, count }),
  );
}

/* ---------- display helpers (pure, tested) ---------- */

export function minutesLabel(seconds: number): string {
  if (seconds < 60) return seconds ? `${seconds}s` : "0m";
  const minutes = Math.round(seconds / 60);
  return minutes < 60
    ? `${minutes}m`
    : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function ago(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(
    0,
    Math.round((now.getTime() - new Date(iso).getTime()) / 1000),
  );
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

export function when(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  const time = at.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (sameDay(at, now)) return `today ${time}`;
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (sameDay(at, tomorrow)) return `tomorrow ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(at, yesterday)) return `yesterday ${time}`;
  return `${at.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${time}`;
}

/** NeoDove's quick follow-up chips: One hour, Tomorrow (same time), Next week. */
export function quickFollowUp(
  choice: "hour" | "tomorrow" | "week",
  now: Date = new Date(),
): Date {
  const at = new Date(now);
  if (choice === "hour") at.setHours(at.getHours() + 1);
  else if (choice === "tomorrow") at.setDate(at.getDate() + 1);
  else at.setDate(at.getDate() + 7);
  at.setSeconds(0, 0);
  return at;
}

/** A value for <input type="datetime-local"> in the viewer's own time. */
export function localInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function splitList(text: string): string[] {
  const seen = new Set<string>();
  return text
    .split(/[,\n]/)
    .map((item) => item.trim().replace(/\s+/g, " "))
    .filter((item) => {
      const key = item.toLowerCase();
      if (!item || seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 40);
}
