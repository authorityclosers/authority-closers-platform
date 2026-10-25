/**
 * Settings → AI apps (owner via the orchestrator, 24 Oct 2026: "redo Settings →
 * Connections / Developers"): the AI apps one person let into their own
 * account (/v1/me/connected-apps), and ending one. Revoked connections are
 * history, so only live ones are kept.
 */

export type AiApp = {
  id: string;
  name: string;
  /** The consent screen's checked mark: a first-party app on its own address. */
  verified: boolean;
  maker: string | null;
  scopes: string[];
  workspaceId: string;
  connectedAt: string;
  lastUsedAt: string | null;
};

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string =>
  typeof value === "string" && value.trim().length > 0;

/** The live connections, newest first as the server sends them; null for a bad shape. */
export function parseAiApps(value: unknown): AiApp[] | null {
  if (!record(value) || !Array.isArray(value.apps)) return null;
  const apps: AiApp[] = [];
  for (const item of value.apps) {
    if (
      !record(item) ||
      !text(item.id) ||
      !text(item.app) ||
      !text(item.tenant_id) ||
      !text(item.created_at) ||
      !Array.isArray(item.scopes)
    )
      return null;
    if (item.revoked_at !== null && item.revoked_at !== undefined) continue;
    apps.push({
      id: item.id,
      name: item.app,
      verified: item.verified === true,
      maker: text(item.maker) ? item.maker : null,
      scopes: item.scopes.filter(text),
      workspaceId: item.tenant_id,
      connectedAt: item.created_at,
      lastUsedAt: text(item.last_used_at) ? item.last_used_at : null,
    });
  }
  return apps;
}

const READS: readonly [string, string][] = [
  ["calls:read", "calls"],
  ["reports:read", "reports"],
  ["leads:read", "leads"],
];

// What an app may add (AI writes, 25 Oct 2026): leads, notes, tasks.
const WRITES: readonly [string, string][] = [
  ["leads:write", "leads"],
  ["leads:notes", "notes"],
  ["leads:tasks", "tasks"],
];

const joined = (words: string[]) =>
  words.length < 2
    ? words.join("")
    : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;

/** "Reads calls, reports and leads · adds leads": short, for a two-line row. */
export function accessWords(scopes: readonly string[]): string {
  const reads = READS.filter(([scope]) => scopes.includes(scope)).map(
    ([, word]) => word,
  );
  const parts = reads.length ? [`Reads ${joined(reads)}`] : [];
  const adds = WRITES.filter(([scope]) => scopes.includes(scope)).map(
    ([, word]) => word,
  );
  if (adds.length)
    parts.push(`${parts.length ? "adds" : "Adds"} ${joined(adds)}`);
  if (scopes.includes("webhooks:manage"))
    parts.push(parts.length ? "manages webhooks" : "Manages webhooks");
  return parts.join(" · ") || "Knows who you are";
}

const time = new Intl.DateTimeFormat("en-IN", {
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});
const day = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
});
const dayYear = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

/** "today 4:30 pm", "yesterday", "3 Oct", "3 Oct 2025". */
export function dayWords(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const midnight = (value: Date) =>
    new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const days = Math.round((midnight(now) - midnight(at)) / 86_400_000);
  if (days === 0) return `today ${time.format(at).toLowerCase()}`;
  if (days === 1) return "yesterday";
  return at.getFullYear() === now.getFullYear()
    ? day.format(at)
    : dayYear.format(at);
}

/** "Used today 4:30 pm" or "Not used yet". */
export function usedWords(app: AiApp, now?: Date): string {
  return app.lastUsedAt
    ? `Used ${dayWords(app.lastUsedAt, now)}`
    : "Not used yet";
}

const READ: RequestInit = {
  method: "GET",
  credentials: "same-origin",
  cache: "no-store",
  redirect: "error",
  headers: { accept: "application/json" },
};

export async function readAiApps(signal: AbortSignal): Promise<AiApp[]> {
  const response = await fetch("/v1/me/connected-apps", { ...READ, signal });
  if (!response.ok) throw new Error("ai_apps_read_rejected");
  const apps = parseAiApps(await response.json());
  if (!apps) throw new Error("ai_apps_shape_invalid");
  return apps;
}

/** Ends one connection at once; the answer is the list as it is now. */
export async function disconnectAiApp(id: string): Promise<AiApp[]> {
  const response = await fetch(
    `/v1/me/connected-apps/${encodeURIComponent(id)}/revoke`,
    { ...READ, method: "POST" },
  );
  if (!response.ok)
    throw new Error(
      response.status === 404 ? "ai_app_missing" : "ai_app_disconnect_rejected",
    );
  const apps = parseAiApps(await response.json());
  if (!apps) throw new Error("ai_apps_shape_invalid");
  return apps;
}

/* ----- Changes from AI apps (docs/product/ai-writes.md) ------------------------ */

export type AppChange = {
  id: string;
  action: string;
  leadId: string;
  /** Null for a lead deleted since. */
  leadName: string | null;
  /** "ChatGPT", "Claude", "API key sxk_live_ab12". */
  via: string;
  at: string;
  status: "applied" | "undone";
  canUndo: boolean;
};

/** The changes, newest first; null for a bad shape. */
export function parseAppChanges(value: unknown): AppChange[] | null {
  if (!record(value) || !Array.isArray(value.changes)) return null;
  const changes: AppChange[] = [];
  for (const item of value.changes) {
    if (
      !record(item) ||
      !text(item.change_id) ||
      !text(item.action) ||
      !text(item.lead_id) ||
      !text(item.via) ||
      !text(item.at) ||
      (item.status !== "applied" && item.status !== "undone")
    )
      return null;
    changes.push({
      id: item.change_id,
      action: item.action,
      leadId: item.lead_id,
      leadName: text(item.lead_name) ? item.lead_name : null,
      via: item.via,
      at: item.at,
      status: item.status,
      canUndo: item.can_undo === true,
    });
  }
  return changes;
}

/** "Added a note", "Added a task". */
export function changeWords(action: string): string {
  return action === "task"
    ? "Added a task"
    : action === "note"
      ? "Added a note"
      : "Changed a lead";
}

const DESK = "/v1/lead-desk";

/** The changes, or null where there is no lead desk (Personal, signed out). */
export async function readAppChanges(
  signal?: AbortSignal,
): Promise<AppChange[] | null> {
  const response = await fetch(`${DESK}/ai-changes`, { ...READ, signal });
  if (response.status === 401 || response.status === 403) return null;
  if (!response.ok) throw new Error("ai_changes_read_rejected");
  const changes = parseAppChanges(await response.json());
  if (!changes) throw new Error("ai_changes_shape_invalid");
  return changes;
}

async function refusal(response: Response): Promise<Error> {
  try {
    const body: unknown = await response.json();
    if (record(body) && text(body.detail)) return new Error(body.detail);
  } catch {
    // The status says enough.
  }
  return new Error("");
}

/** Undo one change: a note stops showing, an open task is cancelled. */
export async function undoAppChange(id: string): Promise<void> {
  const response = await fetch(
    `${DESK}/ai-changes/${encodeURIComponent(id)}/undo`,
    { ...READ, method: "POST" },
  );
  if (!response.ok) throw await refusal(response);
}

export type AiWritesSwitch = {
  revision: number;
  paused: boolean;
  note: boolean;
  task: boolean;
  outcome: boolean;
  /** Owners and admins. */
  canChange: boolean;
};

export function parseAiWrites(value: unknown): AiWritesSwitch | null {
  if (
    !record(value) ||
    typeof value.revision !== "number" ||
    typeof value.paused !== "boolean" ||
    typeof value.note !== "boolean" ||
    typeof value.task !== "boolean" ||
    typeof value.outcome !== "boolean"
  )
    return null;
  return {
    revision: value.revision,
    paused: value.paused,
    note: value.note,
    task: value.task,
    outcome: value.outcome,
    canChange: value.can_change === true,
  };
}

export async function readAiWrites(
  signal?: AbortSignal,
): Promise<AiWritesSwitch | null> {
  const response = await fetch(`${DESK}/ai-writes`, { ...READ, signal });
  if (response.status === 401 || response.status === 403) return null;
  if (!response.ok) throw new Error("ai_writes_read_rejected");
  return parseAiWrites(await response.json());
}

export async function saveAiWrites(
  next: AiWritesSwitch,
): Promise<AiWritesSwitch> {
  const response = await fetch(`${DESK}/ai-writes`, {
    ...READ,
    method: "PUT",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({
      expected_revision: next.revision,
      paused: next.paused,
      note: next.note,
      task: next.task,
      outcome: next.outcome,
    }),
  });
  if (!response.ok) throw await refusal(response);
  const saved = parseAiWrites({ ...(await response.json()), can_change: true });
  if (!saved) throw new Error("ai_writes_shape_invalid");
  return saved;
}
