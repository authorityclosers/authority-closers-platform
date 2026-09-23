import { REF, UUID, sections, states, type Selection, type Section, type StateId } from "./core.js";
export const viewports = [
  [320, 720], [375, 667], [390, 844], [768, 1024], [1024, 626], [1440, 900],
] as const;
const targets = ["report.section", "report.reader.close", "processing.details", "audio.play"] as const;
export type Command =
  | { type: "select"; selection: Selection }
  | { type: "reset" | "forget" | "return-live" }
  | { type: "viewport"; width: number; height: number }
  | { type: "motion"; value: "system" | "reduce" }
  | { type: "focus" | "hover"; target: (typeof targets)[number] };
function fail(): never { throw new Error("invalid-review-command"); }
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return fail();
  return value as Record<string, unknown>;
}
function exact(value: Record<string, unknown>, allowed: string[]): void {
  if (Object.keys(value).some(k => !allowed.includes(k))) fail();
}
const isRef = (x: unknown): x is string => typeof x === "string" && REF.test(x);
const frameRef = (x: unknown): x is string => typeof x === "string" && /^f-[0-9]{1,10}-[0-9]{1,16}-[a-f0-9]{16}$/.test(x);
/** JSON validation is separate from execution and conveys no server authority. */
export function parseSelection(value: unknown): Selection {
  const v = record(value);
  if (v.mode === "live") { exact(v, ["mode"]); return { mode: "live" }; }
  if (v.mode !== "observed" && v.mode !== "presentation") return fail();
  exact(v, v.mode === "observed" ? ["mode", "frameId", "expectedState"] :
    ["mode", "frameId", "expectedState", "section", "reader", "observationAgeMs"]);
  if (!frameRef(v.frameId)) return fail();
  if (v.expectedState !== undefined && !(states as readonly unknown[]).includes(v.expectedState)) return fail();
  const base = { mode: v.mode, frameId: v.frameId,
    ...(v.expectedState === undefined ? {} : { expectedState: v.expectedState as StateId }) };
  if (v.mode === "observed") return { ...base, mode: "observed" };
  if (v.section !== undefined && !(sections as readonly unknown[]).includes(v.section)) return fail();
  if (v.reader !== undefined && v.reader !== null && !isRef(v.reader)) return fail();
  if (v.observationAgeMs !== undefined && (!Number.isSafeInteger(v.observationAgeMs) ||
    (v.observationAgeMs as number) < 0 || (v.observationAgeMs as number) > 1_800_000)) return fail();
  return { ...base, mode: "presentation",
    ...(v.section === undefined ? {} : { section: v.section as Section }),
    ...(v.reader === undefined ? {} : { reader: v.reader as string | null }),
    ...(v.observationAgeMs === undefined ? {} : { observationAgeMs: v.observationAgeMs as number }),
  };
}
export function parseCommand(text: string): Command {
  if (typeof text !== "string" || text.length > 4096 || new TextEncoder().encode(text).length > 4096) return fail();
  let raw: unknown; try { raw = JSON.parse(text); } catch { return fail(); }
  const v = record(raw);
  if (v.type === "select") { exact(v, ["type", "selection"]); return { type: "select", selection: parseSelection(v.selection) }; }
  if (v.type === "reset" || v.type === "forget" || v.type === "return-live") {
    exact(v, ["type"]); return { type: v.type };
  }
  if (v.type === "viewport") {
    exact(v, ["type", "width", "height"]);
    if (!viewports.some(([w, h]) => v.width === w && v.height === h)) return fail();
    return { type: "viewport", width: v.width as number, height: v.height as number };
  }
  if (v.type === "motion") {
    exact(v, ["type", "value"]); if (v.value !== "system" && v.value !== "reduce") return fail();
    return { type: "motion", value: v.value };
  }
  if (v.type === "focus" || v.type === "hover") {
    exact(v, ["type", "target"]); if (!(targets as readonly unknown[]).includes(v.target)) return fail();
    return { type: v.type, target: v.target as (typeof targets)[number] };
  }
  return fail();
}
/** Relative navigation grammar only. Fragments select display references, never HTTP destinations. */
export function parseReviewAddress(text: string): { call: string; section: Section; selection: Selection } {
  if (typeof text !== "string" || text.length > 1024 || !text.startsWith("/") || text.startsWith("//") || /[\\\s]/.test(text)) return fail();
  if (!["/", "/sales-xray"].includes(text.split(/[?#]/, 1)[0]!)) return fail();
  const url = new URL(text, "http://review.invalid");
  if (url.origin !== "http://review.invalid" || !["/", "/sales-xray"].includes(url.pathname)) return fail();
  const q = url.searchParams;
  if ([...q.keys()].some(k => !["call", "section"].includes(k)) || q.getAll("call").length !== 1 || q.getAll("section").length > 1 || !UUID.test(q.get("call")!)) return fail();
  const section = q.get("section") ?? "overview";
  if (!(sections as readonly string[]).includes(section)) return fail();
  if (!url.hash) return { call: q.get("call")!, section: section as Section, selection: { mode: "live" } };
  const h = new URLSearchParams(url.hash.slice(1));
  if ([...h.keys()].some(k => !["sx-review", "mode", "frame", "reader", "state"].includes(k)) ||
    [...h.keys()].some(k => h.getAll(k).length !== 1) || h.get("sx-review") !== "v1") return fail();
  const mode = h.get("mode");
  if (mode !== "observed" && mode !== "presentation") return fail();
  if (mode === "observed" && h.has("reader")) return fail();
  const selection = parseSelection({ mode, frameId: h.get("frame"),
    ...(h.has("state") ? { expectedState: h.get("state") } : {}),
    ...(mode === "presentation" ? { section, ...(h.has("reader") ? { reader: h.get("reader") } : {}) } : {}),
  });
  return { call: q.get("call")!, section: section as Section, selection };
}
/** Standalone policy model only, NOT a replacement for the real bridge's tested policy. */
export function reviewRequestAllowed(method: string, path: string, selectedCall: string): boolean {
  if (!UUID.test(selectedCall) || typeof path !== "string" || /[?#%\\]/.test(path)) return false;
  if (method === "POST") return ["/v1/auth/password/login", "/v1/auth/logout", "/v1/context"].includes(path);
  if (method !== "GET") return false;
  return ["/v1/me/workspaces", "/v1/conversation/acquisition/session", "/v1/conversation/acquisition/entry",
    "/v1/conversation/acquisition/upload-policy", "/v1/conversation/acquisition/availability",
    ...["", "/plan", "/report", "/transcript"].map(s => `/v1/conversation/acquisition/submissions/${selectedCall}${s}`)].includes(path);
}
/** Non-executing FIFO. Local transport authenticates each enqueue before calling it. */
export class CommandQueue {
  #items: Command[] = [];
  enqueue(text: string): void {
    if (this.#items.length >= 16) throw new Error("review-command-queue-full");
    this.#items.push(parseCommand(text));
  }
  take(): Command | undefined { return this.#items.shift(); }
  clear(): void { this.#items.length = 0; }
  get size(): number { return this.#items.length; }
}
