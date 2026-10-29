import { headers } from "next/headers";
import {
  SERVER_READ_BUDGET_MS,
  serverApiOrigin,
  serverFetch,
} from "../server-reads";
import { readCoaching, type CoachingResult } from "./coaching-read";

/**
 * Fixed deployment origin only. No shared cache, cookie logging or redirects.
 * The server read is a head start, not the authority: if it fails (an older
 * or misrouted API, a bad origin, a network error) or takes longer than the
 * read budget, it returns null and the browser makes the one read itself. It
 * goes through serverFetch, so the API sees this page's own host (with
 * fetch() it saw its own address and refused the read).
 */
export async function loadServerCoaching(
  callId: string | null,
): Promise<CoachingResult | null> {
  // A local preview without an API keeps the authenticated client read path.
  const origin = serverApiOrigin();
  if (!origin) return null;
  try {
    const incoming = await headers();
    // Full page loads only, as every server read (server-reads.ts).
    const destination = incoming.get("sec-fetch-dest");
    if (destination && destination !== "document") return null;
    const host = incoming.get("host") ?? "";
    const cookie = incoming.get("cookie");
    if (!cookie || !/^[a-z0-9.-]+(?::[0-9]+)?$/i.test(host)) return null;
    const result = await readCoaching(
      callId,
      {
        headers: { Cookie: cookie, Host: host },
        signal: AbortSignal.timeout(SERVER_READ_BUDGET_MS),
      },
      origin,
      serverFetch,
    );
    return result.data ? result : null;
  } catch {
    return null;
  }
}
