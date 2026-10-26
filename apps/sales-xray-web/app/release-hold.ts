/**
 * Updates without broken screens (owner, 27 Oct 2026: "updates breaking things mid-use").
 *
 * For the two minutes or so of a production release, the edge answers every request with
 * 503, text/plain, `X-Authority-Closers-Route: release-hold-production` and
 * `Retry-After: 30`. Such a request never reached the app, so sending it again is always
 * safe for the server; what may change is only what the person sees. One fetch layer,
 * installed once for the whole app (release-hold-banner.tsx), handles it:
 * - a calm banner says Sales X-Ray is updating while the hold lasts;
 * - reads, and writes that carry an idempotency key, are sent again on their own (2, 4,
 *   8, then every 15 seconds, for up to about 3 minutes), so the screen just waits;
 * - any other write a person just made is kept, with its words still on screen, until
 *   they press Retry (or Not now, which hands the caller the answer it would have had);
 * - background requests (telemetry, keepalive) are left to their own retries.
 */

export const HOLD_ROUTE = "release-hold";
/** How long a read waits out a release before the caller sees the answer itself. */
export const HOLD_WAIT_MS = 3 * 60_000;
/** Waits between tries: quick at first, then every 15 seconds. */
export const HOLD_DELAYS_MS = [2_000, 4_000, 8_000, 15_000] as const;
/** While a release lasts with nothing else asking, the app checks this often. */
export const HOLD_PROBE_MS = 10_000;

/** The edge's release hold: its route header, or a 503 plain-text answer with Retry-After. */
export function isReleaseHold(response: Response): boolean {
  if (response.status !== 503) return false;
  const route = response.headers.get("x-authority-closers-route") ?? "";
  if (route.startsWith(HOLD_ROUTE)) return true;
  const type = response.headers.get("content-type") ?? "";
  return response.headers.has("retry-after") && type.startsWith("text/plain");
}

/** The wait before try `attempt` + 1 (0-based). */
export function holdDelay(attempt: number): number {
  return HOLD_DELAYS_MS[Math.min(attempt, HOLD_DELAYS_MS.length - 1)]!;
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "PUT", "DELETE"]);
const KEY_HEADERS = ["idempotency-key", "x-idempotency-key"];
const KEY_FIELDS = ["command_id", "request_id", "idempotency_key"];

/**
 * May this request be sent again without asking? Reads and HTTP's idempotent methods,
 * and a write that carries its own key: an Idempotency-Key header, or a JSON body with a
 * command_id, request_id or idempotency_key (the server applies each once).
 */
export function retrySafe(
  method: string,
  headers: Headers,
  body: BodyInit | null | undefined,
): boolean {
  if (SAFE_METHODS.has(method.toUpperCase())) return true;
  if (KEY_HEADERS.some((name) => headers.get(name))) return true;
  if (typeof body !== "string" || body.length > 1_000_000) return false;
  try {
    const parsed: unknown = JSON.parse(body);
    return (
      parsed !== null &&
      typeof parsed === "object" &&
      !Array.isArray(parsed) &&
      KEY_FIELDS.some((field) => {
        const value = (parsed as Record<string, unknown>)[field];
        return typeof value === "string" && value.length > 0;
      })
    );
  } catch {
    return false;
  }
}

// ----- what the banner shows ------------------------------------------------------------

export type HoldState = Readonly<{
  /** The last answer from the app was a release hold. */
  holding: boolean;
  /** Writes kept for the person to send again. */
  kept: number;
}>;

type Kept = { send: () => void; drop: () => void };

let state: HoldState = { holding: false, kept: 0 };
const kept: Kept[] = [];
const listeners = new Set<() => void>();
let probe: ReturnType<typeof setTimeout> | null = null;
let probeFetch: typeof fetch | null = null;

function set(holding: boolean) {
  const next = { holding, kept: kept.length };
  if (next.holding === state.holding && next.kept === state.kept) return;
  state = next;
  for (const listener of listeners) listener();
  if (holding) startProbe();
}

/** The app answered normally again. */
function settled() {
  if (probe) clearTimeout(probe);
  probe = null;
  set(false);
}

/** While the release lasts, one quiet check every 10 seconds notices its end. */
function startProbe() {
  if (probe || !probeFetch) return;
  const check = probeFetch;
  probe = setTimeout(async () => {
    probe = null;
    try {
      const answer = await check(`/favicon.ico?hold=${Date.now()}`, {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (isReleaseHold(answer)) startProbe();
      else settled();
    } catch {
      startProbe();
    }
  }, HOLD_PROBE_MS);
}

export function holdState(): HoldState {
  return state;
}

export function subscribeHold(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Retry: sends every kept write again, oldest first. */
export function sendKept() {
  for (const item of kept.splice(0)) item.send();
  set(state.holding);
}

/** Not now: each kept write's caller gets the answer it would have had. */
export function dropKept() {
  for (const item of kept.splice(0)) item.drop();
  set(state.holding);
}

/** For tests: back to no hold and nothing kept. */
export function resetHold() {
  kept.splice(0);
  if (probe) clearTimeout(probe);
  probe = null;
  probeFetch = null;
  state = { holding: false, kept: 0 };
  for (const listener of listeners) listener();
}

// ----- the fetch layer ------------------------------------------------------------------

export type HoldDeps = {
  /** Waits, or rejects when the signal aborts. */
  sleep: (ms: number, signal?: AbortSignal | null) => Promise<void>;
  now: () => number;
  /** Did the person just act (a tap or a key), so a write is theirs? */
  byPerson: () => boolean;
  origin: () => string;
};

function abortError(): DOMException {
  return new DOMException("The request was cancelled.", "AbortError");
}

export const browserDeps: HoldDeps = {
  sleep: (ms, signal) =>
    new Promise((resolve, reject) => {
      if (signal?.aborted) return reject(abortError());
      const timer = setTimeout(() => {
        signal?.removeEventListener("abort", cancel);
        resolve();
      }, ms);
      const cancel = () => {
        clearTimeout(timer);
        reject(abortError());
      };
      signal?.addEventListener("abort", cancel, { once: true });
    }),
  now: () => Date.now(),
  byPerson: () =>
    (navigator as Navigator & { userActivation?: { isActive: boolean } })
      .userActivation?.isActive ?? true,
  origin: () => window.location.origin,
};

const BACKGROUND = /^\/v1\/telemetry\//;

/** The fetch the whole app uses: `base` with release holds waited out (see the top). */
export function holdingFetch(
  base: typeof fetch,
  deps: HoldDeps = browserDeps,
): typeof fetch {
  probeFetch = base;
  const holding: typeof fetch = async (input, init) => {
    const url = new URL(
      input instanceof Request ? input.url : String(input),
      deps.origin(),
    );
    if (url.origin !== deps.origin()) return base(input, init);
    const pristine = input instanceof Request ? input.clone() : null;
    const again = (): [RequestInfo | URL, RequestInit | undefined] => [
      pristine ? pristine.clone() : input,
      init,
    ];
    const method = (
      init?.method ?? (input instanceof Request ? input.method : "GET")
    ).toUpperCase();
    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined),
    );
    const body = init?.body;
    const signal =
      init?.signal ?? (input instanceof Request ? input.signal : null);
    const byPerson = deps.byPerson();

    let response = await base(input, init);
    if (!isReleaseHold(response)) {
      if (state.holding) settled();
      return response;
    }
    set(true);
    // A stream body can't be sent twice; a background write keeps its own retries.
    if (body instanceof ReadableStream) return response;
    if (retrySafe(method, headers, body)) {
      const started = deps.now();
      for (let attempt = 0; ; attempt++) {
        const delay = holdDelay(attempt);
        if (deps.now() - started + delay > HOLD_WAIT_MS) return response;
        await deps.sleep(delay, signal);
        response = await base(...again());
        if (!isReleaseHold(response)) {
          settled();
          return response;
        }
      }
    }
    if (!byPerson || init?.keepalive || BACKGROUND.test(url.pathname))
      return response;
    // A write the person just made: kept until they press Retry or Not now.
    const held = response;
    return new Promise<Response>((resolve, reject) => {
      const item: Kept = {
        send: () => {
          signal?.removeEventListener("abort", cancel);
          holding(...again()).then(resolve, reject);
        },
        drop: () => {
          signal?.removeEventListener("abort", cancel);
          resolve(held);
        },
      };
      const cancel = () => {
        const at = kept.indexOf(item);
        if (at >= 0) kept.splice(at, 1);
        set(state.holding);
        reject(abortError());
      };
      signal?.addEventListener("abort", cancel, { once: true });
      kept.push(item);
      set(true);
    });
  };
  return holding;
}

const INSTALLED = Symbol.for("sx.release-hold");

/** Puts the layer in front of the page's fetch, once (the banner's module does it). */
export function installReleaseHoldFetch(): void {
  if (typeof window === "undefined") return;
  const current = window.fetch as typeof fetch & { [INSTALLED]?: true };
  if (current[INSTALLED]) return;
  const wrapped = holdingFetch(current.bind(window)) as typeof fetch & {
    [INSTALLED]?: true;
  };
  wrapped[INSTALLED] = true;
  window.fetch = wrapped;
}
