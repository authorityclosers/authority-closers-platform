/**
 * What a bug report may carry from this device (owner, 23 Oct 2026).
 *
 * The device scrubs before it sends and the server scrubs again
 * (ac_platform/bug_reports/scrub.py): no secrets, sign-in codes, contact
 * details, transcripts or call content. Free text is cut short; anything
 * shaped like a token, key, email address or phone number becomes a marker.
 */

const REDACTIONS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\beyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]{6,}/g, "[token]"],
  [/\bbearer\s+[\w.~+/=-]{8,}/gi, "Bearer [token]"],
  [/\b(?:ac_(?:live|test)|sk|pk|rk|whsec|AIza)[\w-]{10,}/g, "[key]"],
  [
    /\b(?:password|passwd|secret|token|otp|cookie|api[_-]?key)\s*[:=]\s*\S+/gi,
    "[secret]",
  ],
  [/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, "[email]"],
  [/\b[A-Za-z0-9+/_-]{40,}={0,2}/g, "[long]"],
  [/(?<![\w-])\+?\d(?:[\s().-]?\d){8,}(?![\w-])/g, "[phone]"],
];

// An id in a route (a UUID, a number, or a long opaque part with a digit) becomes ":id",
// so a route is the screen's pattern (#15, 26 Oct 2026; the server's _ID_PART).
const ID_PART =
  /^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9]+|(?=[A-Za-z_-]*[0-9])[A-Za-z0-9_-]{16,})$/i;

// Secrets only, for the screen's picture (dev #2, 26 Oct 2026): tokens, keys and
// long opaque strings; the rest of what a person reads stays as it is.
const SECRETS: ReadonlyArray<readonly [RegExp, string]> = [
  ...REDACTIONS.filter(
    ([, marker]) =>
      marker !== "[email]" && marker !== "[phone]" && marker !== "[long]",
  ),
  [/\b[A-Za-z0-9_-]{40,}={0,2}/g, "[long]"],
];

/** Text with tokens, keys and long opaque strings masked (for the screen's picture). */
export function maskSecrets(text: string): string {
  let out = text;
  for (const [pattern, marker] of SECRETS) out = out.replace(pattern, marker);
  return out;
}

const SECRET_KEY =
  /token|code|key|secret|password|state|auth|session|email|phone|mobile|signature|sig/i;

/** One line of plain text, redacted and cut to `limit` characters. */
export function scrubText(value: unknown, limit: number): string {
  if (typeof value !== "string") return "";
  let text = value.replace(/\s+/g, " ").trim();
  for (const [pattern, marker] of REDACTIONS) {
    text = text.replace(pattern, marker);
  }
  return text.slice(0, limit);
}

/** One part of a route: an id becomes ":id", anything else is scrubbed like text. */
function routePart(value: string, limit: number): string {
  return ID_PART.test(value) ? ":id" : scrubText(value, limit);
}

/** Keeps the markers readable: ":id", "[email]". */
function encodePart(value: string): string {
  return encodeURIComponent(value)
    .replace(/%3A/gi, ":")
    .replace(/%5B/gi, "[")
    .replace(/%5D/gi, "]");
}

/**
 * A route's pattern: ids become ":id", secret-looking query values are dropped,
 * each part is scrubbed on its own (a redaction never spans a "/"), and there
 * is no fragment.
 */
export function scrubRoute(value: unknown, limit = 512): string {
  if (typeof value !== "string" || !value.trim()) return "/";
  let url: URL;
  try {
    url = new URL(value, "https://app.invalid");
  } catch {
    return "/";
  }
  const path = url.pathname
    .split("/")
    .map((part) => routePart(part, 80))
    .join("/");
  const pairs: string[] = [];
  url.searchParams.forEach((val, key) => {
    if (pairs.length >= 12) return;
    const kept = SECRET_KEY.test(key) ? "" : routePart(val, 80);
    pairs.push(`${encodePart(scrubText(key, 40))}=${encodePart(kept)}`);
  });
  return (
    (path + (pairs.length ? `?${pairs.join("&")}` : "")).slice(0, limit) || "/"
  );
}
