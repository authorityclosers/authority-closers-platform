/**
 * A seller's changes stay on this device until the server confirms them
 * (owner, 24 Oct 2026, P0: "all data must go to server and saved immediately
 * ... instant sync should be the first of all"; a tester's after-call
 * results of 23 Oct never reached the server).
 *
 * - A change is stored before it is sent and removed only when the server
 *   says yes. localStorage, written synchronously before the request starts,
 *   so a closed app, a lost connection or a busy server can't drop it in
 *   between; it survives restarts and app updates (an uninstall clears it, as
 *   it clears anything kept on the phone).
 * - No connection, a timeout, a busy server (408, 425, 429, 5xx) or a lapsed
 *   sign-in (401): it waits and goes again (5 s, 15 s, 1 min, 5 min, then
 *   every 10 min), oldest first, and at once on reconnect, on return to the
 *   app, at the next start and after signing in again (write-sync.tsx).
 * - Each change keeps its command id, so the server applies it once however
 *   often it is sent. The same change asked for again while it waits reuses
 *   the waiting id instead of becoming a second change.
 * - A change sent again that the server now refuses (409: the lead changed
 *   meanwhile; other 4xx) is never forced through: it is kept as "needs a
 *   look" and shown, with its words, until the person opens the lead or
 *   closes it.
 * - Changes belong to the person and workspace that made them, and are only
 *   sent again for them; logging out keeps them for the next sign-in here.
 * - Only a seller's own entries wait (results, notes, stages, follow-ups,
 *   logged calls, new or edited leads, meetings). Settings, bulk changes,
 *   assigning and deleting fail visibly as before: sending them hours later
 *   could surprise someone.
 */

import { useSyncExternalStore } from "react";

const KEY = "sx-writes:v1";
const DAY_MS = 24 * 3600 * 1000;
/** Kept this long, then shown as needing a look rather than sent so late. */
export const WRITE_MAX_AGE_MS = 30 * DAY_MS;
export const WRITE_BACKOFF_MS = [
  5_000,
  15_000,
  60_000,
  5 * 60_000,
  10 * 60_000,
] as const;

export type WriteState = "waiting" | "check";

export type QueuedWrite = Readonly<{
  /** The command id: the server applies a command once. */
  id: string;
  identity: string;
  url: string;
  method: string;
  body: string;
  /** What it is, in words ("A call result"). */
  label: string;
  /** The lead it changes, when the address says. */
  lead: string | null;
  at: number;
  attempts: number;
  nextAt: number;
  state: WriteState;
  /** The last answer's status; 0 for no answer, null before any. */
  status: number | null;
}>;

export type WriteResult =
  | { kind: "sent"; response: Response }
  /** onDevice false: the phone's storage refused it; it waits only while the app runs. */
  | { kind: "kept"; onDevice: boolean }
  | { kind: "refused"; response: Response };

let identity: string | null = null;
/** False after the phone's storage refused the list (full, or blocked). */
let storageOk = true;
let cache: QueuedWrite[] | null = null;
let sending = false;
let savedAt = 0;
let snapshot: WritesSnapshot | null = null;
const listeners = new Set<() => void>();

function emit() {
  snapshot = null;
  listeners.forEach((listener) => listener());
}

const isWrite = (value: unknown): value is QueuedWrite => {
  const item = value as Partial<QueuedWrite> | null;
  return (
    !!item &&
    typeof item.id === "string" &&
    typeof item.identity === "string" &&
    typeof item.url === "string" &&
    typeof item.method === "string" &&
    typeof item.body === "string" &&
    typeof item.at === "number" &&
    typeof item.nextAt === "number" &&
    (item.state === "waiting" || item.state === "check")
  );
};

function items(): QueuedWrite[] {
  if (cache) return cache;
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    cache = Array.isArray(parsed) ? parsed.filter(isWrite) : [];
  } catch {
    cache = [];
  }
  return cache;
}

/** True when the list is safely on the device. */
function store(next: QueuedWrite[]): boolean {
  cache = next;
  let kept = true;
  try {
    if (next.length) window.localStorage.setItem(KEY, JSON.stringify(next));
    else window.localStorage.removeItem(KEY);
  } catch {
    kept = false;
  }
  storageOk = kept;
  emit();
  return kept;
}

function update(id: string, change: (item: QueuedWrite) => QueuedWrite) {
  store(items().map((item) => (item.id === id ? change(item) : item)));
}

function remove(id: string) {
  store(items().filter((item) => item.id !== id));
}

/** Who writes now ("person:workspace"); null while signed out. */
export function setWriteIdentity(next: string | null) {
  if (next === identity) return;
  identity = next;
  emit();
}

const COMMAND_KEYS = ["command_id", "commandId"] as const;

function parseBody(body: BodyInit | null | undefined) {
  if (typeof body !== "string") return null;
  try {
    const value: unknown = JSON.parse(body);
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function commandOf(body: Record<string, unknown>): string | null {
  for (const key of COMMAND_KEYS) {
    const value = body[key];
    if (typeof value === "string" && value) return value;
  }
  return null;
}

function withCommand(body: Record<string, unknown>, id: string) {
  const next = { ...body };
  for (const key of COMMAND_KEYS) if (key in next) next[key] = id;
  return next;
}

/** The body without its command id, keys in order: the same change compares equal. */
function essence(body: Record<string, unknown>): string {
  const keys = Object.keys(body)
    .filter((key) => !(COMMAND_KEYS as readonly string[]).includes(key))
    .sort();
  return JSON.stringify(keys.map((key) => [key, body[key]]));
}

const LEAD = /\/leads\/([0-9a-f-]{36})(?:\/|$)/i;

/** A seller's own entry, in words; null for a change that doesn't wait. */
export function writeLabel(method: string, url: string): string | null {
  const path = url.split("?")[0];
  if (method === "POST") {
    if (/\/leads\/[^/]+\/dispose$/.test(path)) return "A call result";
    if (/\/leads\/[^/]+\/notes$/.test(path)) return "A note";
    if (/\/leads\/[^/]+\/stage$/.test(path)) return "A stage change";
    if (/\/leads\/[^/]+\/follow-up$/.test(path)) return "A follow-up";
    if (/\/leads\/[^/]+\/calls\/phone$/.test(path)) return "A logged call";
    if (/\/leads\/[^/]+\/messages$/.test(path)) return "A message note";
    if (/\/leads\/[^/]+\/reopen$/.test(path)) return "A reopened lead";
    if (/\/leads\/[^/]+\/meetings$/.test(path)) return "A meeting";
    if (/\/meetings\/[^/]+\/(done|not-held)$/.test(path))
      return "A meeting result";
    if (/\/lead-desk\/leads$/.test(path)) return "A new lead";
  }
  if (method === "PATCH" && /\/lead-desk\/leads\/[^/]+$/.test(path))
    return "A lead's details";
  return null;
}

/** No answer, a timeout, a busy server, or a lapsed sign-in: send again later. */
const keepFor = (status: number) =>
  status === 0 ||
  status === 401 ||
  status === 408 ||
  status === 425 ||
  status === 429 ||
  status >= 500;

function later(id: string, status: number) {
  update(id, (item) => ({
    ...item,
    attempts: item.attempts + 1,
    status,
    nextAt:
      Date.now() +
      WRITE_BACKOFF_MS[Math.min(item.attempts, WRITE_BACKOFF_MS.length - 1)],
  }));
}

const JSON_HEADERS = {
  accept: "application/json",
  "content-type": "application/json",
};

/**
 * Send one write, keeping a seller's entry on this device until the server
 * says yes. "kept": it didn't arrive and waits to be sent again; "refused":
 * the server said no (the caller handles it as before). Anything that isn't
 * a seller's entry, or with nobody signed in, is simply sent.
 */
export async function sendWrite(
  url: string,
  init: RequestInit,
): Promise<WriteResult> {
  const method = (init.method ?? "GET").toUpperCase();
  const label = writeLabel(method, url);
  const parsed = label ? parseBody(init.body) : null;
  const command = parsed ? commandOf(parsed) : null;
  const who = identity;
  if (!label || !parsed || !command || !who) {
    const response = await fetch(url, init);
    return response.ok
      ? { kind: "sent", response }
      : { kind: "refused", response };
  }
  const same = essence(parsed);
  const twin = items().find(
    (item) =>
      item.identity === who &&
      item.url === url &&
      item.method === method &&
      item.state === "waiting" &&
      essence(parseBody(item.body) ?? {}) === same,
  );
  const id = twin?.id ?? command;
  const body = JSON.stringify(withCommand(parsed, id));
  const kept = store([
    ...items().filter((item) => item.id !== id),
    {
      id,
      identity: who,
      url,
      method,
      body,
      label,
      lead: LEAD.exec(url)?.[1] ?? null,
      at: twin?.at ?? Date.now(),
      attempts: twin?.attempts ?? 0,
      nextAt: Date.now(),
      state: "waiting",
      status: null,
    },
  ]);
  let response: Response;
  try {
    response = await fetch(url, { ...init, body });
  } catch {
    // Kept on the phone, or, when its storage refused, held while the app runs
    // (a corner card says so, with Try again): never dropped.
    later(id, 0);
    return { kind: "kept", onDevice: kept };
  }
  if (response.ok) {
    remove(id);
    savedAt = Date.now();
    emit();
    return { kind: "sent", response };
  }
  if (keepFor(response.status)) {
    later(id, response.status);
    return { kind: "kept", onDevice: kept };
  }
  remove(id);
  return { kind: "refused", response };
}

let replaying: Promise<void> | null = null;

/**
 * Send what waits for the person signed in now, oldest first; `force` sends
 * even what isn't due yet (Send now). A change that doesn't arrive stops the
 * round, so later changes never overtake it.
 */
export function replayWrites({ force = false } = {}): Promise<void> {
  const who = identity;
  if (!who || typeof window === "undefined") return Promise.resolve();
  if (replaying) return replaying;
  // Cleared after it settles, even when it ends without waiting on anything.
  replaying = (async () => {
    sending = true;
    emit();
    try {
      const due = items()
        .filter((item) => item.identity === who && item.state === "waiting")
        .sort((a, b) => a.at - b.at);
      for (const item of due) {
        if (Date.now() - item.at > WRITE_MAX_AGE_MS) {
          update(item.id, (old) => ({ ...old, state: "check" }));
          continue;
        }
        if (!force && item.nextAt > Date.now()) break;
        let response: Response;
        try {
          response = await fetch(item.url, {
            method: item.method,
            body: item.body,
            credentials: "same-origin",
            cache: "no-store",
            redirect: "error",
            headers: JSON_HEADERS,
          });
        } catch {
          later(item.id, 0);
          break;
        }
        if (response.ok) {
          remove(item.id);
          savedAt = Date.now();
          continue;
        }
        if (keepFor(response.status)) {
          later(item.id, response.status);
          break;
        }
        update(item.id, (old) => ({
          ...old,
          state: "check",
          status: response.status,
        }));
      }
    } finally {
      sending = false;
      emit();
    }
  })().finally(() => {
    replaying = null;
  });
  return replaying;
}

/** Try storing on the phone again (Try again), then send what waits. */
export function retryStorage(): Promise<void> {
  store(items());
  return replayWrites({ force: true });
}

/** The person closed a change that needs a look. */
export function discardWrite(id: string) {
  remove(id);
}

/** Changes of the person signed in now that the server hasn't confirmed. */
export function unsentWrites(): QueuedWrite[] {
  const who = identity;
  return who ? items().filter((item) => item.identity === who) : [];
}

/** The words a person typed into a change, to show when it needs a look. */
export function writtenWords(item: QueuedWrite): string | null {
  const body = parseBody(item.body);
  for (const key of ["remark", "note", "notes", "text"]) {
    const value = body?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

/**
 * Before logging out: true to go ahead. With changes still waiting, the
 * person is asked; they stay on this phone either way and go when this
 * person signs in here again. Staying signed in sends them now.
 */
export function confirmLogOutWithUnsent(): boolean {
  const waiting = unsentWrites().filter((item) => item.state === "waiting");
  if (!waiting.length) return true;
  const what = [...new Set(waiting.map((item) => item.label.toLowerCase()))];
  const count =
    waiting.length === 1
      ? "1 change isn't"
      : `${waiting.length} changes aren't`;
  const sure = window.confirm(
    `${count} on Sales X-Ray yet (${what.join(", ")}). Stay signed in and ${
      waiting.length === 1 ? "it goes" : "they go"
    } as soon as Sales X-Ray answers. If you log out, ${
      waiting.length === 1 ? "it stays" : "they stay"
    } on this phone and ${
      waiting.length === 1 ? "goes" : "go"
    } when you sign in here again. Log out anyway?`,
  );
  if (!sure) void replayWrites({ force: true });
  return sure;
}

export type WritesSnapshot = Readonly<{
  waiting: number;
  check: readonly QueuedWrite[];
  sending: boolean;
  /** When the next waiting change is due; 0 with none. */
  nextAt: number;
  /** A waiting change needs the person signed in again. */
  signIn: boolean;
  /** The phone's storage refused the changes: they wait only while the app runs. */
  storageFull: boolean;
  /** When the oldest unsent change was made; 0 with none. */
  oldestAt: number;
  savedAt: number;
}>;

const NONE: WritesSnapshot = {
  waiting: 0,
  check: [],
  sending: false,
  nextAt: 0,
  signIn: false,
  storageFull: false,
  oldestAt: 0,
  savedAt: 0,
};

function read(): WritesSnapshot {
  if (snapshot) return snapshot;
  const mine = unsentWrites();
  const waiting = mine.filter((item) => item.state === "waiting");
  snapshot = {
    waiting: waiting.length,
    check: mine.filter((item) => item.state === "check"),
    sending,
    nextAt: waiting.length
      ? Math.min(...waiting.map((item) => item.nextAt))
      : 0,
    signIn: waiting.some((item) => item.status === 401),
    storageFull: !storageOk && mine.length > 0,
    oldestAt: mine.length ? Math.min(...mine.map((item) => item.at)) : 0,
    savedAt,
  };
  return snapshot;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key !== KEY) return;
    cache = null;
    emit();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** The same, outside React (tests). */
export const writesNow = () => read();

/** What waits, what needs a look, and whether a send is under way. */
export function useWrites(): WritesSnapshot {
  return useSyncExternalStore(subscribe, read, () => NONE);
}

/** For tests: forget everything. */
export function resetWrites() {
  cache = null;
  snapshot = null;
  identity = null;
  storageOk = true;
  sending = false;
  savedAt = 0;
  replaying = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Nothing kept.
  }
}
