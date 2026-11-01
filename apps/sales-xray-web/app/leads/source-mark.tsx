/**
 * Where a lead came from, at a glance (owner, 31 Oct 2026): a small mark and a
 * short name on the row ("Website · SOC Analyst", not "Website:
 * /courses/soc-analyst"); the full source stays in the row's tooltip.
 */

import {
  FileUp,
  Globe,
  Hand,
  Handshake,
  Inbox,
  Infinity as MetaLoop,
  Sheet,
} from "lucide-react";

import type { LeadRow } from "./leads-client";
import styles from "./leads.module.css";

export type SourceKind =
  | "meta"
  | "google"
  | "website"
  | "sheet"
  | "file"
  | "manual"
  | "referral"
  | "other";

type Source = Pick<LeadRow, "source" | "source_label">;

/** Where the lead came from, as a seller would say it. */
export function sourceText(row: Source): string {
  if (row.source === "synthetic") {
    const kind = row.source_label.split("·").pop()?.trim() ?? "";
    return kind ? kind[0].toUpperCase() + kind.slice(1) : "Lead";
  }
  // A file's own list name from its Source column (ph1-18): "Expo list".
  if (row.source === "csv")
    return /^File: | export: /.test(row.source_label)
      ? "File upload"
      : row.source_label;
  return row.source_label.replace(/^Sheet: /, "Sheet · ");
}

export function sourceKind(row: Source): SourceKind {
  const label = row.source_label ?? "";
  if (row.source === "meta") return "meta";
  if (row.source === "google_ads" || /google ads/i.test(label)) return "google";
  if (row.source === "sheet" || /^sheet:/i.test(label)) return "sheet";
  if (row.source === "csv") return "file";
  if (row.source === "manual") return "manual";
  if (row.source === "referral") return "referral";
  if (row.source === "webhook" || /^website\b/i.test(label)) return "website";
  return "other";
}

// Short words that stay words; any other of two or three letters is an
// abbreviation ("soc-analyst" is SOC Analyst).
const WORDS = new Set(
  "a an and the for of to in on by at or our new top pro how why you get buy now all web app day one two use job its".split(
    " ",
  ),
);

/** A page's address as words: "/courses/soc-analyst" is "SOC Analyst". */
export function pageWords(path: string): string {
  const page =
    path
      .replace(/^https?:\/\/[^/]+/i, "")
      .split(/[?#]/)[0]
      .split("/")
      .filter(Boolean)
      .pop() ?? "";
  return page
    .replace(/\.[a-z0-9]+$/i, "")
    .split(/[-_+\s]+/)
    .filter(Boolean)
    .map((word) =>
      word.length <= 3 && !WORDS.has(word.toLowerCase())
        ? word.toUpperCase()
        : word[0].toUpperCase() + word.slice(1).toLowerCase(),
    )
    .join(" ");
}

/** The source in a few words for a row. */
export function shortSource(row: Source): string {
  const label = (row.source_label ?? "").trim();
  switch (sourceKind(row)) {
    case "meta":
      return "Meta Ads";
    case "google":
      return "Google Ads";
    case "website": {
      const named = label.match(/^website\s*[:·-]\s*(.+)$/i)?.[1] ?? null;
      const path = named ?? (/^(\/|https?:)/i.test(label) ? label : null);
      if (path === null) return "Website";
      const page = /^(\/|https?:)/i.test(path) ? pageWords(path) : path;
      return page ? `Website · ${page}` : "Website";
    }
    default:
      return sourceText(row);
  }
}

/** Google's own four-colour "G". */
function GoogleG() {
  return (
    <svg
      className={styles.sourceMark}
      viewBox="0 0 48 48"
      aria-hidden="true"
      focusable="false"
    >
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"
      />
      <path
        fill="#FF3D00"
        d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"
      />
    </svg>
  );
}

const ICONS = {
  meta: MetaLoop,
  website: Globe,
  sheet: Sheet,
  file: FileUp,
  manual: Hand,
  referral: Handshake,
  other: Inbox,
} as const;

/** The source's mark: Google's G, else a small icon in the source's colour. */
export function SourceMark({ kind }: { kind: SourceKind }) {
  if (kind === "google") return <GoogleG />;
  const Icon = ICONS[kind];
  return (
    <Icon
      size={13}
      aria-hidden="true"
      className={styles.sourceMark}
      data-kind={kind}
    />
  );
}
