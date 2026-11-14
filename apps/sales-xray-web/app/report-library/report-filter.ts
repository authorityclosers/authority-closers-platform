/**
 * Which reports the Reports library shows (Dipak's Reports V4 spec, 13 Nov
 * 2026, sections 7-15): a search, one lead type and one date range, all
 * together, newest first. Pure: it only chooses what is visible and never
 * changes a report.
 *
 * Lead type (section 9). Every report has exactly one source, from what the
 * server stored: "Inbound leads (Auto-uploaded)" and "Cold leads
 * (Auto-uploaded)" are calls the phone captured and uploaded itself, by the
 * side of the lead they belong to; "Manually Uploaded" is a recording someone
 * chose and sent. "Saved Reports" is the person's own Save on a report
 * (PUT /submissions/{id}/saved): it lists every report they saved, whatever
 * its source, and the other three ignore it. An auto-uploaded call no lead
 * names counts as Inbound, as Lead Desk reads an empty side.
 */

export type ReportSource = "inbound_auto" | "cold_auto" | "manual";
export type LeadTypeFilter = ReportSource | "saved";

/** The dropdown's words, in its order (section 9). */
export const LEAD_TYPE_OPTIONS: readonly {
  key: LeadTypeFilter;
  label: string;
}[] = [
  { key: "inbound_auto", label: "Inbound leads (Auto-uploaded)" },
  { key: "cold_auto", label: "Cold leads (Auto-uploaded)" },
  { key: "manual", label: "Manually Uploaded" },
  { key: "saved", label: "Saved Reports" },
];
export const ALL_LEAD_TYPES = "All lead types";

/** A report card's lead type (section 16 A). */
export const SOURCE_LABEL: Record<ReportSource, string> = {
  inbound_auto: "Inbound · Auto",
  cold_auto: "Cold · Auto",
  manual: "Manual upload",
};
export const SAVED_LABEL = "Saved report";

export function leadTypeLabel(key: LeadTypeFilter): string {
  return LEAD_TYPE_OPTIONS.find((option) => option.key === key)?.label ?? key;
}

export function isLeadTypeFilter(value: unknown): value is LeadTypeFilter {
  return LEAD_TYPE_OPTIONS.some((option) => option.key === value);
}

/** One report as the library shows and filters it. */
export type ReportRow = Readonly<{
  id: string;
  /** The stored creation time (ISO 8601): sorting and dates come from it. */
  createdAt: string;
  createdMs: number;
  /** The calendar day it was created on in the reader's time zone (YYYY-MM-DD). */
  day: string;
  /** The lead's name, or null when no lead names the call. */
  prospect: string | null;
  topic: string;
  summary: string | null;
  durationSeconds: number;
  /** "Report ready", "Analysis in progress", … (call-status.ts). */
  status: string;
  ready: boolean;
  /** Analysis under way: the list reads again until it settles. */
  active: boolean;
  source: ReportSource;
  saved: boolean;
  /** Whose call, when an owner or admin sees the team's calls. */
  owner: string | null;
}>;

/** Where the library stands: search words, lead type, and a From–To range. */
export type ReportQuery = Readonly<{
  query: string;
  leadType: LeadTypeFilter | null;
  /** YYYY-MM-DD, both or neither (an incomplete range is never applied). */
  from: string | null;
  to: string | null;
}>;

export const NO_FILTERS: ReportQuery = {
  query: "",
  leadType: null,
  from: null,
  to: null,
};

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

export function isDay(value: unknown): value is string {
  return (
    typeof value === "string" &&
    ISO_DAY.test(value) &&
    !Number.isNaN(Date.parse(`${value}T00:00:00Z`))
  );
}

/** A range that can be applied: both days, From not after To. */
export function completeRange(
  from: string | null,
  to: string | null,
): { from: string; to: string } | null {
  if (!isDay(from) || !isDay(to) || from > to) return null;
  return { from, to };
}

/** Lead type and a complete date range count one each (section 14). */
export function activeFilterCount(filters: ReportQuery): number {
  return (
    Number(filters.leadType !== null) +
    Number(completeRange(filters.from, filters.to) !== null)
  );
}

/** The words a search matches for a report, lower case (section 7). */
function haystack(row: ReportRow): string {
  const words = [
    row.prospect ?? "",
    row.topic,
    row.summary ?? "",
    SOURCE_LABEL[row.source],
    leadTypeLabel(row.source),
  ];
  if (row.saved) words.push(SAVED_LABEL, leadTypeLabel("saved"));
  return words.join(" \u0000 ").toLocaleLowerCase();
}

export function matchesLeadType(
  row: ReportRow,
  leadType: LeadTypeFilter | null,
): boolean {
  if (leadType === null) return true;
  if (leadType === "saved") return row.saved;
  return row.source === leadType;
}

export function matchesReport(row: ReportRow, filters: ReportQuery): boolean {
  if (!matchesLeadType(row, filters.leadType)) return false;
  const range = completeRange(filters.from, filters.to);
  if (range && (row.day < range.from || row.day > range.to)) return false;
  const needle = filters.query.trim().toLocaleLowerCase();
  return !needle || haystack(row).includes(needle);
}

/** Newest first by the stored time (section 12); ties keep one fixed order. */
export function newestFirst(rows: readonly ReportRow[]): ReportRow[] {
  return [...rows].sort(
    (a, b) => b.createdMs - a.createdMs || (a.id < b.id ? 1 : -1),
  );
}

export function visibleReports(
  rows: readonly ReportRow[],
  filters: ReportQuery,
): ReportRow[] {
  return newestFirst(rows.filter((row) => matchesReport(row, filters)));
}

/** "10 of 10 reports", "3 of 10 reports · Filtered" (section 15). */
export function countLine(
  shown: number,
  total: number,
  filters: ReportQuery,
): string {
  const noun = total === 1 ? "report" : "reports";
  return `${shown} of ${total} ${noun}${activeFilterCount(filters) ? " · Filtered" : ""}`;
}

/** The sheet's main button (section 11): "Show all reports", "Show 2 reports". */
export function showButtonLabel(shown: number, total: number): string {
  if (shown === total && total > 0) return "Show all reports";
  return `Show ${shown} ${shown === 1 ? "report" : "reports"}`;
}

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function parts(day: string): [number, number, number] {
  const [year, month, date] = day.split("-").map(Number);
  return [year, month, date];
}

/** "1 Nov 2026" (the From and To fields). */
export function dayWords(day: string): string {
  const [year, month, date] = parts(day);
  return `${date} ${MONTHS[month - 1]} ${year}`;
}

/** "1 November 2026" (a calendar day's name for screen readers). */
export function longDayWords(day: string): string {
  const [year, month, date] = parts(day);
  return `${date} ${MONTH_NAMES[month - 1]} ${year}`;
}

/** "November 2026" (the calendar's head). */
export function monthWords(year: number, month: number): string {
  return `${MONTH_NAMES[month]} ${year}`;
}

/** The date chip: "1 Nov – 13 Nov 2026", or with both years when they differ. */
export function rangeWords(from: string, to: string): string {
  const [fromYear, fromMonth, fromDate] = parts(from);
  const end = dayWords(to);
  const start =
    fromYear === parts(to)[0]
      ? `${fromDate} ${MONTHS[fromMonth - 1]}`
      : dayWords(from);
  return `${start} – ${end}`;
}

/** YYYY-MM-DD for a calendar cell (month is 0-based). */
export function isoDay(year: number, month: number, date: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(date).padStart(2, "0")}`;
}

/**
 * The calendar's next selection after a tap (section 10): the first tap sets
 * From, the next sets To; a day before From starts again from it; a tap while
 * From is being chosen moves From and drops a To that would end before it.
 */
export function pickDay(
  state: { from: string | null; to: string | null; picking: "from" | "to" },
  day: string,
): { from: string | null; to: string | null; picking: "from" | "to" } {
  if (state.picking === "from" || !state.from) {
    const to = state.to && state.to < day ? null : state.to;
    return { from: day, to, picking: "to" };
  }
  if (day < state.from) return { from: day, to: null, picking: "to" };
  return { from: state.from, to: day, picking: "from" };
}

/**
 * A card's summary (section 16 E: "approximately two lines"): the Report's
 * first sentence, with the next one when the first is short. Whole sentences
 * only, never a sentence cut off; the search still reads the whole summary.
 */
export function summaryLine(summary: string): string {
  const text = summary.replace(/\s+/g, " ").trim();
  const sentences = text.split(/(?<=[.!?])\s+(?=[\p{Lu}\p{N}"“])/u);
  const first = sentences[0] ?? text;
  const both = sentences[1] ? `${first} ${sentences[1]}` : first;
  return first.length < 60 && both.length <= 140 ? both : first;
}
