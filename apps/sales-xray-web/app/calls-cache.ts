/**
 * What each signed-in identity (person, session, workspace) has already
 * read, kept for the life of the tab (design system v2; orchestrator, 20
 * Oct: Home read the calls list Calls had read 4 s before, and Calls read
 * every row's report on every visit).
 *
 * - The calls list's first page: Calls and Home paint from it at once and
 *   refresh it quietly (stale while revalidating).
 * - Home's panels (summary, activity, time left, recent calls), the same way.
 * - Each call's insight from its report: read once, not on every visit.
 *
 * Memory only: nothing goes to the browser's storage, a full reload starts
 * empty, and an identity never sees another's answers (the key carries the
 * person, the session and the workspace). A few identities at most are kept.
 */
import {
  acquisition,
  parseSubmissionLibraryPage,
  type SubmissionLibraryPage,
} from "./acquisition-client";

/** The Calls list's first read (and Home's, with owners). */
export const CALLS_LIST_READ =
  "/submissions?include_owners=true&order=reports_first";

const MAX_IDENTITIES = 4;

type Shelf = {
  page?: SubmissionLibraryPage;
  panels: Record<string, unknown>;
  insights: Map<string, unknown>;
};
const shelves = new Map<string, Shelf>();

/** The cache key for a signed-in context, or null without one. */
export function identityOf(
  context:
    | { personId: string; sessionId: string; tenantId: string }
    | null
    | undefined,
): string | null {
  return context
    ? JSON.stringify([context.personId, context.sessionId, context.tenantId])
    : null;
}

const isIdentity = (key: string | null | undefined): key is string =>
  typeof key === "string" && key.startsWith("[");

function shelf(identity: string): Shelf {
  let found = shelves.get(identity);
  if (found) {
    // Most recently used last, so the oldest goes first.
    shelves.delete(identity);
  } else {
    found = { panels: {}, insights: new Map() };
  }
  shelves.set(identity, found);
  while (shelves.size > MAX_IDENTITIES) {
    const oldest = shelves.keys().next().value;
    if (oldest === undefined) break;
    shelves.delete(oldest);
  }
  return found;
}

export function cachedCallsPage(
  identity: string | null | undefined,
): SubmissionLibraryPage | null {
  if (!isIdentity(identity)) return null;
  return shelves.get(identity)?.page ?? null;
}

export function rememberCallsPage(
  identity: string | null | undefined,
  page: SubmissionLibraryPage,
) {
  if (isIdentity(identity)) shelf(identity).page = page;
}

/** Home's panels, by name, as their last ready read states. */
export function cachedPanel<T>(
  identity: string | null | undefined,
  name: string,
): T | undefined {
  if (!isIdentity(identity)) return undefined;
  return shelves.get(identity)?.panels[name] as T | undefined;
}

export function rememberPanel(
  identity: string | null | undefined,
  name: string,
  value: unknown,
) {
  if (isIdentity(identity)) shelf(identity).panels[name] = value;
}

/** The identity's insight shelf (a fresh one without an identity). */
export function insightShelf<T>(
  identity: string | null | undefined,
): Map<string, T> {
  if (!isIdentity(identity)) return new Map<string, T>();
  return shelf(identity).insights as Map<string, T>;
}

/** Forget everything (sign out, or a test between cases). */
export function forgetCalls() {
  shelves.clear();
}

const warming = new Set<string>();

/**
 * Reads the calls list once for an identity that has none yet, when the app
 * is quiet, so Calls and Home open with their rows. A failure is silent: the
 * page reads for itself as before.
 */
export async function warmCallsList(identity: string | null | undefined) {
  if (
    !isIdentity(identity) ||
    cachedCallsPage(identity) ||
    warming.has(identity)
  )
    return;
  warming.add(identity);
  try {
    const page = parseSubmissionLibraryPage(await acquisition(CALLS_LIST_READ));
    if (!cachedCallsPage(identity)) rememberCallsPage(identity, page);
  } catch {
    // Only a head start; the page reads for itself.
  } finally {
    warming.delete(identity);
  }
}
