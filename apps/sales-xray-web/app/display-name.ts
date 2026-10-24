/**
 * Names with capitals (owner, 22 Oct 2026: "Swamini Deshpande", not
 * "swamini deshpande"): people, sellers and leads alike, on every screen.
 *
 * Display only: what was saved stays as typed, and edits send only the
 * fields a person changed, so showing a name never rewrites it. A name typed
 * in mixed case ("McDonald", "de Souza") is shown as typed; only names in
 * one case change. Emails and numbers that stand in for a name stay as they
 * are.
 */

const WORD_START = /(^|[\s\-'’.(])(\p{L})/gu;

export function displayName(raw: string): string {
  const name = raw.trim().replace(/\s+/g, " ");
  if (!name || name.includes("@") || !/\p{L}/u.test(name)) return name;
  const lower = name.toLocaleLowerCase();
  const upper = name.toLocaleUpperCase();
  // Mixed case: the person typed it on purpose.
  if (name !== lower && name !== upper) return name;
  return lower.replace(
    WORD_START,
    (_, before: string, letter: string) => before + letter.toLocaleUpperCase(),
  );
}

/**
 * A person's first name and last initial ("Swamini F."), for a row with room
 * for a short label: a whole name cut mid-word reads worse (polish pass,
 * 24 Oct 2026). One-word names and emails stay whole.
 */
export function shortName(raw: string): string {
  const name = displayName(raw);
  if (name.includes("@")) return name;
  const [first, ...rest] = name.split(" ");
  const last = rest.at(-1);
  return last ? `${first} ${last[0]}.` : first;
}

/** displayName for a name that may be missing. */
export function displayNameOf<T extends string | null | undefined>(raw: T): T {
  return (typeof raw === "string" ? displayName(raw) : raw) as T;
}

/**
 * The same object with every listed key's string shown with capitals, at any
 * depth: for API answers whose people sit in lists and nested records.
 */
export function withDisplayNames<T>(value: T, keys: ReadonlySet<string>): T {
  if (Array.isArray(value))
    return value.map((item) => withDisplayNames(item, keys)) as T;
  if (!value || typeof value !== "object") return value;
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>))
    out[key] =
      typeof item === "string" && keys.has(key)
        ? displayName(item)
        : withDisplayNames(item, keys);
  return out as T;
}
