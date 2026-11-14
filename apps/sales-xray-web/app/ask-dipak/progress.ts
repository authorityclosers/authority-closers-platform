/**
 * Your saved lessons and Next-call missions, kept on your account (spec
 * sections 20, 22, 23 and 31): the same on every phone and computer you sign
 * in on, and separate for every person. The 13 Nov 2026 meeting's "one thing
 * tracked" is the missions marked done, countable per lesson for Growth.
 * Marking a mission is the seller's own word; it is never proof a call went
 * that way, and nothing here scores it.
 *
 * GET /v1/sales-xray/ask-dipak/progress
 * PUT /v1/sales-xray/ask-dipak/progress/{question_id}  {item, on}
 *     Both answer {saved: [ids], missions: [ids]}.
 */
import { useSyncExternalStore } from "react";

export const PROGRESS_PATH = "/v1/sales-xray/ask-dipak/progress";

export type ProgressItem = "saved" | "mission";

export type Progress = Readonly<{
  /** loading until the account's answer arrives; failed if it couldn't be read. */
  status: "idle" | "loading" | "ready" | "failed";
  saved: ReadonlySet<string>;
  missions: ReadonlySet<string>;
}>;

const EMPTY: Progress = {
  status: "idle",
  saved: new Set(),
  missions: new Set(),
};

let state: Progress = EMPTY;
let reading: Promise<void> | null = null;
/** Only the newest write's answer is taken, so quick taps never flip back. */
let writes = 0;
/** Whose progress this is: another person signing in starts afresh. */
let person: string | null = null;
const listeners = new Set<() => void>();

function set(next: Progress) {
  state = next;
  listeners.forEach((listener) => listener());
}

const ids = (value: unknown): Set<string> =>
  new Set(
    Array.isArray(value)
      ? value.filter(
          (item): item is string =>
            typeof item === "string" && /^[A-Za-z0-9-]{1,16}$/.test(item),
        )
      : [],
  );

export function parseProgress(
  raw: unknown,
): Pick<Progress, "saved" | "missions"> | null {
  if (typeof raw !== "object" || raw === null) return null;
  const body = raw as Record<string, unknown>;
  if (!Array.isArray(body.saved) || !Array.isArray(body.missions)) return null;
  return { saved: ids(body.saved), missions: ids(body.missions) };
}

async function request(
  path: string,
  init: RequestInit,
): Promise<Pick<Progress, "saved" | "missions">> {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    ...init,
    headers: { accept: "application/json", ...init.headers },
  });
  if (!response.ok) throw new Error(`Progress answered ${response.status}`);
  const parsed = parseProgress(await response.json());
  if (!parsed) throw new Error("Progress answer was not understood");
  return parsed;
}

/** Reads the account's progress once per visit (again after a failure). */
export function loadProgress(): Promise<void> {
  if (state.status === "ready") return Promise.resolve();
  if (reading) return reading;
  set({ ...state, status: "loading" });
  const started = writes;
  reading = request(PROGRESS_PATH, { method: "GET" })
    .then(
      (answer) => {
        // A tap made while reading wins over the older read.
        if (writes === started) set({ status: "ready", ...answer });
        else set({ ...state, status: "ready" });
      },
      () => set({ ...state, status: "failed" }),
    )
    .finally(() => {
      reading = null;
    });
  return reading;
}

/**
 * Saves or clears one item. The screen changes at once; the account's answer
 * then stands, and if the write fails the change is taken back.
 */
export async function setItem(
  questionId: string,
  item: ProgressItem,
  on: boolean,
): Promise<boolean> {
  const key = item === "saved" ? "saved" : "missions";
  const before = state[key];
  const next = new Set(before);
  if (on) next.add(questionId);
  else next.delete(questionId);
  set({ ...state, [key]: next });
  const mine = ++writes;
  try {
    const answer = await request(
      `${PROGRESS_PATH}/${encodeURIComponent(questionId)}`,
      {
        method: "PUT",
        body: JSON.stringify({ item, on }),
        headers: { "content-type": "application/json" },
      },
    );
    if (mine === writes) set({ status: "ready", ...answer });
    return true;
  } catch {
    if (mine === writes) {
      const back = new Set(state[key]);
      if (before.has(questionId)) back.add(questionId);
      else back.delete(questionId);
      set({ ...state, [key]: back });
    }
    return false;
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const read = () => state;
/** The progress as it stands, outside React (tests). */
export const progressNow = (): Progress => state;
const readServer = () => EMPTY;

export function useProgress(): Progress {
  return useSyncExternalStore(subscribe, read, readServer);
}

/** For tests and sign-out: forget this visit's progress. */
export function resetProgress() {
  state = EMPTY;
  reading = null;
  writes = 0;
  person = null;
  listeners.forEach((listener) => listener());
}

/** Another person signed in on this screen: their own progress, never the last one's. */
export function progressFor(personId: string) {
  if (person !== null && person !== personId) resetProgress();
  person = personId;
  void loadProgress();
}
