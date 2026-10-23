/**
 * The last twenty problems this page met, kept in memory for a bug report.
 *
 * Script errors, unhandled rejections, console errors and the error corner
 * cards people saw. Each entry is scrubbed when it is recorded (scrub.ts):
 * the message's first line, where it came from, the request reference. Never
 * request or response bodies, never console arguments other than text. It
 * lives only in this tab and leaves the device only inside a report the
 * person chose to send.
 */

import { scrubRoute, scrubText } from "./scrub";

export type RecentError = Readonly<{
  at: string;
  kind: "error" | "rejection" | "console" | "notice" | "http";
  message?: string;
  source?: string;
  reference?: string;
  status?: number;
  method?: string;
  path?: string;
}>;

const LIMIT = 20;
let entries: RecentError[] = [];

/** Keep one problem (scrubbed), dropping the oldest past twenty. */
export function recordError(
  entry: Omit<RecentError, "at"> & { at?: string },
): void {
  const clean: RecentError = {
    at: entry.at ?? new Date().toISOString(),
    kind: entry.kind,
    ...(entry.message ? { message: scrubText(entry.message, 300) } : {}),
    ...(entry.source ? { source: scrubText(entry.source, 200) } : {}),
    ...(entry.reference && /^[A-Za-z0-9_.:-]{4,64}$/.test(entry.reference)
      ? { reference: entry.reference }
      : {}),
    ...(typeof entry.status === "number" ? { status: entry.status } : {}),
    ...(entry.method ? { method: entry.method.toUpperCase() } : {}),
    ...(entry.path ? { path: scrubRoute(entry.path, 200) } : {}),
  };
  const last = entries.at(-1);
  // A loop repeating one failure keeps one entry, not twenty copies of it.
  if (
    last &&
    last.kind === clean.kind &&
    last.message === clean.message &&
    last.source === clean.source
  ) {
    entries[entries.length - 1] = clean;
    return;
  }
  entries = [...entries, clean].slice(-LIMIT);
}

/** The problems so far, oldest first. */
export function recentErrors(): readonly RecentError[] {
  return entries;
}

/** For tests. */
export function clearRecentErrors(): void {
  entries = [];
}

function describe(reason: unknown): string {
  if (reason instanceof Error) return `${reason.name}: ${reason.message}`;
  if (typeof reason === "string") return reason;
  return "Unknown problem";
}

let installed = false;

/**
 * Listen for script errors, rejections and console errors once per page.
 * Console arguments other than text are never read.
 */
export function installErrorRecorder(): () => void {
  if (installed || typeof window === "undefined") return () => {};
  installed = true;
  const onError = (event: ErrorEvent) => {
    if (!event.error && !event.message) return;
    recordError({
      kind: "error",
      message: event.error ? describe(event.error) : event.message,
      // A script's path, line and column; never its query.
      source: event.filename
        ? `${scrubRoute(event.filename, 160).split("?")[0]}:${event.lineno}:${event.colno}`
        : undefined,
    });
  };
  const onRejection = (event: PromiseRejectionEvent) => {
    const reason = event.reason as { name?: string } | null;
    if (reason?.name === "AbortError") return;
    recordError({ kind: "rejection", message: describe(event.reason) });
  };
  const original = console.error;
  const patched = (...args: unknown[]) => {
    const first = args.find(
      (arg) => typeof arg === "string" || arg instanceof Error,
    );
    if (first !== undefined) {
      recordError({ kind: "console", message: describe(first) });
    }
    original.apply(console, args);
  };
  console.error = patched;
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  return () => {
    installed = false;
    if (console.error === patched) console.error = original;
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}
