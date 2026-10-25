/**
 * ChatGPT app directory domain verification: OpenAI's portal shows a token, and
 * https://salesxray.authorityclosers.com/.well-known/openai-apps-challenge must answer
 * with it as plain text (side notes, developer-platform-listings-20261024.md, gap 3).
 *
 * The token is public by design (anyone can read it at that address), so it is
 * configuration, not a secret:
 * - PRODUCTION_CHALLENGE is the production domain's token: paste it here when the
 *   portal shows it. Only the production host answers with it.
 * - AC_OPENAI_APPS_CHALLENGE, when the web server has it, answers on any Sales X-Ray
 *   host (a dev or staging rehearsal of the portal's check).
 * With neither, the address is a plain 404.
 */

/** The production domain's token from OpenAI's portal; empty until it shows one. */
export const PRODUCTION_CHALLENGE = "";
export const PRODUCTION_HOST = "salesxray.authorityclosers.com";

// What a portal token looks like: one printable word, no spaces or markup.
const TOKEN = /^[A-Za-z0-9._~+/=-]{8,512}$/;

/** The token this host should answer with, or null for a 404. ``host`` is the bare
 * host the request reached (publicOrigin has already kept other sites out). */
export function challengeToken(
  host: string,
  configured: string | undefined,
): string | null {
  const fromConfig = configured?.trim() ?? "";
  if (TOKEN.test(fromConfig)) return fromConfig;
  if (host === PRODUCTION_HOST && TOKEN.test(PRODUCTION_CHALLENGE))
    return PRODUCTION_CHALLENGE;
  return null;
}

export function challengeAnswer(token: string) {
  return new Response(token, {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
