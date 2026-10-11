/**
 * Plain-object guards for normalizers: every missing or wrong-typed field gets
 * a default instead of crashing a page. Pure, so server pages and client
 * islands share the same normalizers.
 */
export const read = {
  object(value: unknown): Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  },
  array(value: unknown): unknown[] {
    return Array.isArray(value) ? value : [];
  },
  string(value: unknown, fallback = ""): string {
    return typeof value === "string" ? value : fallback;
  },
  optionalString(value: unknown): string | null {
    return typeof value === "string" && value.length > 0 ? value : null;
  },
  number(value: unknown, fallback = 0): number {
    return typeof value === "number" && Number.isFinite(value)
      ? value
      : fallback;
  },
  optionalNumber(value: unknown): number | null {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  },
  boolean(value: unknown, fallback = false): boolean {
    return typeof value === "boolean" ? value : fallback;
  },
  strings(value: unknown): string[] {
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : [];
  },
};
