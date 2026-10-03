import { UUID } from "./acquisition-client";

export const REPORT_SECTIONS = [
  "overview",
  "transcript",
  "moments",
  "analysis",
  "coaching",
] as const;
// Other report readers still use these sections; retain their bookmarks.
const LEGACY_REPORT_SECTIONS = [
  "prospect",
  "skills",
  "next-call-plan",
] as const;
export type ReportSection =
  | (typeof REPORT_SECTIONS)[number]
  | (typeof LEGACY_REPORT_SECTIONS)[number];

function isSection(value: string): value is ReportSection {
  return (
    [...REPORT_SECTIONS, ...LEGACY_REPORT_SECTIONS] as readonly string[]
  ).includes(value);
}

/** A URL selects a panel of an already-authorized report, never job state. */
export function reportSectionFromSearch(
  search: string,
  boundCallId: string,
): ReportSection {
  const query = new URLSearchParams(search);
  const calls = query.getAll("call");
  const sections = query.getAll("section");
  if (
    !UUID.test(boundCallId) ||
    calls.length !== 1 ||
    calls[0] !== boundCallId ||
    sections.length !== 1 ||
    !isSection(sections[0])
  )
    return "overview";
  return sections[0];
}

/** Return only a same-page address. A stale report cannot retarget another call. */
export function reportSectionAddress(
  current: URL,
  boundCallId: string,
  section: string,
): string | null {
  if (!UUID.test(boundCallId) || !isSection(section)) return null;
  const query = new URLSearchParams(current.search);
  const calls = query.getAll("call");
  if (calls.length > 1 || (calls.length === 1 && calls[0] !== boundCallId))
    return null;
  query.set("call", boundCallId);
  query.delete("new");
  query.set("section", section);
  return `${current.pathname}?${query.toString()}${current.hash}`;
}
