import { headers } from "next/headers";
import { readCoaching, type CoachingResult } from "./coaching-read";

/** Fixed deployment origin only. No shared cache, cookie logging or redirects. */
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
      return {
        data: null,
        error: "Coaching is temporarily unavailable. Try again.",
      };
    const incoming = await headers();
    const host = incoming.get("host") ?? "";
    if (!/^[a-z0-9.-]+(?::[0-9]+)?$/i.test(host))
      return {
        data: null,
        error: "Coaching is temporarily unavailable. Try again.",
      };
    return readCoaching(
      callId,
      {
        headers: { Cookie: incoming.get("cookie") ?? "", Host: host },
      },
      origin.origin,
    );
  } catch {
    return {
      data: null,
      error: "Coaching is temporarily unavailable. Try again.",
    };
  }
}
