/**
 * Stable initials for self-scoped identity fallbacks.
 *
 * This is presentation-only. It never becomes an identity or authorization
 * value, and it deliberately uses the surname initial for multi-word names.
 */
export function initialsForDisplayName(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "AC";

  const first = Array.from(parts[0] ?? "")[0] ?? "";
  const surname =
    parts.length > 1 ? (Array.from(parts.at(-1) ?? "")[0] ?? "") : "";
  return `${first}${surname}`.toUpperCase() || "AC";
}
