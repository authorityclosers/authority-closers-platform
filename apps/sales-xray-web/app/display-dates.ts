/**
 * How dates read on screen: the language they are written in, the time zone
 * that decides the day, and which day is today there. Pure helpers, used on
 * the server and in the browser alike (display-clock.tsx hands the browser's
 * own values to screens once the app has started).
 */
export type DisplayDates = Readonly<{
  /** A BCP 47 language tag, e.g. "en-IN". */
  locale: string;
  /** An IANA time zone, e.g. "Asia/Kolkata". */
  timeZone: string;
  /** Today in that zone, as YYYY-MM-DD. */
  today: string;
}>;

/** Where most of our users read: pages drawn on the server use India time. */
export const INDIA_TIME = "Asia/Kolkata";
export const INDIAN_ENGLISH = "en-IN";

const dayFormats = new Map<string, Intl.DateTimeFormat>();

/**
 * The calendar day an instant falls on in a time zone (the runtime's own when
 * none is given), as YYYY-MM-DD; null for an invalid date.
 */
export function dayKey(
  at: Date | number | string,
  timeZone?: string,
): string | null {
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return null;
  const cacheKey = timeZone ?? "";
  const format =
    dayFormats.get(cacheKey) ??
    new Intl.DateTimeFormat("en-GB", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
  dayFormats.set(cacheKey, format);
  const parts = format.formatToParts(date);
  const part = (type: string) =>
    parts.find((item) => item.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

/** Whole days from one YYYY-MM-DD day to another (negative if earlier). */
export function daysBetween(from: string, to: string): number {
  return Math.round(
    (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) /
      86_400_000,
  );
}

/** A language tag this runtime formats dates in, canonical; else null. */
export function displayLocale(tag: string | null | undefined): string | null {
  if (!tag) return null;
  try {
    const [supported] = Intl.DateTimeFormat.supportedLocalesOf([tag]);
    return supported
      ? new Intl.DateTimeFormat(supported).resolvedOptions().locale
      : null;
  } catch {
    return null;
  }
}

/** The first language an Accept-Language header asks for, if usable. */
export function acceptedLocale(header: string | null | undefined) {
  const first = header?.split(",")[0]?.split(";")[0]?.trim();
  return first && first !== "*" ? displayLocale(first) : null;
}

/**
 * How a page drawn on the server writes dates: in the language the browser
 * asked for (Indian English if none), in India time, as of now.
 */
export function serverDisplayDates(
  acceptLanguage: string | null | undefined,
  now = Date.now(),
): DisplayDates {
  return {
    locale: acceptedLocale(acceptLanguage) ?? INDIAN_ENGLISH,
    timeZone: INDIA_TIME,
    today: dayKey(now, INDIA_TIME) as string,
  };
}
