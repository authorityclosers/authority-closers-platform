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
  ["reports:read", "call reports"],
  ["leads:read", "leads"],
];

const joined = (words: string[]) =>
  words.length < 2
    ? words.join("")
    : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;

/** "Reads your calls, call reports and leads · adds leads". */
export function accessWords(scopes: readonly string[]): string {
  const reads = READS.filter(([scope]) => scopes.includes(scope)).map(
    ([, word]) => word,
  );
  const parts = reads.length ? [`Reads your ${joined(reads)}`] : [];
  if (scopes.includes("leads:write"))
    parts.push(parts.length ? "adds leads" : "Adds leads");
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
