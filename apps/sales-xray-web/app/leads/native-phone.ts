/**
 * The Sales Xray phone app's channel, when this page runs inside the app.
 *
 * The Android app injects an origin-restricted "SXPhone" object into Sales
 * Xray pages. Through it the lead screen places the call itself, hears when
 * the call ends (connected or not, and for how long, from the phone's call
 * history) and gets the phone's own recording of that call. In a browser none
 * of this exists: Call stays a tel: link and the seller answers by hand.
 */

export type NativeRecording = {
  source: string;
  name: string;
  size: number;
  durationMs: number;
  ext: string;
  mime: string;
  supported: boolean;
};

export type NativeCallResult =
  | "answered"
  | "no_answer"
  | "busy"
  | "rejected"
  | "failed"
  | "unknown";

export type NativeCall = {
  leadId: string;
  number: string;
  startedMs: number;
  endedMs: number | null;
  durationSeconds: number | null;
  connected: boolean | null;
  result: NativeCallResult;
  recording: NativeRecording | null;
  /** False while the phone may still be writing the recording. */
  final: boolean;
};

export type NativeStatus = {
  platform: string;
  version: string;
  /** The app can place calls and read their result. */
  calling: boolean;
  callAccess: boolean;
  audio: boolean;
};

type Channel = {
  postMessage: (data: string) => void;
  addEventListener: (
    type: "message",
    listener: (event: { data: unknown }) => void,
  ) => void;
};

type Reply = { id?: string; ok?: boolean; result?: unknown; error?: string };

function channel(): Channel | null {
  const found = (globalThis as { SXPhone?: Partial<Channel> }).SXPhone;
  return found &&
    typeof found.postMessage === "function" &&
    typeof found.addEventListener === "function"
    ? (found as Channel)
    : null;
}

/** True only inside the Sales Xray phone app. */
export function inPhoneApp(): boolean {
  return channel() !== null;
}

const waiting = new Map<
  string,
  { resolve: (value: unknown) => void; reject: (error: Error) => void }
>();
const callListeners = new Set<(call: NativeCall) => void>();
let listening: Channel | null = null;
let counter = 0;

function listen(target: Channel): void {
  if (listening === target) return;
  listening = target;
  target.addEventListener("message", (event) => {
    let message: Reply & { event?: string; call?: unknown };
    try {
      message = JSON.parse(String(event.data)) as typeof message;
    } catch {
      return;
    }
    if (message.event === "call") {
      const call = parseCall(message.call);
      if (call) callListeners.forEach((listener) => listener(call));
      return;
    }
    const waiter = message.id ? waiting.get(message.id) : undefined;
    if (!waiter || !message.id) return;
    waiting.delete(message.id);
    if (message.ok) waiter.resolve(message.result);
    else waiter.reject(new Error(message.error ?? "phone_error"));
  });
}

function ask<T>(
  method: string,
  args: Record<string, unknown> = {},
  timeoutMs = 20_000,
): Promise<T> {
  const target = channel();
  if (!target) return Promise.reject(new Error("no_phone_app"));
  listen(target);
  const id = `w${++counter}`;
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      waiting.delete(id);
      reject(new Error("phone_timeout"));
    }, timeoutMs);
    waiting.set(id, {
      resolve: (value) => {
        clearTimeout(timer);
        resolve(value as T);
      },
      reject: (error) => {
        clearTimeout(timer);
        reject(error);
      },
    });
    target.postMessage(JSON.stringify({ id, method, args }));
  });
}

const text = (value: unknown) => (typeof value === "string" ? value : "");
const count = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;

export function parseRecording(raw: unknown): NativeRecording | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (!text(value.source) || !text(value.name)) return null;
  return {
    source: text(value.source),
    name: text(value.name),
    size: count(value.size),
    durationMs: count(value.durationMs),
    ext: text(value.ext),
    mime: text(value.mime) || "audio/mpeg",
    supported: value.supported !== false,
  };
}

const RESULTS = new Set<NativeCallResult>([
  "answered",
  "no_answer",
  "busy",
  "rejected",
  "failed",
  "unknown",
]);

export function parseCall(raw: unknown): NativeCall | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (!text(value.leadId)) return null;
  const result = RESULTS.has(value.result as NativeCallResult)
    ? (value.result as NativeCallResult)
    : "unknown";
  const seconds =
    typeof value.durationSeconds === "number" && value.durationSeconds >= 0
      ? Math.round(value.durationSeconds)
      : null;
  return {
    leadId: text(value.leadId),
    number: text(value.number),
    startedMs: count(value.startedMs),
    endedMs: typeof value.endedMs === "number" ? value.endedMs : null,
    durationSeconds: seconds,
    connected: typeof value.connected === "boolean" ? value.connected : null,
    result,
    recording: parseRecording(value.recording),
    final: value.final === true,
  };
}

export async function phoneStatus(): Promise<NativeStatus | null> {
  if (!inPhoneApp()) return null;
  try {
    const raw = await ask<Record<string, unknown>>("status", {}, 5_000);
    return {
      platform: text(raw.platform),
      version: text(raw.version),
      calling: raw.calling === true,
      callAccess: raw.callAccess === true,
      audio: raw.audio === true,
    };
  } catch {
    return null;
  }
}

/** Asks the phone for call, call-history and recordings access in one go. */
export async function askCallAccess(): Promise<boolean> {
  const raw = await ask<Record<string, unknown>>(
    "requestCallAccess",
    {},
    120_000,
  );
  return raw.callAccess === true;
}

/** Places the call from the app; it reports back when the call ends. */
export async function startPhoneCall(lead: {
  leadId: string;
  number: string;
  name: string;
}): Promise<void> {
  await ask("call", lead);
}

/** The lead's last call from this phone, when it has ended. */
export async function readLastCall(leadId: string): Promise<NativeCall | null> {
  if (!inPhoneApp()) return null;
  try {
    return parseCall(await ask("lastCall", { leadId }, 8_000));
  } catch {
    return null;
  }
}

/** Marks the call as handled, so it isn't offered again. */
export async function forgetCall(leadId: string): Promise<void> {
  if (!inPhoneApp()) return;
  await ask("forgetCall", { leadId }, 5_000).catch(() => undefined);
}

export function onPhoneCall(listener: (call: NativeCall) => void): () => void {
  const target = channel();
  if (!target) return () => undefined;
  listen(target);
  callListeners.add(listener);
  return () => {
    callListeners.delete(listener);
  };
}

function decode(base64: string): Uint8Array<ArrayBuffer> {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/** The phone's recording as a file, read in pieces through the channel. */
export async function readPhoneRecording(
  recording: NativeRecording,
  onProgress?: (bytes: number) => void,
): Promise<File> {
  const parts: Uint8Array<ArrayBuffer>[] = [];
  let offset = 0;
  for (;;) {
    const piece = await ask<{ data?: string; eof?: boolean }>("read", {
      source: recording.source,
      offset,
    });
    const bytes = decode(piece.data ?? "");
    parts.push(bytes);
    offset += bytes.length;
    onProgress?.(offset);
    if (piece.eof || bytes.length === 0) break;
  }
  return new File(parts, recording.name, { type: recording.mime });
}

/** The "Didn't get through" reason that matches what the phone saw. */
export function missedReason(result: NativeCallResult): string | null {
  switch (result) {
    case "no_answer":
      return "did_not_pick";
    case "busy":
      return "busy";
    case "rejected":
      return "disconnected";
    case "failed":
      return "not_connected";
    default:
      return null;
  }
}

/**
 * A light buzz, as an app gives on a long-press, a swipe or a save. Inside the
 * phone app the app does it (no vibration permission needed); in a phone
 * browser the page asks the browser; elsewhere nothing happens.
 */
export function buzz(kind: "tick" | "press" | "done" = "tick"): void {
  if (inPhoneApp()) {
    void ask("haptic", { kind }, 2_000).catch(() => undefined);
    return;
  }
  try {
    navigator.vibrate?.(kind === "press" ? 18 : 10);
  } catch {
    // Not allowed here: no buzz.
  }
}

export type PushState = {
  /** This app build can receive lead alerts. */
  supported: boolean;
  /** The phone allows Sales Xray notifications. */
  allowed: boolean;
  /** The phone's alert address, once alerts are on. */
  token: string | null;
};

/** What the phone app says about lead alerts; null in a browser or an older app. */
export async function pushStatus(): Promise<PushState | null> {
  if (!inPhoneApp()) return null;
  try {
    const raw = await ask<Record<string, unknown>>("pushStatus", {}, 5_000);
    return {
      supported: raw.supported === true,
      allowed: raw.allowed === true,
      token: typeof raw.token === "string" && raw.token ? raw.token : null,
    };
  } catch {
    return null;
  }
}

/**
 * Turns lead alerts on: the phone asks to allow notifications (once), starts
 * Firebase with the client settings Sales Xray sent, and returns its address.
 */
export async function pushEnable(config: {
  project_id: string;
  app_id: string;
  api_key: string;
  sender_id: string;
}): Promise<PushState | null> {
  try {
    const raw = await ask<Record<string, unknown>>(
      "pushEnable",
      config,
      120_000,
    );
    return {
      supported: raw.supported === true,
      allowed: raw.allowed === true,
      token: typeof raw.token === "string" && raw.token ? raw.token : null,
    };
  } catch {
    return null;
  }
}

/**
 * Signals from the phone app: "resume" when it comes back to the front,
 * "alert" when a lead alert arrives while it is open. Older apps send none;
 * the page also listens for the browser's own visibility change.
 */
export function onPhoneSignal(listener: (event: string) => void): () => void {
  const handle = (event: Event) => {
    const detail = (event as CustomEvent<{ event?: unknown }>).detail;
    if (typeof detail?.event === "string") listener(detail.event);
  };
  window.addEventListener("sx-phone", handle);
  return () => window.removeEventListener("sx-phone", handle);
}
