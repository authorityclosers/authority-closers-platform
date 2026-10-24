/**
 * Sales Xray CRM (code name Lead Desk) API client: /v1/lead-desk.
 *
 * Reads check the few fields the screens depend on and ignore any others, so
 * a new API field never breaks the page. Writes carry a command id so a retry
 * after a dropped connection never records the same thing twice.
 */

import { withDisplayNames } from "../display-name";
import { sendWrite } from "../sync/write-queue";
import { earlyFetch, forgetSharedReads } from "../early-reads";
import type { MeetingView, MoveOption } from "./pipeline/pipeline-client";

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
  /** Its call is more than an hour late (a new lead counts from its arrival). */
  overdue?: boolean;
  /** The business own stage (its key), when it has a stage list (Lead stages). */
  step?: string | null;
  /** The organisation's pipeline the lead is in ("main" until there are more). */
  pipeline?: string;
  /** They called, nobody picked up, and nobody has called back yet. */
  missed_at?: string | null;
  missed_calls?: number;
  /** Lead OS: when it entered its stage (null: not moved since Lead OS). */
  stage_at?: string | null;
  group?: "active" | "won" | "lost" | "junk";
  outcome_reason?: string | null;
  outcome_reason_label?: string | null;
  last_contact_at?: string | null;
  next_action_note?: string | null;
  /** An open lead past New with no follow-up set. */
  no_next_action?: boolean;
  /** It has an email address: the card offers one-tap Email. */
  has_email?: boolean;
};

export type MessageTemplate = { key: string; label: string; text: string };

export type Stage =
  | "new"
  | "not_connected"
  | "follow_up"
  | "interested"
  | "won"
  | "lost"
  | "junk";

export type Desk = {
  me: {
    person_id: string;
    name: string;
    role: string;
    can_manage: boolean;
    /** Off: the lead rules give this seller no new leads (UX study item 8). */
    taking_leads?: boolean;
    /** Outside work hours with the pause on: new leads wait until then. */
    paused_until?: string | null;
  };
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
    overdue?: number;
    call_back?: number;
  };
  queue: LeadRow[];
  call_mode: "simulated" | "phone";
  sandbox: boolean;
  generated_at: string;
  /** The next few days, after today. */
  upcoming?: LeadRow[];
  templates?: MessageTemplate[];
  /** Missed calls from my leads, newest first, until someone calls back. */
  call_back?: LeadRow[];
};

export type { Badge } from "./badge-client";

export type LeadEvent = {
  kind:
    | "captured"
    | "repeat"
    | "assigned"
    | "reassigned"
    | "call"
    | "result"
    | "note"
    | "edited"
    | "message"
    | "scheduled"
    | "stage"
    | "meeting"
    | "suggestion";
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
  recording?: boolean | null;
  duration_seconds: number | null;
  changed?: string[] | null;
  channel?: string | null;
  template_label?: string | null;
  /** "phone": the seller's phone logged this call by itself (UX study item 5). */
  via?: "phone" | null;
  direction?:
    | "outgoing"
    | "incoming"
    | "missed"
    | "rejected"
    | "blocked"
    | null;
  /** A phone-logged call: its seller may mark it private (shown to them only). */
  event_id?: string | null;
  can_hide?: boolean;
  private?: boolean;
  /** A stage move (Lead OS): how, from where, by whom or what, and why. */
  action?: "move" | "close" | "reopen" | "reclassify" | string | null;
  from_label?: string | null;
  move_source?: string | null;
  outcome_reason?: string | null;
  outcome_reason_label?: string | null;
  /** A meeting's history: scheduled, rescheduled, done, missed, cancelled. */
  meeting_action?: string | null;
  starts_at?: string | null;
  from_starts_at?: string | null;
  mode_label?: string | null;
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
  /** The business's own stages a seller picks after a call (Lead stages). */
  stage_choices?: StageChoice[];
  /** Where the lead's last call says it got to, when further than its stage. */
  stage_suggestion?: StageSuggestion | null;
  /** Lead OS: where it may go now, for this person, and what each asks. */
  moves?: MoveOption[];
  /** Its scheduled meeting, if one is booked. */
  meeting?: MeetingView | null;
  /** Its open tasks, the next one first (work-memory engine). */
  tasks?: TaskView[];
};

export type StageSuggestion = {
  step: string;
  label: string;
  kind: Stage;
  why: string;
  at: string;
};

export type StageChoice = {
  key: string;
  label: string;
  kind: Stage;
  meaning: string;
};

export type LeadPage = {
  leads: LeadRow[];
  total: number;
  next_offset: number | null;
  /** Every stage's count for the same people and search (the stage tabs). */
  stage_counts?: Record<string, number>;
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
  /** The seller's phone as their app last reported it (UX study item 7). */
  phone?: PhoneHealth | null;
};

/** The team's work days and hours, India time (0 is Monday). */
export type WorkHours = {
  days: number[];
  start: string;
  end: string;
  pause_leads: boolean;
  inside: boolean;
  next_start: string | null;
};

export type PhoneHealth = {
  reported_at: string;
  app_version: string | null;
  family: string | null;
  checks: Record<string, boolean>;
  done: number;
  total: number;
  call_log_on: boolean;
  /** When the phone's call history last reached Sales Xray. */
  synced_at: string | null;
};

export type Team = {
  reps: RepView[];
  settings: {
    revision: number;
    auto_reassign: boolean;
    reassign_minutes: number;
    default_country: string;
    work_hours?: WorkHours | null;
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
  /** Numbers in the file that are already leads: kept there, never added again. */
  known_leads?: number;
};

export type ImportResult = {
  created: number;
  repeats: number;
  skipped: number;
  assigned: number;
  waiting: number;
  /** Stage and owner columns: new leads given the stage or owner their row named. */
  staged?: number;
  owned?: number;
  /** What matched no stage or teammate (the first ten). */
  unmatched_stages?: string[];
  unmatched_owners?: string[];
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
    /** Not on the server yet, but kept on this phone and sent again (sync/write-queue.ts). */
    readonly kept = false,
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

/**
 * Lead details read ahead (app speed, 23 Oct 2026): the leads a seller is
 * most likely to open next are read once the desk loads, so their sheet opens
 * on its details instead of an outline. An answer is kept AHEAD_MS for the
 * identity that read it and taken once; any write drops them all, so a sheet
 * never shows a lead as it was before a change.
 */
export const AHEAD_MS = 60_000;
const AHEAD_MOST = 12;
// A read ahead that failed: the opening reads for itself.
const FAILED = Symbol("failed");
const ahead = new Map<string, { at: number; p: Promise<unknown> }>();
let aheadScope: string | null = null;

/** Whose reads these are (person, session, workspace); a change drops them. */
export function setAheadScope(scope: string | null) {
  if (scope !== aheadScope) ahead.clear();
  aheadScope = scope;
}

function readAhead(path: string) {
  if (!aheadScope) return;
  const known = ahead.get(path);
  if (known && Date.now() - known.at <= AHEAD_MS) return;
  while (ahead.size >= AHEAD_MOST) {
    const oldest = ahead.keys().next().value;
    if (oldest === undefined) break;
    ahead.delete(oldest);
  }
  ahead.set(path, {
    at: Date.now(),
    p: request<unknown>(path).catch(() => FAILED),
  });
}

/** What was read ahead for this path, taken once, or null (none, or too old). */
function takeAhead<T>(path: string, signal?: AbortSignal): Promise<T> | null {
  const known = ahead.get(path);
  ahead.delete(path);
  if (!known || Date.now() - known.at > AHEAD_MS) return null;
  return known.p.then((value) => {
    if (signal?.aborted)
      throw new DOMException("The read was cancelled.", "AbortError");
    return value === FAILED ? request<T>(path, { signal }) : (value as T);
  });
}

const leadPath = (leadId: string) => `/leads/${encodeURIComponent(leadId)}`;

function nextPath(skip?: string, pipeline?: string | null) {
  const query = new URLSearchParams();
  if (skip) query.set("skip", skip);
  if (pipeline) query.set("pipeline", pipeline);
  const asked = query.toString();
  return asked ? `/next?${asked}` : "/next";
}

/** Start reading a lead's details now, for its sheet to take when it opens. */
export function readLeadAhead(leadId: string) {
  readAhead(leadPath(leadId));
}

/** Start reading Start calling's first lead now, in the pipeline To call shows. */
export function readNextAhead(pipeline?: string | null) {
  readAhead(nextPath(undefined, pipeline));
}

/** A seller's entry that didn't arrive yet but waits on this phone. */
export const KEPT_MESSAGE =
  "Not sent yet: Sales X-Ray isn't answering. It's kept on this phone and goes as soon as it answers.";

/** The same, when the phone's storage refused it: it waits while the app runs. */
export const HELD_MESSAGE =
  "Not sent yet, and this phone couldn't store it. Keep Sales X-Ray open: it goes as soon as Sales X-Ray answers.";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const write = (init.method ?? "GET").toUpperCase() !== "GET";
  // A write may change any lead: nothing read ahead or shared is shown after it.
  if (write) {
    ahead.clear();
    forgetSharedReads();
  }
  const options: RequestInit = {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    ...init,
    headers: { accept: "application/json", ...(init.headers ?? {}) },
  };
  let response: Response;
  try {
    if (write) {
      // A seller's entry stays on this phone until the server has it, and
      // goes again by itself (owner's P0, 24 Oct 2026: nothing lost).
      const sent = await sendWrite(`${API}${path}`, options);
      if (sent.kind === "kept")
        throw new LeadsError(
          sent.onDevice ? KEPT_MESSAGE : HELD_MESSAGE,
          0,
          true,
        );
      response = sent.response;
    } else {
      // A read the Leads tab press already started (early-reads.ts) is
      // taken as it lands; anything else goes to the network.
      response = await earlyFetch(`${API}${path}`, options);
    }
  } catch (error) {
    if (error instanceof LeadsError) throw error;
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new LeadsError("Sales X-Ray isn't answering. Try again.", 0);
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
  // Names with capitals on every screen (owner, 22 Oct); stored as typed.
  return withDisplayNames((await response.json()) as T, PEOPLE);
}

/** Lead and person names in Lead Desk answers (not stages, sources or files). */
const PEOPLE: ReadonlySet<string> = new Set([
  "name",
  "owner_name",
  "actor_name",
  "previous_owner_name",
]);

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const commandId = () => crypto.randomUUID();

/** The same request and body helpers for the pipeline client (Lead OS). */
export { request as deskRequest, json as deskJson };

/** Overdue, then call now, then later today: the due-now list in sections. */
export function deskSections(
  all: LeadRow[],
  /** Leads already listed under Call back: not again here. */
  callBack: readonly LeadRow[] = [],
): {
  key: "overdue" | "now" | "later";
  title: string;
  rows: LeadRow[];
}[] {
  const listed = new Set(callBack.map((row) => row.lead_id));
  const queue = all.filter((row) => !listed.has(row.lead_id));
  const overdue = queue.filter((row) => row.overdue);
  const now = queue.filter(
    (row) =>
      !row.overdue && row.why_kind !== "later" && row.why_kind !== "open",
  );
  const later = queue.filter(
    (row) =>
      !row.overdue && (row.why_kind === "later" || row.why_kind === "open"),
  );
  return [
    { key: "overdue" as const, title: "Overdue", rows: overdue },
    { key: "now" as const, title: "Call now", rows: now },
    { key: "later" as const, title: "Later today", rows: later },
  ].filter((section) => section.rows.length);
}

/**
 * The leads a seller is most likely to open next, in the desk's order: those
 * waiting for a call back, then overdue, then due now (never Later today).
 */
export function likelyNext(
  desk: Pick<Desk, "queue" | "call_back">,
  count = 3,
): string[] {
  const callBack = desk.call_back ?? [];
  const ids = [
    ...callBack,
    ...deskSections(desk.queue, callBack)
      .filter((section) => section.key !== "later")
      .flatMap((section) => section.rows),
  ].map((row) => row.lead_id);
  return [...new Set(ids)].slice(0, count);
}

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

/** My day; with a pipeline, its leads only (Start calling one pipeline at a time). */
export async function readDesk(
  signal?: AbortSignal,
  pipeline?: string | null,
): Promise<Desk> {
  const desk = await request<unknown>(
    pipeline ? `?pipeline=${encodeURIComponent(pipeline)}` : "",
    { signal },
  );
  if (!isDesk(desk))
    throw new LeadsError("Your leads didn't load. Try again.", 0);
  return desk;
}

export function readNext(
  skip?: string,
  signal?: AbortSignal,
  pipeline?: string | null,
) {
  const path = nextPath(skip, pipeline);
  return (
    takeAhead<LeadDetail | null>(path, signal) ??
    request<LeadDetail | null>(path, { signal })
  );
}

/** The list's sort and filters, answered by the server over every lead, not one
 *  page (owner, 24 Oct 2026: "filters and sorting both on mobile as well as PC"). */
export type ListSort = "next_action" | "last_contact" | "name" | "created";
export type ListDue = "late" | "today" | "week" | "none";
export type ListSince = "today" | "week" | "month" | "never";
export type ListMade = "today" | "week" | "month";
export type ListMore = {
  source?: string | null;
  due?: ListDue | null;
  contact?: ListSince | null;
  created?: ListMade | null;
  sort?: ListSort | null;
  order?: "asc" | "desc" | null;
};

/** The address parameters of the list's sort and filters, in a fixed order. */
export function moreParams(
  more: ListMore | null | undefined,
): [string, string][] {
  if (!more) return [];
  return (
    [
      ["source", more.source],
      ["due", more.due],
      ["contact", more.contact],
      ["created", more.created],
      ["sort", more.sort],
      ["order", more.sort ? more.order : null],
    ] as [string, string | null | undefined][]
  ).filter((pair): pair is [string, string] => !!pair[1]);
}

export function readLeads(
  {
    scope,
    stage,
    search,
    offset = 0,
    test = false,
    owner,
    pipeline,
    more,
  }: {
    scope: "mine" | "team" | "unassigned";
    stage?: string | null;
    search?: string;
    offset?: number;
    /** Test and sample leads only, in every stage. */
    test?: boolean;
    /** One seller's leads (team scope, owners and admins): their profile. */
    owner?: string;
    /** One pipeline's leads; none: every pipeline's. */
    pipeline?: string | null;
    /** Sort and filters over the whole list. */
    more?: ListMore | null;
  },
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ scope });
  for (const [key, value] of moreParams(more)) params.set(key, value);
  if (owner) params.set("owner", owner);
  if (pipeline) params.set("pipeline", pipeline);
  if (stage) params.set("stage", stage);
  if (search?.trim()) params.set("search", search.trim().slice(0, 80));
  if (offset) params.set("offset", String(offset));
  if (test) params.set("test", "only");
  return request<LeadPage>(`/leads?${params}`, { signal });
}

/** My work: what the seller did, today, yesterday or this week. */
export type WorkDay = "today" | "yesterday" | "week";
export type ActivityItem = {
  event_id: string;
  lead_id: string;
  lead_name: string;
  stage_label: string | null;
  event: LeadEvent;
};
export type ActivityPage = {
  items: ActivityItem[];
  next_before: string | null;
  counts: Record<string, number>;
};

export function readActivity(
  day: WorkDay,
  before: string | null = null,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ day });
  if (before) params.set("before", before);
  return request<ActivityPage>(`/activity?${params}`, { signal });
}

/* ---------- Tasks (work-memory engine, docs/product/lead-desk/work-memory-engine.md) ---------- */

export type TaskKind =
  | "call_back"
  | "whatsapp"
  | "email"
  | "send_file"
  | "meeting"
  | "other";
export type TaskBucket = "overdue" | "today" | "upcoming";
export type TaskSnoozeChoice = "15m" | "1h" | "evening" | "tomorrow";

export type TaskView = {
  task_id: string;
  lead_id: string;
  lead_name: string;
  kind: TaskKind;
  title: string;
  note: string | null;
  starts_at: string;
  ends_at: string | null;
  location: string | null;
  status: "open" | "done" | "cancelled";
  done_at: string | null;
  original_due_at: string;
  snoozes: number;
  rollovers: number;
  source: string;
  revision: number;
  owner_person_id: string | null;
  /** Open and a minute past its due. */
  overdue: boolean;
  bucket: TaskBucket | null;
};

export type TaskList = {
  tasks: TaskView[];
  counts: Partial<Record<TaskBucket, number>>;
};

export type NewTask = {
  kind: TaskKind;
  starts_at: string;
  ends_at?: string | null;
  location?: string | null;
  note?: string | null;
};

/** A seller's open tasks in one bucket, earliest first, with every bucket's count. */
export function readTasks(view: TaskBucket, signal?: AbortSignal) {
  return request<TaskList>(`/tasks?view=${view}`, { signal });
}

export function addTask(leadId: string, task: NewTask, command = commandId()) {
  const body = Object.fromEntries(
    Object.entries(task).filter(([, value]) => value !== "" && value != null),
  );
  return request<TaskView>(
    `/leads/${encodeURIComponent(leadId)}/tasks`,
    json("POST", {
      command_id: command,
      client_at: new Date().toISOString(),
      ...body,
    }),
  );
}

/** Notes: what people wrote on your leads, newest first; with words, what says
 *  them (v0.89). A note on its own and the remark saved with a call's outcome. */
export function readNotes(
  q: string | null = null,
  before: string | null = null,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams();
  if (q?.trim()) params.set("q", q.trim().slice(0, 80));
  if (before) params.set("before", before);
  const query = params.toString();
  return request<ActivityPage>(`/notes${query ? `?${query}` : ""}`, {
    signal,
  });
}

export type SearchResult = {
  leads: LeadRow[];
  notes: ActivityItem[];
  tasks: TaskView[];
};

/** A few words (two letters at least) across leads, notes and open tasks. */
export function searchDesk(q: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ q: q.trim().slice(0, 80) });
  return request<SearchResult>(`/search?${params}`, { signal });
}

/** Done, undo or cancel, on the revision this device saw. */
export function taskAction(
  task: Pick<TaskView, "task_id" | "revision">,
  action: "done" | "undo" | "cancel",
  command = commandId(),
) {
  return request<TaskView>(
    `/tasks/${encodeURIComponent(task.task_id)}/${action}`,
    json("POST", {
      command_id: command,
      expected_revision: task.revision,
      client_at: new Date().toISOString(),
    }),
  );
}

export function snoozeTask(
  task: Pick<TaskView, "task_id" | "revision">,
  choice: TaskSnoozeChoice,
  command = commandId(),
) {
  return request<TaskView>(
    `/tasks/${encodeURIComponent(task.task_id)}/snooze`,
    json("POST", {
      command_id: command,
      expected_revision: task.revision,
      client_at: new Date().toISOString(),
      choice,
    }),
  );
}

/** At most this many leads go in one delete. */
export const DELETE_LIMIT = 500;

export type LeadsDeleted = {
  deleted: number;
  lead_ids: string[];
  /** Asked for but not here any more (deleted already). */
  not_found: number;
};

/**
 * Delete leads for good (owners and admins, after a confirm). Keep one command
 * id per confirm: a retry after a dropped connection never deletes twice.
 */
export function deleteLeads(leadIds: string[], command = commandId()) {
  return request<LeadsDeleted>(
    "/leads/delete",
    json("POST", { command_id: command, lead_ids: leadIds }),
  );
}

export function readLead(leadId: string, signal?: AbortSignal) {
  const path = leadPath(leadId);
  // Read ahead: taken as it lands (or read now, if that read failed).
  return (
    takeAhead<LeadDetail>(path, signal) ?? request<LeadDetail>(path, { signal })
  );
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
  /** A pipeline picked by hand; none: the one that takes added leads. */
  pipeline?: string;
};

/** Whether a number is already a lead (Add lead asks while it is typed). */
export type LeadMatch = {
  found: boolean;
  /** Only for a manager, or the lead's own owner. */
  lead_id?: string | null;
  name?: string | null;
  stage_label?: string | null;
  owner_name?: string | null;
  yours?: boolean;
};

export function matchLead(phone: string, signal?: AbortSignal) {
  return request<LeadMatch>(
    `/leads/match?${new URLSearchParams({ phone: phone.slice(0, 40) })}`,
    { signal },
  );
}

export function addLead(lead: NewLead, command = commandId()) {
  const body = Object.fromEntries(
    Object.entries(lead).filter(([, value]) => value !== "" && value != null),
  );
  return request<LeadDetail>(
    "/leads",
    json("POST", { command_id: command, ...body }),
  );
}

export type LeadFields = {
  name?: string;
  phone?: string;
  email?: string;
  company?: string;
  city?: string;
  language?: string;
  interest?: string;
};

/** Correct a lead's details: only the fields sent change; "" clears one. */
export function editLead(
  lead: Pick<LeadRow, "lead_id" | "revision">,
  fields: LeadFields,
  command = commandId(),
) {
  return request<LeadDetail>(
    `/leads/${encodeURIComponent(lead.lead_id)}`,
    json("PATCH", {
      command_id: command,
      expected_revision: lead.revision,
      ...fields,
    }),
  );
}

export function addNote(leadId: string, note: string, command = commandId()) {
  return request<LeadDetail>(
    `/leads/${encodeURIComponent(leadId)}/notes`,
    json("POST", { command_id: command, note }),
  );
}

export type Disposition = {
  connected: boolean;
  reason?: string;
  stage?: Stage;
  /** One of the business's own stages (Lead stages); its kind goes as `stage`. */
  step?: string;
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

/** Move a lead to one of the business's stages without a call (Lead stages). */
export async function moveToStage(
  lead: Pick<LeadRow, "lead_id" | "revision">,
  step: string,
  command = commandId(),
): Promise<LeadDetail> {
  await request<unknown>(
    `/leads/${encodeURIComponent(lead.lead_id)}/stage`,
    json("POST", {
      commandId: command,
      expectedRevision: lead.revision,
      step,
    }),
  );
  return readLead(lead.lead_id);
}

/** Book the next call without a call (long-press on the list). */
export function setFollowUp(
  lead: Pick<LeadRow, "lead_id" | "revision">,
  at: Date,
  command = commandId(),
) {
  return request<LeadDetail>(
    `/leads/${encodeURIComponent(lead.lead_id)}/follow-up`,
    json("POST", {
      command_id: command,
      expected_revision: lead.revision,
      at: at.toISOString(),
    }),
  );
}

export type Channel = "whatsapp" | "sms";

/** Notes on the lead that a ready message went out; only its template is kept. */
export function logMessage(
  leadId: string,
  message: { channel: Channel; template: string | null; edited: boolean },
  command = commandId(),
) {
  return request<LeadDetail>(
    `/leads/${encodeURIComponent(leadId)}/messages`,
    json("POST", { command_id: command, ...message }),
  );
}

export { readBadge } from "./badge-client";

export type PushConfig = {
  enabled: boolean;
  project_id?: string | null;
  app_id?: string | null;
  api_key?: string | null;
  sender_id?: string | null;
};

export async function readPushConfig(): Promise<PushConfig | null> {
  try {
    return await request<PushConfig>("/push");
  } catch {
    return null;
  }
}

export function registerDevice(token: string, appVersion?: string) {
  return request<{ registered: boolean }>(
    "/devices",
    json("POST", { token, platform: "android", app_version: appVersion }),
  );
}

export function forgetDevice(token: string) {
  return request<{ registered: boolean }>(
    "/devices/forget",
    json("POST", { token, platform: "android" }),
  );
}

export type BulkAction = "assign" | "stage" | "pipeline";
export type BulkDone = { done: number; skipped: number; words: string };

/** Many leads at once (owners and admins): give, re-stage or move them. */
export function bulkLeads(
  body: {
    action: BulkAction;
    lead_ids: string[];
    person_id?: string | null;
    step?: string;
    pipeline?: string;
  },
  command = commandId(),
) {
  return request<BulkDone>(
    "/leads/bulk",
    json("POST", { command_id: command, ...body }),
  );
}

/** An approved WhatsApp template, as Meta last said (Settings → Connected apps). */
export type WaTemplate = {
  name: string;
  language: string;
  status: string;
  text: string;
  /** How many {{n}} parts it asks for. */
  parts: number;
};

/** The organisation's approved WhatsApp templates; none when WhatsApp isn't set up. */
export async function readApprovedTemplates(
  signal?: AbortSignal,
): Promise<WaTemplate[]> {
  // Read as sent: a template's name is Meta's id ("welcome_lead"), not a person's.
  const response = await fetch(`${API}/whatsapp/status`, {
    credentials: "same-origin",
    cache: "no-store",
    signal,
    headers: { accept: "application/json" },
  });
  if (!response.ok) return [];
  const status = (await response.json()) as {
    numbers?: unknown[];
    templates?: WaTemplate[];
  };
  if (!status.numbers?.length) return [];
  return (status.templates ?? []).filter((item) => item.status === "APPROVED");
}

export type BulkWhatsApp = {
  ready: number;
  skipped: { reason: string; words: string; count: number }[];
  sent: number;
  failed: number;
  /** The template as a lead reads it ({name} stays as written). */
  text: string;
  limit: number;
};

/**
 * One approved template to many leads (owners and admins). Without `confirm` it only
 * says who would get it; a send must quote the count that check showed.
 */
export function bulkWhatsApp(
  body: {
    leadIds: string[];
    template: string;
    language: string;
    values: string[];
  },
  send: { commandId: string; confirm: number } | null = null,
) {
  return request<BulkWhatsApp>(
    send ? "/leads/bulk-whatsapp" : "/leads/bulk-whatsapp/preview",
    json("POST", send ? { ...body, ...send } : body),
  );
}

/** Move a lead to another of the organisation's pipelines (owners and admins). */
export function movePipeline(
  lead: Pick<LeadRow, "lead_id" | "revision">,
  pipeline: string,
  command = commandId(),
) {
  return request<LeadDetail>(
    `/leads/${encodeURIComponent(lead.lead_id)}/pipeline`,
    json("POST", {
      command_id: command,
      expected_revision: lead.revision,
      pipeline,
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

/** The seller's own "Taking new leads" switch. */
/** Me on the desk: whether new leads come to me (the account sheet's switch). */
export function readMe(signal?: AbortSignal) {
  return request<Desk["me"]>("/me", { signal });
}

export function setTaking(taking: boolean) {
  return request<Desk["me"]>("/me/taking", json("PUT", { taking }));
}

/** The phone app's setup checklist, for the seller's manager on Team (UX study item 7). */
export function reportPhone(report: {
  device_id: string;
  app_version?: string;
  family?: string;
  checks: Record<string, boolean>;
}) {
  return request<PhoneHealth>("/me/phone", json("POST", report));
}

export function readTeam(signal?: AbortSignal) {
  return request<Team>("/team", { signal });
}

/** One period's sales outcomes (Home, owners and admins). */
export type Outcomes = {
  calls: number;
  connected: number;
  /** Different leads called at least once. */
  leads_called: number;
  /** Different leads moved to an interested or a won stage. */
  interested: number;
  won: number;
  new_leads: number;
  first_call_minutes: number | null;
};

export type SellerOutcome = {
  person_id: string;
  name: string;
  calls: number;
  connected: number;
  interested: number;
  won: number;
  open_leads: number;
  late: number;
};

export type Performance = {
  days: number;
  start: string;
  end: string;
  current: Outcomes;
  previous: Outcomes;
  sellers: SellerOutcome[];
  pipeline: Record<string, number>;
  /** The same open leads by stage, per pipeline (by the pipeline's key). */
  pipelines?: Record<string, Record<string, number>>;
};

export type Period = 1 | 7 | 30;

/** How sales went today, or over 7 or 30 days, beside the period before. */
export function readPerformance(days: Period, signal?: AbortSignal) {
  return request<Performance>(`/reports/performance?days=${days}`, { signal });
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

/** Sets the team's work hours; no days clears them. */
export function saveWorkHours(
  revision: number,
  hours: { days: number[]; start: string; end: string; pause_leads: boolean },
) {
  return request<Team>(
    "/work-hours",
    json("PUT", { expected_revision: revision, ...hours }),
  );
}

export type CallReport = {
  start: string;
  end: string;
  sellers: {
    person_id: string;
    name: string;
    days: {
      day: string;
      calls: number;
      connected: number;
      talk_seconds: number;
      missed: number;
    }[];
    calls: number;
    connected: number;
    talk_seconds: number;
    missed: number;
  }[];
};

/** Hides a call the seller's phone logged from everyone else, or shows it again. */
export function setCallPrivacy(
  eventId: string,
  hidden: boolean,
  command = commandId(),
) {
  return request<LeadDetail>(
    `/calls/${encodeURIComponent(eventId)}/private`,
    json("POST", { command_id: command, private: hidden }),
  );
}

/** Calls by seller by day, India time (managers). */
export function readCallReport(
  start: string,
  end: string,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({ start, end });
  return request<CallReport>(`/reports/calls?${query}`, { signal });
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
  pipeline: string | null = null,
) {
  return request<ImportResult>(
    "/imports",
    json("POST", {
      command_id: command,
      file_name: preview.file_name,
      mapping,
      rows: preview.rows,
      assign,
      ...(pipeline ? { pipeline } : {}),
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

/** A wait in words: "45 min", "22 h 38 min", "2 d 4 h" (Redmi sweep, 24 Oct 2026:
 *  "1358 min" read as a number, not a time). */
export function waitWords(minutes: number): string {
  const total = Math.max(0, Math.round(minutes));
  if (total < 60) return `${total} min`;
  const hours = Math.floor(total / 60);
  if (hours < 24) {
    const rest = total % 60;
    return rest ? `${hours} h ${rest} min` : `${hours} h`;
  }
  const days = Math.floor(hours / 24);
  const left = hours % 24;
  return left ? `${days} d ${left} h` : `${days} d`;
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

export type CallTime = "hour" | "evening" | "morning" | "week" | "someday";

/**
 * When to call again, as a human time: this evening, tomorrow at 10, next
 * week at 10, or Someday (Privyr's, UX study item 9): three weeks out at 11,
 * moved off a Sunday, so a "not now" lead still has a next date.
 */
export function nextCallTime(choice: CallTime, now: Date = new Date()): Date {
  const at = new Date(now);
  at.setSeconds(0, 0);
  if (choice === "hour") {
    at.setHours(at.getHours() + 1);
    return at;
  }
  if (choice === "someday") {
    at.setDate(at.getDate() + 21);
    if (at.getDay() === 0) at.setDate(at.getDate() + 1);
    at.setHours(11, 0, 0, 0);
    return at;
  }
  if (choice === "evening") {
    const six = new Date(at);
    six.setHours(18, 0, 0, 0);
    if (six.getTime() - now.getTime() >= 60 * 60 * 1000) return six;
    at.setHours(at.getHours() + 2);
    return at;
  }
  at.setDate(at.getDate() + (choice === "morning" ? 1 : 7));
  at.setHours(10, 0, 0, 0);
  return at;
}

export type PickedContact = { name: string; phone: string; email?: string };

type ContactsManager = {
  select: (
    properties: string[],
    options?: { multiple?: boolean },
  ) => Promise<{ name?: string[]; tel?: string[]; email?: string[] }[]>;
};

/** The phone's contact picker (Android Chrome and the Sales Xray app). */
export function contactsSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    "contacts" in navigator &&
    typeof window !== "undefined" &&
    "ContactsManager" in window
  );
}

export async function pickContacts(): Promise<PickedContact[]> {
  const manager = (navigator as Navigator & { contacts?: ContactsManager })
    .contacts;
  if (!manager) return [];
  const picked = await manager.select(["name", "tel", "email"], {
    multiple: true,
  });
  return picked
    .map((person) => ({
      name: (person.name?.[0] ?? "").trim(),
      phone: (person.tel?.[0] ?? "").trim(),
      email: person.email?.[0]?.trim() || undefined,
    }))
    .filter((person) => person.name || person.phone);
}

/** Name, phone and email from pasted text: a WhatsApp message or contact card. */
export type SharedLead = {
  name: string;
  phone: string;
  email: string;
  note: string;
};

/**
 * A lead handed over in the link, as the Sales Xray Chrome extension opens
 * /leads#add=lead&name=…&phone=…&email=…&note=…. The details sit after "#",
 * so browsers never send them to a server. They only fill the Add lead form;
 * nothing is saved until the person taps Add lead.
 */
export function sharedLead(params: {
  get: (name: string) => string | null;
}): SharedLead | null {
  if (params.get("add") !== "lead") return null;
  const take = (name: string, max: number) =>
    (params.get(name) ?? "").trim().slice(0, max);
  const lead = {
    name: take("name", 200),
    phone: take("phone", 40),
    email: take("email", 254),
    note: take("note", 1000),
  };
  return lead.name || lead.phone || lead.email || lead.note ? lead : null;
}

export function parseContactText(text: string): {
  name?: string;
  phone?: string;
  email?: string;
} {
  const email = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i.exec(text)?.[0];
  const rest = email ? text.replace(email, " ") : text;
  const digits = /\+?\d[\d\s().-]{7,}\d/.exec(rest)?.[0];
  const phone = digits ? digits.replace(/[^\d+]/g, "") : undefined;
  const name = text
    .split(/\r?\n/)
    .map((line) =>
      line
        .replace(/^\s*(name|naam|contact)\s*[:\-]\s*/i, "")
        .replace(/^[~*\s]+|[*\s]+$/g, ""),
    )
    .find(
      (line) =>
        line.length > 1 &&
        line.length <= 80 &&
        /[A-Za-z\u0900-\u097F]/.test(line) &&
        !line.includes("@") &&
        !/\d{5,}/.test(line.replace(/\s/g, "")),
    );
  return {
    name: name || undefined,
    phone: phone && phone.replace(/\D/g, "").length >= 8 ? phone : undefined,
    email,
  };
}

export const SAMPLE_CSV = [
  "Name,Phone,Email,City,Interested in",
  "Asha Patil,98765 43210,asha@example.com,Pune,Solar rooftop",
  "Ravi Kumar,+91 91234 56780,,Mumbai,Home loan",
].join("\n");

/** A phone number as people read it: "+91 98765 43210" for Indian mobiles. */
export function displayPhone(phone: string): string {
  const india = /^\+91([6-9]\d{4})(\d{5})$/.exec(phone);
  return india ? `+91 ${india[1]} ${india[2]}` : phone;
}

/** A WhatsApp chat with this number (digits only, country code included). */
export function whatsappHref(phone: string, text?: string): string {
  const chat = `https://wa.me/${phone.replace(/[^0-9]/g, "")}`;
  return text ? `${chat}?text=${encodeURIComponent(text)}` : chat;
}

/** The phone's own Messages app with the text ready. */
export function smsHref(phone: string, text: string): string {
  return `sms:${phone.replace(/[^0-9+]/g, "")}?body=${encodeURIComponent(text)}`;
}

/** How a seller greets a lead: the first word of a real name, or "there". */
export function firstName(name: string): string {
  const word = name.trim().split(/\s+/)[0] ?? "";
  return /^[A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F.'-]*$/.test(word)
    ? word
    : "there";
}

/** A ready message with the lead's and the seller's names put in. */
export function fillTemplate(
  text: string,
  values: {
    leadName: string;
    myName: string;
    org: string;
    interest?: string | null;
  },
): string {
  const mine = firstName(values.myName);
  const fills: Record<string, string> = {
    first_name: firstName(values.leadName),
    my_name: mine === "there" ? values.myName.trim() : mine,
    org: values.org,
    about_interest: values.interest?.trim()
      ? ` about ${values.interest.trim()}`
      : "",
  };
  return text
    .replace(/\{(\w+)\}/g, (whole, name: string) => fills[name] ?? whole)
    .replace(/ from \./g, ".")
    .replace(/, \./g, ".")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/**
 * A lead to open from the link, as a phone alert opens /leads#lead=<id>
 * (and #lead=<id>&call=1 for its Call button). Ids only, after "#".
 */
export function linkedLead(
  hash: string,
): { leadId: string; call: boolean } | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const leadId = params.get("lead") ?? "";
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      leadId,
    )
  )
    return null;
  return { leadId, call: params.get("call") === "1" };
}

/** A lead's own link: Leads opens with its sheet up, on a phone or a computer. */
export function leadLink(leadId: string, origin = ""): string {
  return `${origin}${LEADS_PATH}?lead=${encodeURIComponent(leadId)}`;
}

/** Logs a call the seller placed from their own phone, with the time they were away. */
export function logPhoneCall(
  leadId: string,
  seconds: number | null,
  command = commandId(),
) {
  return request<LeadDetail>(
    `/leads/${encodeURIComponent(leadId)}/calls/phone`,
    json("POST", {
      command_id: command,
      ...(seconds == null
        ? {}
        : {
            duration_seconds: Math.min(7200, Math.max(0, Math.round(seconds))),
          }),
    }),
  );
}

// The call the seller just started from the desk, so the result can follow it
// even if the phone reloads the page while the dialer is open.
const PENDING_CALL = "sx-leads-pending-call";
const PENDING_MAX_MS = 3 * 60 * 60 * 1000;

export type PendingCall = { leadId: string; at: number };

export function rememberCall(leadId: string, now: number = Date.now()): void {
  try {
    localStorage.setItem(PENDING_CALL, JSON.stringify({ leadId, at: now }));
  } catch {
    // Storage blocked: the result is still asked when the lead is open.
  }
}

export function peekPendingCall(now: number = Date.now()): PendingCall | null {
  try {
    const raw = localStorage.getItem(PENDING_CALL);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<PendingCall>;
    if (typeof value.leadId !== "string" || typeof value.at !== "number")
      return null;
    if (now - value.at > PENDING_MAX_MS) {
      localStorage.removeItem(PENDING_CALL);
      return null;
    }
    return { leadId: value.leadId, at: value.at };
  } catch {
    return null;
  }
}

export function takePendingCall(now: number = Date.now()): PendingCall | null {
  const pending = peekPendingCall(now);
  try {
    localStorage.removeItem(PENDING_CALL);
  } catch {
    // Nothing to clear.
  }
  return pending;
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
