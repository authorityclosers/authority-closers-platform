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
  /** No SIM, no service or airplane mode when the call was placed. */
  | "no_network"
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
  "no_network",
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
    case "no_network":
      return "out_of_coverage";
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

export type CallLogSim = { id: string; label: string };

/** A work call with a number that isn't a lead yet; it stays on the phone unless saved. */
export type UnknownCall = {
  number: string;
  lastMs: number;
  direction: "outgoing" | "incoming" | "missed";
  seconds: number;
  count: number;
};

export function parseUnknown(raw: unknown): UnknownCall[] {
  const items =
    raw && typeof raw === "object"
      ? (raw as { items?: unknown }).items
      : undefined;
  if (!Array.isArray(items)) return [];
  return items.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const value = item as Record<string, unknown>;
    const direction = text(value.direction);
    if (
      !text(value.number) ||
      !["outgoing", "incoming", "missed"].includes(direction)
    )
      return [];
    return [
      {
        number: text(value.number),
        lastMs: count(value.lastMs),
        direction: direction as UnknownCall["direction"],
        seconds: count(value.seconds),
        count: Math.max(1, count(value.count)),
      },
    ];
  });
}

/** Work calls with numbers that aren't leads, newest first; [] in a browser or older app. */
export async function unknownCalls(): Promise<UnknownCall[]> {
  if (!inPhoneApp()) return [];
  try {
    return parseUnknown(await ask("unknownCalls", {}, 5_000));
  } catch {
    return [];
  }
}

/** "Not a lead": the phone stops offering this number. */
export async function ignoreNumber(number: string): Promise<UnknownCall[]> {
  try {
    return parseUnknown(await ask("ignoreNumber", { number }, 5_000));
  } catch {
    return [];
  }
}

/** Saved as a lead: the phone drops it from the list. */
export async function forgetUnknown(number: string): Promise<void> {
  await ask("forgetUnknown", { number }, 5_000).catch(() => undefined);
}

/** Work calls the phone logs by itself (UX study item 5). */
export type CallLogStatus = {
  on: boolean;
  /** The phone lets Sales Xray read its call history. */
  access: boolean;
  sims: CallLogSim[];
  /** The work SIM; "" means every SIM. */
  sim: string;
  lastSyncMs: number | null;
  lastLogged: number;
  /** How the last look went: ok, never, no_access, signed_out, offline or error. */
  state: string;
};

export function parseCallLog(raw: unknown): CallLogStatus | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (typeof value.on !== "boolean") return null;
  const sims = Array.isArray(value.sims)
    ? value.sims.flatMap((item) => {
        if (!item || typeof item !== "object") return [];
        const sim = item as Record<string, unknown>;
        return text(sim.id)
          ? [{ id: text(sim.id), label: text(sim.label) }]
          : [];
      })
    : [];
  return {
    on: value.on,
    access: value.access === true,
    sims,
    sim: text(value.sim),
    lastSyncMs:
      typeof value.lastSyncMs === "number" && value.lastSyncMs > 0
        ? value.lastSyncMs
        : null,
    lastLogged: count(value.lastLogged),
    state: text(value.state) || "never",
  };
}

/** What the phone app says about logging work calls; null in a browser or an older app. */
export async function callLogStatus(): Promise<CallLogStatus | null> {
  if (!inPhoneApp()) return null;
  try {
    return parseCallLog(await ask("callLogStatus", {}, 5_000));
  } catch {
    return null;
  }
}

/** Turns call logging on or off for a work SIM; the phone asks for call-history access once. */
export async function callLogSetup(
  on: boolean,
  sim: string,
): Promise<CallLogStatus | null> {
  try {
    return parseCallLog(await ask("callLogSetup", { on, sim }, 120_000));
  } catch {
    return null;
  }
}

/** Looks at the call history now (the app also does when it opens and every 15 minutes). */
export async function callLogSyncNow(): Promise<CallLogStatus | null> {
  try {
    return parseCallLog(await ask("callLogSync", {}, 60_000));
  } catch {
    return null;
  }
}

/** The phone setup checklist as the phone sees it (UX study item 7). */
export type SetupStatus = {
  checks: Record<string, boolean>;
  /** xiaomi, samsung, vivo, oppo, realme, oneplus, huawei or other. */
  family: string;
  model: string;
  /** This brand stops apps unless Autostart is allowed. */
  autostartNeeded: boolean;
  version: string;
  /** This install's own id, the same one call logging uses. */
  device: string;
  /** Which dialer records, where it saves, and whether it's on (app 0.3.40+). */
  recorder: RecorderProfile | null;
};

/** This phone's call recorder as the app sees it (owner, 19 Oct: check, don't ask). */
export type RecorderProfile = {
  /** "folder": the maker's dialer saves files Sales Xray reads; "private": Google's Phone app; "unknown". */
  kind: "folder" | "private" | "unknown";
  maker: string;
  dialerLabel: string;
  /** "on", "off", "unknown", or "private" (Google's Phone app). */
  recording: string;
  folders: { path: string; state: string; recordings: number }[];
  /** Another installed Phone app that saves recordings to a folder, if any. */
  switchTo: string | null;
};

export function parseRecorder(raw: unknown): RecorderProfile | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  const kind = value.kind;
  if (kind !== "folder" && kind !== "private" && kind !== "unknown")
    return null;
  const folders = Array.isArray(value.folders)
    ? value.folders
        .filter(
          (row): row is Record<string, unknown> =>
            !!row && typeof row === "object",
        )
        .map((row) => ({
          path: text(row.path),
          state: text(row.state),
          recordings: typeof row.recordings === "number" ? row.recordings : 0,
        }))
        .filter((row) => row.path)
    : [];
  const others = Array.isArray(value.otherDialers) ? value.otherDialers : [];
  const maker = others.find(
    (row): row is Record<string, unknown> =>
      !!row &&
      typeof row === "object" &&
      (row as Record<string, unknown>).savesToFolder === true,
  );
  return {
    kind,
    maker: text(value.maker) || "other",
    dialerLabel: text(value.dialerLabel) || "your Phone app",
    recording: text(value.recording) || "unknown",
    folders,
    switchTo: maker ? text(maker.label) || null : null,
  };
}

export function parseSetup(raw: unknown): SetupStatus | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (!value.checks || typeof value.checks !== "object") return null;
  const checks: Record<string, boolean> = {};
  for (const [key, on] of Object.entries(value.checks as object))
    if (typeof on === "boolean") checks[key] = on;
  return {
    checks,
    family: text(value.family) || "other",
    model: text(value.model),
    autostartNeeded: value.autostartNeeded === true,
    version: text(value.version),
    device: text(value.device),
    recorder: parseRecorder(value.recorderProfile),
  };
}

/** The checklist; null in a browser or in an app without it. */
export async function setupStatus(): Promise<SetupStatus | null> {
  if (!inPhoneApp()) return null;
  try {
    return parseSetup(await ask("setupStatus", {}, 10_000));
  } catch {
    return null;
  }
}

/** Opens the phone screen that fixes a line: battery, autostart, recorder or notifications. */
export async function setupOpen(what: string): Promise<boolean> {
  try {
    const raw = await ask<{ opened?: boolean }>("setupOpen", { what }, 10_000);
    return raw.opened === true;
  } catch {
    return false;
  }
}

/** Opens a recorder screen: "settings" (call recording) or "defaultDialer" (choose the Phone app). */
export async function recorderOpen(
  what: "settings" | "defaultDialer",
): Promise<boolean> {
  try {
    const raw = await ask<{ opened?: boolean }>(
      "recorderOpen",
      { what },
      10_000,
    );
    return raw.opened === true;
  } catch {
    return false;
  }
}

/** The seller ticks what the phone can't tell: "recorder" or "autostart". */
export async function setupMark(
  what: string,
  done: boolean,
): Promise<SetupStatus | null> {
  try {
    return parseSetup(await ask("setupMark", { what, done }, 10_000));
  } catch {
    return null;
  }
}

/** Asks Android for notifications alone (older phones open the settings). */
export async function askNotifications(): Promise<SetupStatus | null> {
  try {
    return parseSetup(await ask("requestNotifications", {}, 120_000));
  } catch {
    return null;
  }
}

/** Asks Android to let Sales Xray read the phone's call recordings. */
export async function askRecordingAccess(): Promise<boolean> {
  try {
    const raw = await ask<Record<string, unknown>>(
      "requestAccess",
      {},
      120_000,
    );
    return raw.audio === true;
  } catch {
    return false;
  }
}

/**
 * Signals from the phone app: "resume" when it comes back to the front,
 * "alert" when a lead alert arrives while it is open, "calls" when it logged
 * new work calls. Older apps send none; the page also listens for the
 * browser's own visibility change.
 */
export function onPhoneSignal(listener: (event: string) => void): () => void {
  const handle = (event: Event) => {
    const detail = (event as CustomEvent<{ event?: unknown }>).detail;
    if (typeof detail?.event === "string") listener(detail.event);
  };
  window.addEventListener("sx-phone", handle);
  return () => window.removeEventListener("sx-phone", handle);
}
