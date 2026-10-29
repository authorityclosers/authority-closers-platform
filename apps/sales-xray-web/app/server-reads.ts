import { headers } from "next/headers";

import { serverDisplayDates as displayDatesFor } from "./display-dates";
import { serverGet } from "./server-get";
import type { DisplayDates } from "./display-dates";

/**
 * Server-side reads (owner, 11 Oct: "server-side data like Pulse").
 *
 * Where the deployment gives this web server the internal API origin
 * (`AC_CONVERSATION_API_ORIGIN`: dev; staging and production from their
 * source profiles, infra/sales-xray-web/environments), a page can ask the API
 * for its data while it renders, with the request's own cookie, and arrive
 * whole. Elsewhere (no origin, a static preview, no cookie, an API slower
 * than SERVER_READ_BUDGET_MS) every helper returns null and the page reads in
 * the browser as before. Such pages are private: next.config.ts sends them
 * with Cache-Control private, no-store.
 *
 * Only exact GET paths chosen by the code; never a URL, origin, header or
 * credential from the request beyond its cookie and host.
 */

export type ServerRead = { status: number; body: unknown } | null;

/**
 * The longest a page waits for its server reads; then it renders without
 * them and the browser reads as before (orchestrator, 29 Oct 2026).
 */
export const SERVER_READ_BUDGET_MS = 800;

/** The configured internal API origin, or null (no server reads here). */
export function serverApiOrigin(
  env: Readonly<Record<string, string | undefined>> = process.env,
): string | null {
  if (env.AC_SALES_XRAY_STATIC_PREVIEW === "1") return null;
  const configured = env.AC_CONVERSATION_API_ORIGIN;
  if (!configured) return null;
  try {
    const url = new URL(configured);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    )
      return null;
    return url.origin;
  } catch {
    return null;
  }
}

/**
 * Whether this build's pages render for each request and read on the
 * server: an origin (dev), or AC_SALES_XRAY_SERVER_READS=1 when the image is
 * built (infra/sales-xray-web/Dockerfile: one image runs in staging and
 * production, each with its own origin at run time). Never the static preview.
 */
export function serverReadsBuilt(
  env: Readonly<Record<string, string | undefined>> = process.env,
): boolean {
  if (env.AC_SALES_XRAY_STATIC_PREVIEW === "1") return false;
  return (
    env.AC_SALES_XRAY_SERVER_READS === "1" || serverApiOrigin(env) !== null
  );
}

const HOST = /^[a-z0-9.-]+(?::[0-9]+)?$/i;

/**
 * GET each path on the API as this request (its cookie and host), together,
 * within `timeoutMs`. Null when server reads are off, the request is not a
 * full page load or has no session cookie; a single read that fails or times
 * out is null in the map.
 */
export async function serverReads(
  paths: readonly string[],
  timeoutMs = SERVER_READ_BUDGET_MS,
): Promise<Record<string, ServerRead> | null> {
  if (!serverReadsBuilt()) return null;
  // Asking for the request marks the page as rendered per request when it is
  // built; the origin then decides at run time, so clearing it switches the
  // reads off without a new build.
  const incoming = await headers();
  const origin = serverApiOrigin();
  if (!origin) return null;
  // Full page loads only. An in-app navigation reads in the browser, fresh:
  // Next may reuse a navigation's server payload for 30 s (`staleTimes`), and
  // it should not wait for reads here. (Next hides its own navigation header
  // from pages; the browser's Fetch Metadata names the document request.)
  const destination = incoming.get("sec-fetch-dest");
  if (destination && destination !== "document") return null;
  const cookie = incoming.get("cookie");
  const host = incoming.get("host") ?? "";
  if (!cookie || !HOST.test(host)) return null;
  const signal = AbortSignal.timeout(timeoutMs);
  const entries = await Promise.all(
    paths.map(async (path): Promise<[string, ServerRead]> => {
      try {
        // serverGet, not fetch(): fetch drops the host header (server-get.ts).
        const answer = await serverGet(
          `${origin}${path}`,
          { accept: "application/json", cookie, host },
          signal,
        );
        let body: unknown = null;
        if (answer.contentType?.includes("application/json"))
          try {
            body = JSON.parse(answer.text);
          } catch {
            body = null;
          }
        return [path, { status: answer.status, body }];
      } catch {
        return [path, null];
      }
    }),
  );
  return Object.fromEntries(entries);
}

/** The two session reads the app's own session check makes (exact paths). */
export const SESSION_PATHS = [
  "/v1/me/workspaces",
  "/v1/me/sales-xray-workspaces",
] as const;

export type InitialSession = Readonly<{
  identity: unknown;
  directory: unknown;
}>;

/**
 * The signed-in session as the browser's check would read it, for the app
 * session to start "ready" on pages that render their data on the server.
 * Null unless both reads succeeded.
 */
export async function serverSession(): Promise<InitialSession | null> {
  // Every full page load waits for this (the layout), so a slow API costs
  // at most 0.6 s before the page falls back to the browser's own check.
  const reads = await serverReads(SESSION_PATHS, 600);
  const identity = reads?.[SESSION_PATHS[0]];
  const directory = reads?.[SESSION_PATHS[1]];
  if (identity?.status !== 200 || directory?.status !== 200) return null;
  return { identity: identity.body, directory: directory.body };
}

/**
 * How pages drawn here write dates: the language this request asked for, in
 * India time (display-dates.ts). Null where the server draws no data.
 */
export async function serverDisplayDates(): Promise<DisplayDates | null> {
  if (!serverApiOrigin()) return null;
  const incoming = await headers();
  return displayDatesFor(incoming.get("accept-language"));
}

/**
 * fetch() for a server read that wants a Response (coaching-read.ts): a GET
 * through serverGet, so the API sees this page's Host. fetch() would send the
 * API's own address, and the API refuses that host.
 */
export async function serverFetch(
  url: string,
  init: RequestInit = {},
): Promise<Response> {
  const sent: Record<string, string> = {};
  // Header names are case-insensitive; one spelling whatever Headers keeps.
  new Headers(init.headers).forEach((value, key) => {
    sent[key.toLowerCase()] = value;
  });
  const answer = await serverGet(
    url,
    sent,
    init.signal ?? AbortSignal.timeout(SERVER_READ_BUDGET_MS),
  );
  const empty = [204, 205, 304].includes(answer.status);
  return new Response(empty ? null : answer.text, {
    status: answer.status,
    headers: answer.contentType ? { "content-type": answer.contentType } : {},
  });
}
