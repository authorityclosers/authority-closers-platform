/**
 * Addresses of the analysis section. Calls are the first kind of analysis:
 * /analysis/new starts one, /analysis/calls lists them and
 * /analysis/calls/<id> opens one. Embedded and preview hosts keep their query
 * links, so only the standalone app pages use these paths.
 */
export const NEW_ANALYSIS_PATH = "/analysis/new";
export const CALLS_PATH = "/analysis/calls";

const CALL_PATH =
  /^\/analysis\/calls\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/?$/i;

const APP_HOMES = new Set([
  "/",
  "/dashboard",
  "/analysis",
  NEW_ANALYSIS_PATH,
  CALLS_PATH,
]);

/** True for a standalone app page with no extra (preview or review) query. */
export function isAppHome(url: URL): boolean {
  return APP_HOMES.has(url.pathname) && url.search === "" && url.hash === "";
}

export function callPath(id: string): string {
  return `${CALLS_PATH}/${id}`;
}

export function callIdFromPath(pathname: string): string | null {
  return CALL_PATH.exec(pathname)?.[1] ?? null;
}
