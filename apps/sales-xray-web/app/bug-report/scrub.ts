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

/** A route's path and query, with secret-looking values dropped and no fragment. */
export function scrubRoute(value: unknown, limit = 512): string {
  if (typeof value !== "string" || !value.trim()) return "/";
  let url: URL;
  try {
    url = new URL(value, "https://app.invalid");
  } catch {
    return "/";
  }
  const query = new URLSearchParams();
  let kept = 0;
  url.searchParams.forEach((val, key) => {
    if (kept >= 12) return;
    kept += 1;
    query.append(key, SECRET_KEY.test(key) ? "" : val);
  });
  const search = query.toString();
  return scrubText(url.pathname + (search ? `?${search}` : ""), limit) || "/";
}
