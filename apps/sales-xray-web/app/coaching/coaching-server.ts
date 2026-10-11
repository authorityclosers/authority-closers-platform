import { headers } from "next/headers";
import { readCoaching, type CoachingResult } from "./coaching-read";

/**
 * Fixed deployment origin only. No shared cache, cookie logging or redirects.
 * The server read is a head start, not the authority: if it fails (an older
 * or misrouted API, a bad origin, a network error), it returns null and the
 * browser makes the one read itself.
 */
export async function loadServerCoaching(
  callId: string | null,
): Promise<CoachingResult | null> {
  const configured = process.env.AC_CONVERSATION_API_ORIGIN;
  // A local preview without an API keeps the authenticated client read path.
  if (!configured) return null;
  try {
    const origin = new URL(configured);
    if (
      !["http:", "https:"].includes(origin.protocol) ||
      origin.username ||
      origin.password ||
      origin.pathname !== "/" ||
      origin.search ||
      origin.hash
    )
      return null;
    const incoming = await headers();
    const host = incoming.get("host") ?? "";
    if (!/^[a-z0-9.-]+(?::[0-9]+)?$/i.test(host)) return null;
    const result = await readCoaching(
      callId,
      {
        headers: { Cookie: incoming.get("cookie") ?? "", Host: host },
      },
      origin.origin,
    );
    return result.data ? result : null;
  } catch {
    return null;
  }
}
