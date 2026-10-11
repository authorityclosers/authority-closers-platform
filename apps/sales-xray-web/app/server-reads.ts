import { headers } from "next/headers";

import { serverDisplayDates as displayDatesFor } from "./display-dates";
import type { DisplayDates } from "./display-dates";

/**
 * Server-side reads (owner, 11 Oct: "server-side data like Pulse").
 *
 * Where the deployment gives this web server the internal API origin
 * (`AC_CONVERSATION_API_ORIGIN`, as on dev; Coaching's coaching-server.ts
 * reads the same way), a page can ask the API for its data while it renders,
 * with the request's own cookie, and arrive whole. Elsewhere (no origin, a
 * static preview, no cookie, a slow API) every helper returns null and the
 * page reads in the browser as before.
 *
 * Only exact GET paths chosen by the code; never a URL, origin, header or
 * credential from the request beyond its cookie and host.
 */

export type ServerRead = { status: number; body: unknown } | null;

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

const HOST = /^[a-z0-9.-]+(?::[0-9]+)?$/i;

/**
 * GET each path on the API as this request (its cookie and host), together,
 * within `timeoutMs`. Null when server reads are off, the request is not a
 * full page load or has no session cookie; a single read that fails or times
 * out is null in the map.
 */
export async function serverReads(
  paths: readonly string[],
  timeoutMs = 1000,
): Promise<Record<string, ServerRead> | null> {
  const origin = serverApiOrigin();
  if (!origin) return null;
  const incoming = await headers();
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
        const response = await fetch(`${origin}${path}`, {
          method: "GET",
          headers: { accept: "application/json", cookie, host },
          cache: "no-store",
          redirect: "error",
          signal,
        });
        const json = response.headers
          .get("content-type")
          ?.includes("application/json");
        return [
          path,
          {
            status: response.status,
            body: json ? await response.json().catch(() => null) : null,
          },
        ];
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
