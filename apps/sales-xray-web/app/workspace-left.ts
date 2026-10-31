/**
 * A workspace the person is no longer in (orchestrator, 1 Nov 2026): someone
 * removed them, or the organisation was deleted, while their session still
 * named it. The server answers such a session without a workspace instead of
 * refusing it, and names the one left in two headers until the person lands
 * somewhere else; the page then moves to another workspace or the picker and
 * says so calmly, never a bare "tenant context denied".
 */

export const LEFT_HEADER = "x-ac-workspace-left";
export const LEFT_NAME_HEADER = "x-ac-workspace-left-name";

export type LeftWorkspace = Readonly<{ tenantId: string; name: string | null }>;

/** The workspace an answer says the person left, or null. */
export function leftWorkspace(response: Response): LeftWorkspace | null {
  const tenantId = response.headers.get(LEFT_HEADER)?.trim();
  if (!tenantId) return null;
  let name: string | null = null;
  try {
    name = decodeURIComponent(response.headers.get(LEFT_NAME_HEADER) ?? "");
  } catch {
    // A name that can't be read is left out; the note still shows.
  }
  return { tenantId, name: name?.trim() || null };
}

/** The corner note's title. */
export function leftWorkspaceTitle(left: LeftWorkspace): string {
  return left.name
    ? `You're no longer in ${left.name}`
    : "You're no longer in that workspace";
}

type Listener = (left: LeftWorkspace) => void;

const listeners = new Set<Listener>();
let watching: typeof fetch | null = null;

/**
 * Hear every answer that names a workspace left, from any read or write on
 * the page. The page's fetch is wrapped once (again only if something
 * replaced it); the answer itself passes through untouched.
 */
export function onWorkspaceLeft(listener: Listener): () => void {
  listeners.add(listener);
  if (typeof globalThis.fetch === "function" && globalThis.fetch !== watching) {
    const original = globalThis.fetch;
    const watched = (async (...request: Parameters<typeof fetch>) => {
      const response = await original(...request);
      try {
        const left = leftWorkspace(response);
        if (left) for (const heard of [...listeners]) heard(left);
      } catch {
        // Watching never changes what the page receives.
      }
      return response;
    }) as typeof fetch;
    watching = watched;
    globalThis.fetch = watched;
  }
  return () => {
    listeners.delete(listener);
  };
}
