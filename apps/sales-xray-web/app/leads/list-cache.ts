/** Last first pages and desks, kept on this device, so the phone app's next
 * launch shows them at once while they sync (owner bug #67, 29 Oct 2026:
 * "cache and previous things can be preloaded"). A confirmed person + session
 * + workspace is required, and every filter is part of the key. One identity,
 * a day, six answers; signing out forgets them (list-cache-slot.ts). Storage
 * being unavailable must never stop a network read. */
import {
  deskWithMoves,
  inStageList,
  inWorkView,
  onLeadMoved,
} from "./lead-moves";
import type { Desk, LeadPage, LeadRow, ListMore } from "./leads-client";
import { readLeads } from "./leads-client";
import { LEADS_CACHE_SLOT as SLOT } from "./list-cache-slot";

const MAX_AGE = 24 * 60 * 60_000;
const MAX_ENTRIES = 6;
type Entry = { at: number; value: unknown };
type Store = { identity: string; entries: Record<string, Entry> };
const valid = (identity: string | null | undefined): identity is string => {
  if (!identity) return false;
  try {
    const parts: unknown = JSON.parse(identity);
    return (
      Array.isArray(parts) &&
      parts.length === 3 &&
      parts.every((part) => typeof part === "string" && !!part)
    );
  } catch {
    return false;
  }
};
function read(identity: string): Store {
  try {
    const stored = JSON.parse(
      localStorage.getItem(SLOT) ?? "null",
    ) as Store | null;
    if (
      stored?.identity === identity &&
      stored.entries &&
      typeof stored.entries === "object"
    )
      return stored;
  } catch {
    /* Private browsers may refuse site data. */
  }
  return { identity, entries: {} };
}
export function cachedLeadData<T>(
  identity: string | null | undefined,
  key: string,
): T | null {
  if (!valid(identity) || typeof window === "undefined") return null;
  const entry = read(identity).entries[key];
  return entry && Date.now() - entry.at >= 0 && Date.now() - entry.at < MAX_AGE
    ? (entry.value as T)
    : null;
}
export function rememberLeadData(
  identity: string | null | undefined,
  key: string,
  value: unknown,
) {
  if (!valid(identity) || typeof window === "undefined") return;
  const store = read(identity);
  const entries = Object.entries(store.entries).filter(
    ([name, entry]) => name !== key && Date.now() - entry.at < MAX_AGE,
  );
  store.entries = Object.fromEntries([
    ...entries.slice(-(MAX_ENTRIES - 1)),
    [key, { at: Date.now(), value }],
  ]);
  try {
    localStorage.setItem(SLOT, JSON.stringify(store));
  } catch {
    /* The list still works without storage. */
  }
}

export type ListAsk = Parameters<typeof readLeads>[0];
export const listQuestion = (ask: ListAsk) =>
  JSON.stringify([
    ask.scope,
    ask.owner ?? null,
    ask.stage ?? null,
    ask.search?.trim() ?? "",
    ask.test ?? false,
    ask.pipeline ?? null,
    ask.more ?? null,
  ]);
export const cachedLeadPage = (
  identity: string | null | undefined,
  ask: ListAsk,
) => cachedLeadData<LeadPage>(identity, `list:${listQuestion(ask)}`);
const pending = new Map<string, Promise<LeadPage>>();
const warming = new Map<string, { at: number; request: Promise<LeadPage> }>();
/** Warm-up and mounted list share their first read. Callers ignore aborted results;
 * the read itself can finish for the other reader. Never share across identities. */
export function readFirstLeads(
  identity: string | null | undefined,
  ask: ListAsk,
  signal?: AbortSignal,
): Promise<LeadPage> {
  if (!valid(identity)) return readLeads(ask, signal);
  const key = JSON.stringify([identity, listQuestion(ask)]);
  const warmed = warming.get(key);
  if (warmed && Date.now() - warmed.at < 10_000) {
    const clear = () => {
      if (warming.get(key) === warmed) warming.delete(key);
    };
    void warmed.request.then(clear, clear);
    return warmed.request;
  }
  warming.delete(key);
  let request = pending.get(key);
  if (!request) {
    request = readLeads(ask).then((page) => {
      rememberLeadData(identity, `list:${listQuestion(ask)}`, page);
      return page;
    });
    pending.set(key, request);
    const clear = () => {
      if (pending.get(key) === request) pending.delete(key);
    };
    void request.then(clear, clear);
  }
  return request;
}

/** Keep a completed warm-up until the list mounts, so a fast API cannot create
 * a second first-page request behind the desk. */
export function preloadFirstLeads(
  identity: string | null | undefined,
  ask: ListAsk,
) {
  if (!valid(identity)) return;
  const key = JSON.stringify([identity, listQuestion(ask)]);
  if (warming.has(key)) return;
  const request = readFirstLeads(identity, ask);
  const entry = { at: Date.now(), request };
  warming.set(key, entry);
  while (warming.size > MAX_ENTRIES)
    warming.delete(warming.keys().next().value!);
  void request.catch(() => {
    if (warming.get(key) === entry) warming.delete(key);
  });
}

/** A device-kept first page with one moved lead applied: it leaves a stage
 * list it no longer fits; elsewhere it is the newer row. */
function keptPage(key: string, page: LeadPage, row: LeadRow): LeadPage {
  let list: unknown;
  let more: unknown;
  try {
    [, , list, , , , more] = JSON.parse(key.slice("list:".length)) as unknown[];
  } catch {
    return page;
  }
  const at = page.leads.findIndex((lead) => lead.lead_id === row.lead_id);
  if (at < 0 || page.leads[at].revision >= row.revision) return page;
  const leads =
    (typeof list !== "string" || inStageList(row, list)) &&
    inWorkView(row, more as ListMore | null)
      ? page.leads.map((lead, index) => (index === at ? row : lead))
      : page.leads.filter((_, index) => index !== at);
  return { ...page, leads };
}

// The person moved a lead (lead-moves.ts): first reads already asked are
// stale, and what this device keeps follows the move at once.
onLeadMoved((row, moves) => {
  warming.clear();
  pending.clear();
  if (typeof window === "undefined") return;
  try {
    const stored = JSON.parse(
      localStorage.getItem(SLOT) ?? "null",
    ) as Store | null;
    if (!stored?.entries || typeof stored.entries !== "object") return;
    let changed = false;
    for (const [key, entry] of Object.entries(stored.entries)) {
      const value = key.startsWith("list:")
        ? keptPage(key, entry.value as LeadPage, row)
        : key.startsWith("leads.desk:")
          ? deskWithMoves(entry.value as Desk, moves)
          : entry.value;
      if (value === entry.value) continue;
      stored.entries[key] = { ...entry, value };
      changed = true;
    }
    if (changed) localStorage.setItem(SLOT, JSON.stringify(stored));
  } catch {
    /* The list still works without storage. */
  }
});
